"""Job identity, builder, atomic writes, and Result consumption. Pure aside from filesystem writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .protocol import (
    bind_authoritative_job_hash,
    bind_result,
    checks_passed,
    digest_canonical,
    expectation_from_job,
    harness_canonical_json,
    job_document_sha256,
    parse_verification_document,
    require_absolute_path,
    require_sha256,
    result_digest,
    review_verdict_from_result,
    sha256_file_if_exists,
    validate_completed_result,
    validate_job_document,
)
from .types import (
    ALLOWED_ADAPTERS,
    ARTIFACT_SCHEMA,
    JOB_SCHEMA,
    STAGE_INPUT_KINDS,
    STAGE_OUTPUT,
    STAGE_PERMISSIONS,
    STAGE_PROFILES,
    THINKING_LEVELS,
    TRANSPORT_FAILURE_STATUSES,
    VERIFICATION_STAGES,
    ArtifactRef,
    WorkflowConflict,
    WorkflowProtocolError,
    WorkflowStatus,
)

ConsumeKind = Literal[
    "noop",
    "consumed",
    "protocol_failure",
    "transport_failure",
    "precondition_failure",
]
DEFAULT_CHECK_TIMEOUT_SECONDS = 1800  # real-CLI smoke checks legitimately take minutes


@dataclass(frozen=True)
class ConsumeOutcome:
    kind: ConsumeKind
    next_status: WorkflowStatus | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    session_id: str | None = None
    review_verdict: str | None = None
    result_sha256: str | None = None
    reason: str | None = None


def make_idempotency_key(
    *,
    board: str,
    task_id: str,
    stage: str,
    business_attempt: int,
    transport_retry: int,
    input_sha_prefix: str,
) -> str:
    return f"{board}:{task_id}:{stage}:{business_attempt}:{transport_retry}:{input_sha_prefix}"


def make_job_id(idempotency_key: str) -> str:
    return "job_" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]


def input_sha_prefix(inputs: Sequence[Mapping[str, Any]]) -> str:
    material = [{"kind": item["kind"], "path": item["path"], "sha256": item["sha256"]} for item in inputs]
    encoded = harness_canonical_json(material)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _require_adapter(value: Any, what: str) -> str:
    if value not in ALLOWED_ADAPTERS:
        raise WorkflowProtocolError(f"{what} must be one of {sorted(ALLOWED_ADAPTERS)}, got {value!r}")
    return str(value)


def resolve_agent_selection(
    *,
    stage: str,
    agents: Mapping[str, Mapping[str, str]] | None,
    stage_agents: Mapping[str, Mapping[str, str]] | None = None,
    agent_selection: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve {adapter, model, thinking} for one Job.

    Precedence: frozen ``agent_selection`` (manifest binding / restart
    recovery) > ``stage_agents[stage]`` (exact Stage config) > legacy
    ``agents[STAGE_PROFILES[stage]]`` with adapter defaulting to ``pi``.
    """
    if stage not in STAGE_PROFILES:
        raise WorkflowProtocolError(f"unknown job stage {stage!r}")
    if agent_selection is not None:
        if not isinstance(agent_selection, Mapping):
            raise WorkflowProtocolError("agent_selection must be an object")
        return {
            "adapter": _require_adapter(agent_selection.get("adapter"), "agent_selection.adapter"),
            "model": _require_nonempty(agent_selection.get("model"), "agent_selection.model"),
            "thinking": _require_nonempty(agent_selection.get("thinking"), "agent_selection.thinking"),
        }
    spec = (stage_agents or {}).get(stage)
    if spec is not None:
        if not isinstance(spec, Mapping):
            raise WorkflowProtocolError(f"stage_agents[{stage}] must be an object")
        thinking = spec.get("thinking")
        if thinking not in THINKING_LEVELS:
            raise WorkflowProtocolError(
                f"stage_agents[{stage}].thinking must be one of {sorted(THINKING_LEVELS)}"
            )
        return {
            "adapter": _require_adapter(spec.get("adapter"), f"stage_agents[{stage}].adapter"),
            "model": _require_nonempty(spec.get("model"), f"stage_agents[{stage}].model"),
            "thinking": str(thinking),
        }
    profile = STAGE_PROFILES[stage]
    legacy = (agents or {}).get(profile)
    if not isinstance(legacy, Mapping) or not legacy.get("model") or not legacy.get("thinking"):
        raise WorkflowProtocolError(f"missing model/thinking for profile {profile}")
    adapter = legacy.get("adapter") or "pi"
    return {
        "adapter": _require_adapter(adapter, f"agents[{profile}].adapter"),
        "model": str(legacy["model"]),
        "thinking": str(legacy["thinking"]),
    }


