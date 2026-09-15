"""Job identity, builder, atomic writes, and Result consumption. Pure aside from filesystem writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .protocol import (
    bind_result,
    checks_passed,
    expectation_from_job,
    harness_canonical_json,
    job_document_sha256,
    require_absolute_path,
    require_sha256,
    result_digest,
    review_verdict_from_result,
    sha256_file_if_exists,
    validate_completed_result,
    validate_job_document,
)
from .types import (
    JOB_SCHEMA,
    STAGE_INPUT_KINDS,
    STAGE_OUTPUT,
    STAGE_PERMISSIONS,
    STAGE_PROFILES,
    TRANSPORT_FAILURE_STATUSES,
    ArtifactRef,
    WorkflowConflict,
    WorkflowProtocolError,
    WorkflowStatus,
)

ConsumeKind = Literal["noop", "consumed", "protocol_failure", "transport_failure"]


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
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    if stage not in STAGE_OUTPUT:
        raise WorkflowProtocolError(f"unknown job stage {stage!r}")
    if business_attempt < 1 or transport_retry < 0:
        raise WorkflowProtocolError("business_attempt must be >= 1 and transport_retry >= 0")
    profile = STAGE_PROFILES[stage]
    agent_spec = agents.get(profile)
    if not isinstance(agent_spec, Mapping) or not agent_spec.get("model") or not agent_spec.get("thinking"):
        raise WorkflowProtocolError(f"missing model/thinking for profile {profile}")
    if verification and stage != "implement":
        raise WorkflowProtocolError("verification is only allowed on implement jobs")
    bound_inputs = tuple(_bind_input(item, index) for index, item in enumerate(inputs))
    required = STAGE_INPUT_KINDS[stage]
    kinds = tuple(item["kind"] for item in bound_inputs)
    if kinds != required:
        raise WorkflowProtocolError(f"stage {stage} requires inputs {required}")
    output_kind, output_schema = STAGE_OUTPUT[stage]
    reviewer = stage in {"plan_review", "execute_review"}
    agent_session = None if reviewer else session_id
    prefix = input_sha_prefix(bound_inputs)
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
            "adapter": "pi",
            "profile": profile,
            "model": agent_spec["model"],
            "thinking": agent_spec["thinking"],
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
) -> ConsumeOutcome:
    digest = result_digest(result)
    if previously_consumed_sha256 is not None:
        if previously_consumed_sha256 == digest:
            return ConsumeOutcome(kind="noop", result_sha256=digest)
        raise WorkflowConflict("different Result bound to the same Job")
    try:
        expectation = expectation_from_job(job)
        bind_result(expectation, result)
    except WorkflowProtocolError as exc:
        return ConsumeOutcome(
            kind="protocol_failure",
            result_sha256=digest,
            reason=str(exc),
        )
    status = result.get("status")
    if status in TRANSPORT_FAILURE_STATUSES:
        return ConsumeOutcome(
            kind="transport_failure",
            result_sha256=digest,
            reason=str(status),
            session_id=result.get("sessionId") if isinstance(result.get("sessionId"), str) else None,
        )
    try:
        validate_completed_result(expectation, result)
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
    next_status = _next_status_for_completed(job["stage"], verdict)
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


def _canonical_artifacts(result: Mapping[str, Any]) -> tuple[ArtifactRef, ...]:
    from .protocol import parse_artifact_ref

    raw = result.get("artifacts") or []
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in (parse_artifact_ref(entry) for entry in raw) if item.canonical)


def _next_status_for_completed(stage: str, verdict: str | None) -> WorkflowStatus:
    if stage == "plan":
        return WorkflowStatus.PLAN_REVIEWING
    if stage == "implement":
        return WorkflowStatus.VERIFYING
    if stage == "plan_review":
        if verdict == "approved":
            return WorkflowStatus.IMPLEMENTING
        if verdict == "request_changes":
            return WorkflowStatus.PLAN_REWORK
        return WorkflowStatus.BLOCKED
    if stage == "execute_review":
        if verdict == "approved":
            return WorkflowStatus.PRODUCT_ACCEPTANCE
        if verdict == "request_changes":
            return WorkflowStatus.IMPLEMENT_REWORK
        return WorkflowStatus.BLOCKED
    raise WorkflowProtocolError(f"cannot consume stage {stage}")
