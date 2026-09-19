"""Pure validators for Workflow, Job, Result, Artifact, and Acceptance payloads."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .templates import get_template
from .types import (
    ALLOWED_ADAPTERS,
    ARTIFACT_SCHEMA,
    GIT_HEAD_PATTERN,
    ISO_TIMESTAMP_PATTERN,
    JOB_SCHEMA,
    RESULT_CHECK_FIELD_KEYS,
    RESULT_SCHEMA,
    REVIEW_OUTPUT_KINDS,
    REVIEWER_STAGES,
    RESUME_STAGES,
    SHA256_PATTERN,
    STAGE_AGENT_STAGES,
    STAGE_INPUT_KINDS,
    STAGE_OUTPUT,
    STAGE_PERMISSIONS,
    STAGE_PROFILES,
    TRANSPORT_FAILURE_STATUSES,
    VERIFICATION_CHECK_FIELDS,
    VERIFICATION_SCHEMA,
    VERIFICATION_STAGES,
    WORKFLOW_SCHEMA,
    WORKFLOW_TEMPLATE_ID,
    AcceptanceFinding,
    AcceptanceScenario,
    AcceptanceSubmission,
    ArtifactRef,
    GitBaseline,
    JobExpectation,
    WorkflowManifest,
    WorkflowProtocolError,
    WorkflowStatus,
)

_SHA256 = re.compile(SHA256_PATTERN)
_GIT_HEAD = re.compile(GIT_HEAD_PATTERN)
_ISO_TIMESTAMP = re.compile(ISO_TIMESTAMP_PATTERN)
_ACCEPTANCE_VERDICTS = frozenset({"passed", "failed", "needs_human", "blocked"})
_SCENARIO_STATUSES = frozenset({"passed", "failed"})
_FINDING_SEVERITIES = frozenset({"blocking", "warning"})


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkflowProtocolError(f"{what} must be an object")
    return value


def _require_str(value: Any, what: str, *, allow_blank: bool = False) -> str:
    if not isinstance(value, str):
        raise WorkflowProtocolError(f"{what} must be a string")
    text = value.strip() if allow_blank else value
    if not allow_blank and not text.strip():
        raise WorkflowProtocolError(f"{what} must be non-empty")
    return value if allow_blank else text


def _optional_str(value: Any, what: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, what)


def _require_bool(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise WorkflowProtocolError(f"{what} must be a boolean")
    return value


def _require_int(value: Any, what: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkflowProtocolError(f"{what} must be an integer")
    if minimum is not None and value < minimum:
        raise WorkflowProtocolError(f"{what} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise WorkflowProtocolError(f"{what} must be <= {maximum}")
    return value


def _require_iso_timestamp(value: Any, what: str) -> str:
    text = _require_str(value, what)
    if _ISO_TIMESTAMP.fullmatch(text) is None:
        raise WorkflowProtocolError(f"{what} must be an ISO-8601 UTC timestamp")
    return text


def _require_exit_code(value: Any, what: str, *, allow_null: bool = False) -> int | None:
    if allow_null and value is None:
        return None
    return _require_int(value, what, minimum=0, maximum=255)


def _require_nullable_signal(value: Any, what: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, what)


def require_absolute_path(value: Any, what: str) -> str:
    path = _require_str(value, what)
    candidate = Path(path)
    if not candidate.is_absolute() or path.startswith("./") or path.startswith("../"):
        raise WorkflowProtocolError(f"{what} must be an absolute path")
    return path


def require_sha256(value: Any, what: str) -> str:
    digest = _require_str(value, what)
    if _SHA256.fullmatch(digest) is None:
        raise WorkflowProtocolError(f"{what} must be a lowercase SHA-256 hex digest")
    return digest


def sha256_file_if_exists(path: str) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        raise WorkflowProtocolError(f"artifact path does not exist: {path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_status(value: Any) -> WorkflowStatus:
    name = _require_str(value, "workflowStatus")
    try:
        return WorkflowStatus(name)
    except ValueError as exc:
        raise WorkflowProtocolError(f"unknown workflow status {name!r}") from exc


def parse_artifact_ref(value: Any) -> ArtifactRef:
    data = _require_mapping(value, "artifact")
    kind = _require_str(data.get("kind"), "artifact.kind")
    schema = _require_str(data.get("schema"), "artifact.schema")
    return ArtifactRef(
        kind=kind,
        path=require_absolute_path(data.get("path"), "artifact.path"),
        sha256=require_sha256(data.get("sha256"), "artifact.sha256"),
        schema=schema,
        canonical=_require_bool(data.get("canonical"), "artifact.canonical"),
    )


def parse_manifest(value: Any) -> WorkflowManifest:
    data = _require_mapping(value, "manifest")
    schema = _require_str(data.get("schema"), "schema")
    if schema != WORKFLOW_SCHEMA:
        raise WorkflowProtocolError(f"unknown workflow schema {schema!r}")
    template_id = _require_str(data.get("templateId"), "templateId")
    template = get_template(template_id)
    baseline_raw = data.get("baseline")
    baseline = None
    if baseline_raw is not None:
        baseline_data = _require_mapping(baseline_raw, "baseline")
        head = _require_str(baseline_data.get("head"), "baseline.head")
        if _GIT_HEAD.fullmatch(head) is None:
            raise WorkflowProtocolError("baseline.head must be a 40- or 64-char git SHA")
        baseline = GitBaseline(
            repo_root=require_absolute_path(data.get("repoRoot"), "repoRoot"),
            branch=_require_str(baseline_data.get("branch"), "baseline.branch"),
            head=head,
            clean=True,
        )
    fingerprint = data.get("candidateFingerprint")
    if fingerprint is not None:
        fingerprint = require_sha256(fingerprint, "candidateFingerprint")
    stage_agents = data.get("stageAgents")
    if stage_agents is not None:
        validate_stage_agent_binding(stage_agents)
    status = parse_status(data.get("workflowStatus"))
    if status not in template.allowed_statuses:
        raise WorkflowProtocolError(
            f"workflow status {status.value} is not allowed for template {template_id}"
        )
    return WorkflowManifest(
        schema=schema,
        template_id=template_id,
        board=_require_str(data.get("board"), "board"),
        task_id=_require_str(data.get("taskId"), "taskId"),
        repo_root=require_absolute_path(data.get("repoRoot"), "repoRoot"),
        status=status,
        revision=_require_int(data.get("revision"), "revision", minimum=0),
        baseline=baseline,
        candidate_fingerprint=fingerprint,
        approved_plan=_optional_str(data.get("approvedPlan"), "approvedPlan"),
    )


def validate_stage_agent_binding(value: Any) -> dict[str, dict[str, str]]:
    """Validate a frozen per-Stage {adapter, model, thinking} manifest binding.

    Adapters are strictly allowlisted; model/thinking only need to be
    non-empty strings because a frozen binding must round-trip whatever the
    legacy ``agents[profile]`` config legitimately produced at freeze time.
    """
    if not isinstance(value, Mapping):
        raise WorkflowProtocolError("stageAgents must be a mapping of stage to agent selection")
    unknown = set(value) - set(STAGE_AGENT_STAGES)
    if unknown:
        raise WorkflowProtocolError(f"stageAgents has unknown stages {sorted(unknown)}")
    parsed: dict[str, dict[str, str]] = {}
    for stage, spec in value.items():
        if not isinstance(spec, Mapping):
            raise WorkflowProtocolError(f"stageAgents[{stage}] must be an object")
        adapter = spec.get("adapter")
        if adapter not in ALLOWED_ADAPTERS:
            raise WorkflowProtocolError(
                f"stageAgents[{stage}].adapter must be one of {sorted(ALLOWED_ADAPTERS)}"
            )
        model = spec.get("model")
        if not isinstance(model, str) or not model.strip():
            raise WorkflowProtocolError(f"stageAgents[{stage}].model must be a non-empty string")
        thinking = spec.get("thinking")
        if not isinstance(thinking, str) or not thinking.strip():
            raise WorkflowProtocolError(f"stageAgents[{stage}].thinking must be a non-empty string")
        parsed[str(stage)] = {
            "adapter": str(adapter),
            "model": model,
            "thinking": thinking,
        }
    return parsed


def parse_verification_document(value: Any, *, repo_root: str) -> dict[str, Any]:
    data = _require_mapping(value, "verification")
    extra = set(data) - {"schema", "checks"}
    if extra:
        raise WorkflowProtocolError(f"unknown verification fields {sorted(extra)}")
    schema = _require_str(data.get("schema"), "verification.schema")
    if schema != VERIFICATION_SCHEMA:
        raise WorkflowProtocolError(f"unknown verification schema {schema!r}")
    checks_raw = data.get("checks")
    if not isinstance(checks_raw, list) or not checks_raw:
        raise WorkflowProtocolError("verification.checks must be a non-empty array")
    root = Path(require_absolute_path(repo_root, "repo_root")).resolve()
    seen: set[str] = set()
    checks: list[dict[str, Any]] = []
    for index, raw in enumerate(checks_raw):
        check = _parse_verification_check(raw, index=index, repo_root=root)
        if check["id"] in seen:
            raise WorkflowProtocolError(f"duplicate verification check id {check['id']!r}")
        seen.add(check["id"])
        checks.append(check)
    return {"schema": VERIFICATION_SCHEMA, "checks": checks}


def _parse_verification_check(value: Any, *, index: int, repo_root: Path) -> dict[str, Any]:
    data = _require_mapping(value, f"checks[{index}]")
    extra = set(data) - set(VERIFICATION_CHECK_FIELDS)
    if extra:
        raise WorkflowProtocolError(f"unknown checks[{index}] fields {sorted(extra)}")
    check_id = _require_str(data.get("id"), f"checks[{index}].id")
    argv_raw = data.get("argv")
    if not isinstance(argv_raw, list) or not argv_raw or any(
        not isinstance(item, str) or not item for item in argv_raw
    ):
        raise WorkflowProtocolError(f"checks[{index}].argv must be a non-empty string array")
    cwd = _require_repo_relative_cwd(data.get("cwd"), f"checks[{index}].cwd", repo_root=repo_root)
    timeout = _require_int(data.get("timeoutSeconds"), f"checks[{index}].timeoutSeconds", minimum=1)
    exit_code = _require_int(data.get("expectedExitCode"), f"checks[{index}].expectedExitCode", minimum=0)
    if exit_code > 255:
        raise WorkflowProtocolError(f"checks[{index}].expectedExitCode must be 0..255")
    return {
        "id": check_id,
        "argv": list(argv_raw),
        "cwd": cwd,
        "timeoutSeconds": timeout,
        "expectedExitCode": exit_code,
    }


def _require_repo_relative_cwd(value: Any, what: str, *, repo_root: Path) -> str:
    cwd = _require_str(value, what)
    if Path(cwd).is_absolute() or cwd.startswith("/") or "\\" in cwd:
        raise WorkflowProtocolError(f"{what} must be repo-relative")
    if cwd != ".":
        parts = cwd.split("/")
        if any(part == "" or part == "." or part == ".." for part in parts):
            raise WorkflowProtocolError(f"{what} must be repo-relative")
        resolved = (repo_root / cwd).resolve()
        try:
            resolved.relative_to(repo_root)
        except ValueError as exc:
            raise WorkflowProtocolError(f"{what} escapes repo_root") from exc
    return cwd


def assert_allowed_transition(
    source: Any,
    target: Any,
    *,
    template_id: str | None = None,
) -> None:
    src = source if isinstance(source, WorkflowStatus) else parse_status(source)
    dst = target if isinstance(target, WorkflowStatus) else parse_status(target)
    template = get_template(template_id or WORKFLOW_TEMPLATE_ID)
    allowed = template.allowed_transitions.get(src, frozenset())
    if dst not in allowed:
        raise WorkflowProtocolError(f"illegal transition {src.value} -> {dst.value}")


def parse_job_expectation(value: Any, *, saved_session: str | None = None) -> JobExpectation:
    data = _require_mapping(value, "job expectation")
    stage = _require_str(data.get("stage"), "stage")
    if stage not in STAGE_OUTPUT:
        raise WorkflowProtocolError(f"unknown job stage {stage!r}")
    expected_kind, expected_schema = STAGE_OUTPUT[stage]
    output_kind = _require_str(data.get("outputKind"), "outputKind")
    output_schema = _require_str(data.get("outputSchema"), "outputSchema")
    if output_kind != expected_kind or output_schema != expected_schema:
        raise WorkflowProtocolError(
            f"stage {stage} requires output {expected_kind}/{expected_schema}"
        )
    session_id = data.get("sessionId")
    if session_id is not None:
        session_id = _require_str(session_id, "sessionId")
    if stage in REVIEWER_STAGES and session_id is not None:
        raise WorkflowProtocolError(f"{stage} reviewer jobs must use a fresh session")
    if saved_session is not None:
        if stage not in RESUME_STAGES:
            raise WorkflowProtocolError(f"{stage} cannot resume a saved session")
        if session_id != saved_session:
            raise WorkflowProtocolError("rework sessionId must exactly match the saved session")
    adapter = data.get("adapter", "pi")
    if adapter not in ALLOWED_ADAPTERS:
        raise WorkflowProtocolError(f"adapter must be one of {sorted(ALLOWED_ADAPTERS)}")
    return JobExpectation(
        job_id=_require_str(data.get("jobId"), "jobId"),
        task_id=_require_str(data.get("taskId"), "taskId"),
        stage=stage,
        idempotency_key=_require_str(data.get("idempotencyKey"), "idempotencyKey"),
        job_sha256=require_sha256(data.get("jobSha256"), "jobSha256"),
        session_id=session_id,
        output_kind=output_kind,
        output_schema=output_schema,
        adapter=str(adapter),
    )


def bind_result(expectation: JobExpectation, result: Any) -> None:
    data = _require_mapping(result, "result")
    schema = _require_str(data.get("schema"), "result.schema")
    if schema != RESULT_SCHEMA:
        raise WorkflowProtocolError(f"unknown result schema {schema!r}")
    _match(expectation.job_id, data.get("jobId"), "jobId")
    _match(expectation.task_id, data.get("taskId"), "taskId")
    _match(expectation.stage, data.get("stage"), "stage")
    _match(expectation.idempotency_key, data.get("idempotencyKey"), "idempotencyKey")
    _match(expectation.job_sha256, data.get("jobSha256"), "jobSha256")
    _match(expectation.adapter, data.get("adapter"), "adapter")
    actual_session = data.get("sessionId")
    if expectation.session_id is not None:
        if actual_session != expectation.session_id:
            raise WorkflowProtocolError(
                f"result sessionId {actual_session!r} does not match expectation {expectation.session_id!r}"
            )
    elif actual_session is not None:
        _require_str(actual_session, "sessionId")


def _match(expected: Any, actual: Any, field: str) -> None:
    if actual != expected:
        raise WorkflowProtocolError(
            f"result {field} {actual!r} does not match expectation {expected!r}"
        )


def validate_completed_result(
    expectation: JobExpectation,
    result: Any,
    *,
    job: Mapping[str, Any] | None = None,
    expected_job_sha256: str | None = None,
) -> None:
    if expected_job_sha256 is not None:
        if job is None:
            raise WorkflowProtocolError("authoritative job hash requires the Job document")
        bound = bind_authoritative_job_hash(job, expected_job_sha256)
        if expectation.job_sha256 != bound:
            raise WorkflowProtocolError(
                "completed Result expectation jobSha256 does not match the authoritative ledger hash"
            )
    bind_result(expectation, result)
    data = _require_mapping(result, "result")
    status = _require_str(data.get("status"), "status")
    if status != "completed":
        raise WorkflowProtocolError("completed validation requires status=completed")
    output = data.get("structuredOutput")
    output_data = _require_mapping(output, "structuredOutput")
    kind = _require_str(output_data.get("kind"), "structuredOutput.kind")
    if kind != expectation.output_kind:
        raise WorkflowProtocolError(
            f"structuredOutput.kind {kind!r} does not match stage {expectation.stage}"
        )
    payload = _require_mapping(output_data.get("payload"), "structuredOutput.payload")
    artifacts_raw = data.get("artifacts")
    if not isinstance(artifacts_raw, list):
        raise WorkflowProtocolError("result.artifacts must be a list")
    artifacts = tuple(parse_artifact_ref(item) for item in artifacts_raw)
    if not any(
        item.canonical
        and item.kind == expectation.output_kind
        and item.schema == ARTIFACT_SCHEMA
        for item in artifacts
    ):
        raise WorkflowProtocolError(
            f"completed {expectation.stage} requires a canonical {expectation.output_kind} artifact"
        )
    if job is not None:
        validate_canonical_artifact(expectation, result, job)
    if expectation.stage in VERIFICATION_STAGES:
        if job is None:
            raise WorkflowProtocolError("completed verification stages require the Job document")
        bind_result_checks(job.get("verification") or (), data.get("checks"))
    if kind in REVIEW_OUTPUT_KINDS:
        _reject_approved_blocking_findings(payload)
    if kind == "direct-implementation":
        _validate_direct_implementation_payload(payload)


_CHECK_EVIDENCE_STATUSES = frozenset({"passed", "failed", "timed_out", "unavailable"})


def bind_result_checks(job_verification: Any, result_checks: Any) -> None:
    if not isinstance(job_verification, Sequence) or isinstance(job_verification, (str, bytes)):
        raise WorkflowProtocolError("job.verification must be a list")
    if not job_verification:
        raise WorkflowProtocolError("verification jobs require a non-empty job.verification list")
    if not isinstance(result_checks, Sequence) or isinstance(result_checks, (str, bytes)):
        raise WorkflowProtocolError("result.checks must be a list")
    expected_ids: list[str] = []
    expected_by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(job_verification):
        item = _require_mapping(raw, f"job.verification[{index}]")
        check_id = _require_str(item.get("id"), f"job.verification[{index}].id")
        if check_id in expected_by_id:
            raise WorkflowProtocolError(f"duplicate job verification id {check_id!r}")
        expected_ids.append(check_id)
        expected_by_id[check_id] = item
    if len(result_checks) != len(expected_ids):
        raise WorkflowProtocolError("result.checks must contain exactly one entry per job verification id")
    seen: set[str] = set()
    actual_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(result_checks):
        parsed = _parse_result_check(raw, index=index)
        check_id = parsed["id"]
        if check_id in seen:
            raise WorkflowProtocolError(f"duplicate result check id {check_id!r}")
        seen.add(check_id)
        actual_by_id[check_id] = parsed
    missing = [check_id for check_id in expected_ids if check_id not in actual_by_id]
    extra = [check_id for check_id in seen if check_id not in expected_by_id]
    if missing or extra:
        raise WorkflowProtocolError("result.checks ids must exactly match job.verification ids")
    for check_id, expected in expected_by_id.items():
        actual = actual_by_id[check_id]
        if actual["argv"] != list(expected.get("argv") or []):
            raise WorkflowProtocolError(f"check {check_id!r} argv does not match the Job")
        if actual["cwd"] != expected.get("cwd"):
            raise WorkflowProtocolError(f"check {check_id!r} cwd does not match the Job")
        if actual["expectedExitCode"] != expected.get("expectedExitCode"):
            raise WorkflowProtocolError(f"check {check_id!r} expectedExitCode does not match the Job")
        _assert_check_status_coherence(actual)


def _parse_result_check(raw: Any, *, index: int) -> dict[str, Any]:
    item = _require_mapping(raw, f"result.checks[{index}]")
    missing = [key for key in RESULT_CHECK_FIELD_KEYS if key not in item]
    extra = [key for key in item if key not in RESULT_CHECK_FIELD_KEYS]
    if missing:
        raise WorkflowProtocolError(f"result.checks[{index}] missing fields {missing}")
    if extra:
        raise WorkflowProtocolError(f"result.checks[{index}] unknown fields {extra}")
    argv_raw = item.get("argv")
    if not isinstance(argv_raw, list) or not argv_raw or any(
        not isinstance(entry, str) or not entry for entry in argv_raw
    ):
        raise WorkflowProtocolError(f"result.checks[{index}].argv must be a non-empty string array")
    status = _require_str(item.get("status"), f"result.checks[{index}].status")
    if status not in _CHECK_EVIDENCE_STATUSES:
        raise WorkflowProtocolError(f"unknown check status {status!r}")
    return {
        "id": _require_str(item.get("id"), f"result.checks[{index}].id"),
        "status": status,
        "argv": list(argv_raw),
        "cwd": require_absolute_path(item.get("cwd"), f"result.checks[{index}].cwd"),
        "expectedExitCode": _require_exit_code(item.get("expectedExitCode"), f"result.checks[{index}].expectedExitCode"),
        "exitCode": _require_exit_code(
            item.get("exitCode"), f"result.checks[{index}].exitCode", allow_null=True
        ),
        "signal": _require_nullable_signal(item.get("signal"), f"result.checks[{index}].signal"),
        "startedAt": _require_iso_timestamp(item.get("startedAt"), f"result.checks[{index}].startedAt"),
        "finishedAt": _require_iso_timestamp(item.get("finishedAt"), f"result.checks[{index}].finishedAt"),
        "stdoutPath": require_absolute_path(item.get("stdoutPath"), f"result.checks[{index}].stdoutPath"),
        "stderrPath": require_absolute_path(item.get("stderrPath"), f"result.checks[{index}].stderrPath"),
    }


def _assert_check_status_coherence(actual: Mapping[str, Any]) -> None:
    check_id = actual["id"]
    status = actual["status"]
    if status == "passed":
        if actual["exitCode"] != actual["expectedExitCode"] or actual["signal"] is not None:
            raise WorkflowProtocolError(
                f"check {check_id!r} passed evidence requires exitCode==expectedExitCode and signal=null"
            )
    if status == "failed":
        if actual["exitCode"] == actual["expectedExitCode"] and actual["signal"] is None:
            raise WorkflowProtocolError(
                f"check {check_id!r} failed evidence must not claim a successful expected exit with null signal"
            )


def _input_identity(items: Any, what: str) -> list[tuple[str, str, str]]:
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise WorkflowProtocolError(f"{what} must be a list")
    identity: list[tuple[str, str, str]] = []
    for index, raw in enumerate(items):
        item = _require_mapping(raw, f"{what}[{index}]")
        identity.append(
            (
                _require_str(item.get("kind"), f"{what}[{index}].kind"),
                require_absolute_path(item.get("path"), f"{what}[{index}].path"),
                require_sha256(item.get("sha256"), f"{what}[{index}].sha256"),
            )
        )
    return identity


def validate_canonical_artifact(
    expectation: JobExpectation,
    result: Any,
    job: Mapping[str, Any],
) -> None:
    data = _require_mapping(result, "result")
    job_data = _require_mapping(job, "job")
    artifacts = tuple(parse_artifact_ref(item) for item in data.get("artifacts") or [])
    canonical = [
        item
        for item in artifacts
        if item.canonical and item.kind == expectation.output_kind and item.schema == ARTIFACT_SCHEMA
    ]
    if len(canonical) != 1:
        raise WorkflowProtocolError(
            f"completed {expectation.stage} requires exactly one canonical {expectation.output_kind} artifact"
        )
    ref = canonical[0]
    path = Path(ref.path)
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise WorkflowProtocolError(f"canonical artifact path does not exist: {ref.path}") from exc
    if not stat.S_ISREG(mode):
        raise WorkflowProtocolError(f"canonical artifact path is not a regular JSON file: {ref.path}")
    actual_digest = sha256_file_if_exists(ref.path)
    if actual_digest != ref.sha256:
        raise WorkflowProtocolError("canonical artifact SHA-256 does not match file contents")
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkflowProtocolError("canonical artifact is not valid JSON") from exc
    wrapper_data = _require_mapping(wrapper, "canonical artifact")
    if wrapper_data.get("schema") != ARTIFACT_SCHEMA:
        raise WorkflowProtocolError("canonical artifact schema must be coding-agent.artifact.v1")
    if wrapper_data.get("kind") != expectation.output_kind:
        raise WorkflowProtocolError("canonical artifact kind does not match the Job stage")
    payload = _require_mapping(wrapper_data.get("payload"), "canonical artifact.payload")
    payload_schema = _require_str(payload.get("schema"), "canonical artifact.payload.schema")
    if payload_schema != expectation.output_schema:
        raise WorkflowProtocolError("canonical artifact payload schema does not match the Job stage")
    identity = _require_mapping(wrapper_data.get("job"), "canonical artifact.job")
    job_sha = expectation.job_sha256
    expected_identity = {
        "jobId": job_data.get("jobId"),
        "idempotencyKey": job_data.get("idempotencyKey"),
        "taskId": job_data.get("taskId"),
        "stage": job_data.get("stage"),
        "attempt": job_data.get("attempt"),
        "jobSha256": job_sha,
    }
    for field, expected in expected_identity.items():
        if identity.get(field) != expected:
            raise WorkflowProtocolError(
                f"canonical artifact.job.{field} {identity.get(field)!r} does not match the Job"
            )
    if identity.get("jobSha256") != data.get("jobSha256") or identity.get("jobSha256") != expectation.job_sha256:
        raise WorkflowProtocolError("canonical artifact jobSha256 does not match the completed Result")
    if wrapper_data.get("sessionId") != data.get("sessionId"):
        raise WorkflowProtocolError("canonical artifact sessionId does not match the completed Result")
    if _input_identity(wrapper_data.get("inputs"), "canonical artifact.inputs") != _input_identity(
        job_data.get("inputs"), "job.inputs"
    ):
        raise WorkflowProtocolError("canonical artifact inputs do not match the Job")
    result_output = _require_mapping(data.get("structuredOutput"), "structuredOutput")
    result_payload = _require_mapping(result_output.get("payload"), "structuredOutput.payload")
    if payload != result_payload:
        raise WorkflowProtocolError("canonical artifact payload does not match result.structuredOutput.payload")
    art_workspace = _require_mapping(wrapper_data.get("workspace"), "canonical artifact.workspace")
    job_workspace = _require_mapping(job_data.get("workspace"), "job.workspace")
    if art_workspace.get("repoRoot") != job_workspace.get("repoRoot"):
        raise WorkflowProtocolError("canonical artifact workspace.repoRoot does not match the Job")
    if art_workspace.get("branch") != job_workspace.get("branch"):
        raise WorkflowProtocolError("canonical artifact workspace.branch does not match the Job")
    if art_workspace.get("head") != job_workspace.get("expectedHead"):
        raise WorkflowProtocolError("canonical artifact workspace.head does not match the Job")
    result_workspace = data.get("workspace")
    if isinstance(result_workspace, Mapping):
        if result_workspace.get("repoRoot") != job_workspace.get("repoRoot"):
            raise WorkflowProtocolError("result workspace.repoRoot does not match the Job")


def _validate_direct_implementation_payload(payload: Mapping[str, Any]) -> None:
    outcome = _require_str(payload.get("outcome"), "payload.outcome")
    if outcome not in {"completed", "blocked"}:
        raise WorkflowProtocolError(f"unknown direct-implementation outcome {outcome!r}")
    _require_str(payload.get("summary"), "payload.summary")
    residuals = payload.get("residualRisks")
    if residuals is None:
        residuals = []
    if not isinstance(residuals, list) or any(not isinstance(item, str) or not item for item in residuals):
        raise WorkflowProtocolError("direct-implementation residualRisks must be a string list")
    blockers = payload.get("blockingIssues")
    if blockers is None:
        blockers = []
    if not isinstance(blockers, list) or any(not isinstance(item, str) or not item for item in blockers):
        raise WorkflowProtocolError("direct-implementation blockingIssues must be a string list")
    if outcome == "completed" and blockers:
        raise WorkflowProtocolError("completed direct implementation requires blockingIssues=[]")
    if outcome == "blocked" and not blockers:
        raise WorkflowProtocolError("blocked direct implementation requires a non-empty blockingIssues list")


def _reject_approved_blocking_findings(payload: Mapping[str, Any]) -> None:
    verdict = _require_str(payload.get("verdict"), "review.verdict")
    findings_raw = payload.get("findings")
    if findings_raw is None:
        findings_raw = []
    if not isinstance(findings_raw, list):
        raise WorkflowProtocolError("review findings must be a list")
    if verdict != "approved":
        return
    for item in findings_raw:
        finding = _require_mapping(item, "review finding")
        severity = _require_str(finding.get("severity"), "finding.severity")
        if severity == "blocking":
            raise WorkflowProtocolError("approved review cannot contain a blocking finding")


def parse_acceptance(value: Any, *, expected_fingerprint: str) -> AcceptanceSubmission:
    data = _require_mapping(value, "acceptance")
    verdict = _require_str(data.get("verdict"), "verdict")
    if verdict not in _ACCEPTANCE_VERDICTS:
        raise WorkflowProtocolError(f"unknown acceptance verdict {verdict!r}")
    summary = _require_str(data.get("summary"), "summary")
    scenarios_raw = data.get("scenarios")
    if not isinstance(scenarios_raw, list):
        raise WorkflowProtocolError("acceptance.scenarios must be a list")
    scenarios = tuple(_parse_scenario(item) for item in scenarios_raw)
    findings_raw = data.get("findings") or []
    if not isinstance(findings_raw, list):
        raise WorkflowProtocolError("acceptance.findings must be a list")
    findings = tuple(_parse_finding(item) for item in findings_raw)
    question = _optional_str(data.get("question"), "question")
    fingerprint = require_sha256(data.get("candidateFingerprint"), "candidateFingerprint")
    expected = require_sha256(expected_fingerprint, "expected candidate fingerprint")
    if fingerprint != expected:
        raise WorkflowProtocolError("acceptance candidate fingerprint does not match the current candidate")
    blocking = tuple(item for item in findings if item.severity == "blocking")
    if verdict == "passed":
        if not scenarios:
            raise WorkflowProtocolError("passed acceptance requires at least one scenario")
        if any(item.status != "passed" for item in scenarios):
            raise WorkflowProtocolError("passed acceptance requires every scenario to pass")
        if blocking:
            raise WorkflowProtocolError("passed acceptance cannot include a blocking finding")
    elif verdict == "failed":
        if all(item.status != "failed" for item in scenarios) and not blocking:
            raise WorkflowProtocolError(
                "failed acceptance requires a failed scenario or a blocking finding"
            )
    elif verdict == "needs_human":
        if question is None or not question.strip():
            raise WorkflowProtocolError("needs_human acceptance requires an explicit question")
    elif verdict == "blocked":
        if not summary.strip():
            raise WorkflowProtocolError("blocked acceptance requires an explicit external blocker")
    return AcceptanceSubmission(
        verdict=verdict,
        summary=summary,
        scenarios=scenarios,
        findings=findings,
        question=question,
        candidate_fingerprint=fingerprint,
    )


def _parse_scenario(value: Any) -> AcceptanceScenario:
    data = _require_mapping(value, "scenario")
    status = _require_str(data.get("status"), "scenario.status")
    if status not in _SCENARIO_STATUSES:
        raise WorkflowProtocolError(f"unknown scenario status {status!r}")
    evidence_raw = data.get("evidence") or []
    if not isinstance(evidence_raw, list):
        raise WorkflowProtocolError("scenario.evidence must be a list")
    evidence = tuple(require_absolute_path(item, "scenario.evidence") for item in evidence_raw)
    return AcceptanceScenario(
        name=_require_str(data.get("name"), "scenario.name"),
        status=status,
        evidence=evidence,
    )


def _parse_finding(value: Any) -> AcceptanceFinding:
    data = _require_mapping(value, "finding")
    severity = _require_str(data.get("severity"), "finding.severity")
    if severity not in _FINDING_SEVERITIES:
        raise WorkflowProtocolError(f"unknown finding severity {severity!r}")
    return AcceptanceFinding(
        severity=severity,
        problem=_require_str(data.get("problem"), "finding.problem"),
        details=dict(data),
    )


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def digest_canonical(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def harness_canonical_json(payload: Any) -> str:
    """Match coding-agent-harness `canonicalJson`: pretty-printed JSON plus newline."""
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def job_document_sha256(job: Mapping[str, Any]) -> str:
    return hashlib.sha256(harness_canonical_json(job).encode("utf-8")).hexdigest()


def bind_authoritative_job_hash(job: Mapping[str, Any], expected_job_sha256: str | None) -> str:
    actual = job_document_sha256(job)
    if expected_job_sha256 is None:
        return actual
    expected = require_sha256(expected_job_sha256, "expected_job_sha256")
    if actual != expected:
        raise WorkflowProtocolError(
            f"job.json job_sha256 {actual} does not match authoritative ledger job_sha256 {expected}"
        )
    return expected


def result_digest(result: Mapping[str, Any]) -> str:
    return digest_canonical(result)


def review_verdict_from_result(result: Mapping[str, Any]) -> str | None:
    output = result.get("structuredOutput")
    if not isinstance(output, Mapping):
        return None
    payload = output.get("payload")
    if not isinstance(payload, Mapping):
        return None
    verdict = payload.get("verdict")
    if verdict is None:
        return None
    return _require_str(verdict, "review.verdict")


def checks_passed(result_or_checks: Any) -> bool:
    if isinstance(result_or_checks, Mapping) and "checks" in result_or_checks:
        checks = result_or_checks.get("checks")
    else:
        checks = result_or_checks
    if checks is None:
        checks = []
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)):
        raise WorkflowProtocolError("result.checks must be a list")
    return all(
        isinstance(item, Mapping) and item.get("status") == "passed" for item in checks
    ) and bool(checks)


def expectation_from_job(job: Mapping[str, Any], *, job_sha256: str | None = None) -> JobExpectation:
    data = _require_mapping(job, "job")
    stage = _require_str(data.get("stage"), "stage")
    if stage not in STAGE_OUTPUT:
        raise WorkflowProtocolError(f"unknown job stage {stage!r}")
    kind, schema = STAGE_OUTPUT[stage]
    agent = _require_mapping(data.get("agent"), "agent")
    digest = job_sha256 or job_document_sha256(data)
    return parse_job_expectation(
        {
            "jobId": data.get("jobId"),
            "taskId": data.get("taskId"),
            "stage": stage,
            "idempotencyKey": data.get("idempotencyKey"),
            "jobSha256": digest,
            "sessionId": agent.get("sessionId"),
            "outputKind": kind,
            "outputSchema": schema,
            "adapter": agent.get("adapter", "pi"),
        }
    )


def validate_job_document(job: Mapping[str, Any]) -> Mapping[str, Any]:
    data = _require_mapping(job, "job")
    schema = _require_str(data.get("schema"), "schema")
    if schema != JOB_SCHEMA:
        raise WorkflowProtocolError(f"unknown job schema {schema!r}")
    stage = _require_str(data.get("stage"), "stage")
    if stage not in STAGE_OUTPUT:
        raise WorkflowProtocolError(f"unknown job stage {stage!r}")
    _require_str(data.get("jobId"), "jobId")
    _require_str(data.get("idempotencyKey"), "idempotencyKey")
    _require_str(data.get("taskId"), "taskId")
    _require_int(data.get("attempt"), "attempt", minimum=1)
    workspace = _require_mapping(data.get("workspace"), "workspace")
    require_absolute_path(workspace.get("repoRoot"), "workspace.repoRoot")
    _require_str(workspace.get("branch"), "workspace.branch")
    head = _require_str(workspace.get("expectedHead"), "workspace.expectedHead")
    if _GIT_HEAD.fullmatch(head) is None:
        raise WorkflowProtocolError("workspace.expectedHead must be a 40- or 64-char git SHA")
    _require_bool(workspace.get("requireCleanAtStart"), "workspace.requireCleanAtStart")
    agent = _require_mapping(data.get("agent"), "agent")
    adapter = _require_str(agent.get("adapter"), "agent.adapter")
    if adapter not in ALLOWED_ADAPTERS:
        raise WorkflowProtocolError(
            f"agent.adapter must be one of {sorted(ALLOWED_ADAPTERS)}, got {adapter!r}"
        )
    profile = _require_str(agent.get("profile"), "agent.profile")
    if profile != STAGE_PROFILES[stage]:
        raise WorkflowProtocolError(f"stage {stage} requires profile {STAGE_PROFILES[stage]}")
    _require_str(agent.get("model"), "agent.model")
    _require_str(agent.get("thinking"), "agent.thinking")
    session_id = agent.get("sessionId")
    if session_id is not None:
        session_id = _require_str(session_id, "agent.sessionId")
    if stage in REVIEWER_STAGES and session_id is not None:
        raise WorkflowProtocolError(f"{stage} reviewer jobs must use a fresh session")
    permissions = _require_mapping(data.get("permissions"), "permissions")
    mode = _require_str(permissions.get("mode"), "permissions.mode")
    if mode != STAGE_PERMISSIONS[stage]:
        raise WorkflowProtocolError(f"stage {stage} requires permissions.mode {STAGE_PERMISSIONS[stage]}")
    expected = _require_mapping(data.get("expectedOutput"), "expectedOutput")
    kind, schema_name = STAGE_OUTPUT[stage]
    if expected.get("kind") != kind or expected.get("schema") != schema_name:
        raise WorkflowProtocolError(f"stage {stage} requires output {kind}/{schema_name}")
    inputs = data.get("inputs")
    if not isinstance(inputs, list):
        raise WorkflowProtocolError("job.inputs must be a list")
    required = STAGE_INPUT_KINDS[stage]
    kinds = tuple(item.get("kind") if isinstance(item, Mapping) else None for item in inputs)
    if kinds != required:
        raise WorkflowProtocolError(f"stage {stage} requires inputs {required}")
    for index, item in enumerate(inputs):
        entry = _require_mapping(item, f"inputs[{index}]")
        require_absolute_path(entry.get("path"), f"inputs[{index}].path")
        require_sha256(entry.get("sha256"), f"inputs[{index}].sha256")
    verification = data.get("verification")
    if not isinstance(verification, list):
        raise WorkflowProtocolError("job.verification must be a list")
    if verification and stage not in VERIFICATION_STAGES:
        raise WorkflowProtocolError("verification is only allowed on implement and direct_implement jobs")
    limits = _require_mapping(data.get("limits"), "limits")
    if "timeoutSeconds" not in limits:
        raise WorkflowProtocolError("limits.timeoutSeconds is required")
    timeout = limits.get("timeoutSeconds")
    if timeout is not None:
        _require_int(timeout, "limits.timeoutSeconds", minimum=1)
    return data


def is_transport_failure(status: Any) -> bool:
    return status in TRANSPORT_FAILURE_STATUSES