def _require_nonempty(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowProtocolError(f"{what} must be a non-empty string")
    return value


def build_job(
    *,
    board: str,
    task_id: str,
    stage: str,
    business_attempt: int,
    transport_retry: int,
    workspace: Mapping[str, Any],
    agents: Mapping[str, Mapping[str, str]],
    inputs: Sequence[Mapping[str, Any]],
    session_id: str | None,
    verification: Sequence[Mapping[str, Any]] = (),
    previous_check_failures: Sequence[Mapping[str, Any]] | None = None,
    timeout_seconds: int | None = None,
    template_id: str | None = None,
    stage_agents: Mapping[str, Mapping[str, str]] | None = None,
    agent_selection: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if stage not in STAGE_OUTPUT:
        raise WorkflowProtocolError(f"unknown job stage {stage!r}")
    if template_id is not None:
        from .templates import get_template

        template = get_template(template_id)
        if stage not in template.allowed_stages:
            raise WorkflowProtocolError(f"stage {stage!r} is not allowed for template {template_id}")
    if business_attempt < 1 or transport_retry < 0:
        raise WorkflowProtocolError("business_attempt must be >= 1 and transport_retry >= 0")
    if stage in VERIFICATION_STAGES and not verification:
        raise WorkflowProtocolError(f"{stage} jobs require at least one verification check")
    profile = STAGE_PROFILES[stage]
    selection = resolve_agent_selection(
        stage=stage,
        agents=agents,
        stage_agents=stage_agents,
        agent_selection=agent_selection,
    )
    if verification and stage not in VERIFICATION_STAGES:
        raise WorkflowProtocolError("verification is only allowed on implement and direct_implement jobs")
    bound_inputs = tuple(_bind_input(item, index) for index, item in enumerate(inputs))
    required = STAGE_INPUT_KINDS[stage]
    kinds = tuple(item["kind"] for item in bound_inputs)
    if kinds != required:
        raise WorkflowProtocolError(f"stage {stage} requires inputs {required}")
    output_kind, output_schema = STAGE_OUTPUT[stage]
    reviewer = stage in {"plan_review", "execute_review"}
    agent_session = None if reviewer else session_id
    identity_inputs = list(bound_inputs)
    if stage == "direct_implement":
        identity_inputs.append(
            {
                "kind": "verification",
                "path": "verification",
                "sha256": digest_canonical(list(verification)),
            }
        )
    prefix = input_sha_prefix(identity_inputs)
    idempotency_key = make_idempotency_key(
        board=board,
        task_id=task_id,
        stage=stage,
        business_attempt=business_attempt,
        transport_retry=transport_retry,
        input_sha_prefix=prefix,
    )
    job = {
        "schema": JOB_SCHEMA,
        "jobId": make_job_id(idempotency_key),
        "idempotencyKey": idempotency_key,
        "taskId": task_id,
        "stage": stage,
        "attempt": business_attempt,
        "workspace": {
            "repoRoot": require_absolute_path(workspace.get("repoRoot"), "workspace.repoRoot"),
            "branch": workspace["branch"],
            "expectedHead": workspace["expectedHead"],
            "requireCleanAtStart": bool(workspace.get("requireCleanAtStart", True)),
        },
        "agent": {
            "adapter": selection["adapter"],
            "profile": profile,
            "model": selection["model"],
            "thinking": selection["thinking"],
            "sessionId": agent_session,
        },
        "permissions": {"mode": STAGE_PERMISSIONS[stage]},
        "inputs": [
            {"kind": item["kind"], "path": item["path"], "sha256": item["sha256"]}
            for item in bound_inputs
        ],
        "expectedOutput": {"kind": output_kind, "schema": output_schema},
        "verification": [dict(item) for item in verification],
        "limits": {"timeoutSeconds": timeout_seconds},
    }
    if previous_check_failures:
        if stage not in VERIFICATION_STAGES:
            raise WorkflowProtocolError(
                "previous_check_failures is only allowed on implement and direct_implement jobs"
            )
        job["previousCheckFailures"] = [dict(item) for item in previous_check_failures]
    validate_job_document(job)
    return job


def write_job_document(job: Mapping[str, Any], run_dir: str | Path) -> dict[str, str]:
    validate_job_document(job)
    directory = Path(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "job.json"
    hash_path = directory / "job.sha256"
    payload = harness_canonical_json(job)
    digest = job_document_sha256(job)
    if path.exists():
        existing = json_load_if_possible(path)
        if existing is None or job_document_sha256(existing) != digest:
            raise WorkflowConflict("job document identity conflict")
        _write_job_sha256(hash_path, digest)
        return {
            "job_path": str(path),
            "run_dir": str(directory),
            "job_sha256": digest,
        }
    tmp = directory / ".job.json.tmp"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    _write_job_sha256(hash_path, digest)
    return {
        "job_path": str(path),
        "run_dir": str(directory),
        "job_sha256": digest,
    }


def _write_job_sha256(hash_path: Path, digest: str) -> None:
    tmp = hash_path.with_name(".job.sha256.tmp")
    tmp.write_text(f"{digest}\n", encoding="utf-8")
    tmp.replace(hash_path)


def consume_result(
    job: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    previously_consumed_sha256: str | None = None,
    expected_job_sha256: str | None = None,
) -> ConsumeOutcome:
    digest = result_digest(result)
    if previously_consumed_sha256 is not None:
        if previously_consumed_sha256 == digest:
            return ConsumeOutcome(kind="noop", result_sha256=digest)
        raise WorkflowConflict("different Result bound to the same Job")
    try:
        bound_job_sha256 = bind_authoritative_job_hash(job, expected_job_sha256)
        expectation = expectation_from_job(job, job_sha256=bound_job_sha256)
        bind_result(expectation, result)
    except WorkflowProtocolError as exc:
        return ConsumeOutcome(
            kind="protocol_failure",
            result_sha256=digest,
            reason=str(exc),
        )
    status = result.get("status")
    if _is_preflight_workspace_mismatch(result):
        error = result.get("error")
        message = (
            str(error.get("message") or "workspace mismatch")
            if isinstance(error, Mapping)
            else "workspace mismatch"
        )
        return ConsumeOutcome(
            kind="precondition_failure",
            result_sha256=digest,
            reason=f"precondition failure: workspace_mismatch: {message}",
        )
    if status in TRANSPORT_FAILURE_STATUSES:
        return ConsumeOutcome(
            kind="transport_failure",
            result_sha256=digest,
            reason=str(status),
            session_id=result.get("sessionId") if isinstance(result.get("sessionId"), str) and result.get("sessionId").strip() else None,
        )
    try:
        validate_completed_result(
            expectation,
            result,
            job=job,
            expected_job_sha256=bound_job_sha256,
        )
    except WorkflowProtocolError as exc:
        return ConsumeOutcome(
            kind="protocol_failure",
            result_sha256=digest,
            reason=str(exc),
        )
    artifacts = tuple(_canonical_artifacts(result))
    session_id = result.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        session_id = None
    verdict = review_verdict_from_result(result)
    payload_outcome = _payload_outcome(result)
    next_status = _next_status_for_completed(job["stage"], verdict, outcome=payload_outcome)
    return ConsumeOutcome(
        kind="consumed",
        next_status=next_status,
        artifacts=artifacts,
        session_id=session_id,
        review_verdict=verdict,
        result_sha256=digest,
    )


def decide_verification(result_or_checks: Any) -> Literal["passed", "failed"]:
    return "passed" if checks_passed(result_or_checks) else "failed"


def json_load_if_possible(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _bind_input(item: Mapping[str, Any], index: int) -> dict[str, str]:
    kind = item.get("kind")
    if not isinstance(kind, str) or not kind:
        raise WorkflowProtocolError(f"inputs[{index}].kind is required")
    path = require_absolute_path(item.get("path"), f"inputs[{index}].path")
    expected = require_sha256(item.get("sha256"), f"inputs[{index}].sha256")
    actual = sha256_file_if_exists(path)
    if actual != expected:
        raise WorkflowProtocolError(f"inputs[{index}] SHA-256 does not match file contents")
    return {"kind": kind, "path": path, "sha256": expected}


def verification_from_plan_input(
    plan_input: Mapping[str, Any],
    *,
    repo_root: str,
    timeout_seconds: int = DEFAULT_CHECK_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], ...]:
    """Translate canonical plan.v1 verification commands into Harness checks."""
    if timeout_seconds < 1:
        raise WorkflowProtocolError("verification timeout_seconds must be positive")
    bound = _bind_input(plan_input, 0)
    if bound["kind"] != "plan":
        raise WorkflowProtocolError("implement verification requires a plan input")
    document = json_load_if_possible(Path(bound["path"]))
    if document is None:
        raise WorkflowProtocolError("plan Artifact is not valid JSON")
    if document.get("schema") != ARTIFACT_SCHEMA or document.get("kind") != "plan":
        raise WorkflowProtocolError("plan input must be a canonical plan Artifact")
    payload = document.get("payload")
    if not isinstance(payload, Mapping) or payload.get("schema") != "plan.v1":
        raise WorkflowProtocolError("plan Artifact payload must use plan.v1")
    if payload.get("outcome") != "completed":
        raise WorkflowProtocolError("implement verification requires a completed plan")
    raw_checks = payload.get("verification")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise WorkflowProtocolError("completed plan requires at least one verification check")

    root = Path(require_absolute_path(repo_root, "repo_root")).resolve()
    checks: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_checks):
        if not isinstance(raw, Mapping):
            raise WorkflowProtocolError(f"plan.verification[{index}] must be an object")
        check_id = raw.get("id")
        if not isinstance(check_id, str) or not check_id:
            raise WorkflowProtocolError(f"plan.verification[{index}].id is required")
        argv = raw.get("argv")
        if not isinstance(argv, list) or not argv or any(
            not isinstance(item, str) or not item for item in argv
        ):
            raise WorkflowProtocolError(
                f"plan.verification[{index}].argv must be a non-empty string array"
            )
        raw_cwd = raw.get("cwd")
        if raw_cwd == ".":
            cwd = root
        elif isinstance(raw_cwd, str) and raw_cwd and not Path(raw_cwd).is_absolute():
            cwd = (root / raw_cwd).resolve()
        else:
            raise WorkflowProtocolError(
                f"plan.verification[{index}].cwd must be repo-relative"
            )
        try:
            cwd.relative_to(root)
        except ValueError as exc:
            raise WorkflowProtocolError(
                f"plan.verification[{index}].cwd escapes repo_root"
            ) from exc
        raw_timeout = raw.get("timeoutSeconds")
        if raw_timeout is None:
            check_timeout = timeout_seconds
        elif isinstance(raw_timeout, bool) or not isinstance(raw_timeout, int) or raw_timeout < 1:
            raise WorkflowProtocolError(
                f"plan.verification[{index}].timeoutSeconds must be a positive integer"
            )
        else:
            check_timeout = raw_timeout
        checks.append(
            {
                "id": check_id,
                "argv": list(argv),
                "cwd": str(cwd),
                "timeoutSeconds": check_timeout,
                "expectedExitCode": 0,
            }
        )
    return tuple(checks)


def verification_from_intake_artifact(
    verification_input: Mapping[str, Any],
    *,
    repo_root: str,
) -> tuple[dict[str, Any], ...]:
    bound = _bind_input(verification_input, 0)
    if bound["kind"] != "verification":
        raise WorkflowProtocolError("direct verification requires a verification Artifact")
    document = json_load_if_possible(Path(bound["path"]))
    if document is None:
        raise WorkflowProtocolError("verification Artifact is not valid JSON")
    parsed = parse_verification_document(document, repo_root=repo_root)
    root = Path(require_absolute_path(repo_root, "repo_root")).resolve()
    checks: list[dict[str, Any]] = []
    for item in parsed["checks"]:
        raw_cwd = item["cwd"]
        cwd = root if raw_cwd == "." else (root / raw_cwd).resolve()
        checks.append(
            {
                "id": item["id"],
                "argv": list(item["argv"]),
                "cwd": str(cwd),
                "timeoutSeconds": item["timeoutSeconds"],
                "expectedExitCode": item["expectedExitCode"],
            }
        )
    return tuple(checks)


def _canonical_artifacts(result: Mapping[str, Any]) -> tuple[ArtifactRef, ...]:
    from .protocol import parse_artifact_ref

    raw = result.get("artifacts") or []
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in (parse_artifact_ref(entry) for entry in raw) if item.canonical)


def _is_preflight_workspace_mismatch(result: Mapping[str, Any]) -> bool:
    """True for a Harness *preflight* workspace failure (no adapter ran yet).

    The coding-agent harness validates branch/HEAD/clean-tree before the
    agent starts. Such a Result carries status ``failed``, error kind
    ``workspace_mismatch``, and an empty ``paths.adapterRuns``. It means the
    environment premise was not met — not transport-layer jitter — so it must
    not burn the transport-retry budget (``MAX_STAGE_TRANSPORT_FAILURES``).
    A workspace_mismatch recorded after an adapter ran (postflight guard)
    keeps the transport-failure classification.
    """
    if result.get("status") != "failed":
        return False
    error = result.get("error")
    if not isinstance(error, Mapping) or error.get("kind") != "workspace_mismatch":
        return False
    paths = result.get("paths")
    runs = paths.get("adapterRuns") if isinstance(paths, Mapping) else None
    return not (isinstance(runs, list) and runs)


def _payload_outcome(result: Mapping[str, Any]) -> str | None:
    output = result.get("structuredOutput")
    if not isinstance(output, Mapping):
        return None
    payload = output.get("payload")
    if not isinstance(payload, Mapping):
        return None
    outcome = payload.get("outcome")
    return outcome if isinstance(outcome, str) else None


def _next_status_for_completed(
    stage: str, verdict: str | None, *, outcome: str | None = None
) -> WorkflowStatus:
    from .templates import DIRECT_TEMPLATE, FULL_TEMPLATE

    template = DIRECT_TEMPLATE if stage == "direct_implement" else FULL_TEMPLATE
    return template.completed_next_status(stage, verdict=verdict, outcome=outcome)
