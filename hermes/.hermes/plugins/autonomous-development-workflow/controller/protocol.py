"""Pure validators for Workflow, Job, Result, Artifact, and Acceptance payloads."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .types import (
    ALLOWED_TRANSITIONS,
    GIT_HEAD_PATTERN,
    JOB_SCHEMA,
    RESULT_SCHEMA,
    REVIEW_OUTPUT_KINDS,
    REVIEWER_STAGES,
    RESUME_STAGES,
    SHA256_PATTERN,
    STAGE_INPUT_KINDS,
    STAGE_OUTPUT,
    STAGE_PERMISSIONS,
    STAGE_PROFILES,
    TRANSPORT_FAILURE_STATUSES,
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


def _require_int(value: Any, what: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkflowProtocolError(f"{what} must be an integer")
    if minimum is not None and value < minimum:
        raise WorkflowProtocolError(f"{what} must be >= {minimum}")
    return value


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
    if template_id != WORKFLOW_TEMPLATE_ID:
        raise WorkflowProtocolError(f"unknown workflow template {template_id!r}")
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
    return WorkflowManifest(
        schema=schema,
        template_id=template_id,
        board=_require_str(data.get("board"), "board"),
        task_id=_require_str(data.get("taskId"), "taskId"),
        repo_root=require_absolute_path(data.get("repoRoot"), "repoRoot"),
        status=parse_status(data.get("workflowStatus")),
        revision=_require_int(data.get("revision"), "revision", minimum=0),
        baseline=baseline,
        candidate_fingerprint=fingerprint,
        approved_plan=_optional_str(data.get("approvedPlan"), "approvedPlan"),
    )


def assert_allowed_transition(source: Any, target: Any) -> None:
    src = source if isinstance(source, WorkflowStatus) else parse_status(source)
    dst = target if isinstance(target, WorkflowStatus) else parse_status(target)
    allowed = ALLOWED_TRANSITIONS.get(src, frozenset())
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
    return JobExpectation(
        job_id=_require_str(data.get("jobId"), "jobId"),
        task_id=_require_str(data.get("taskId"), "taskId"),
        stage=stage,
        idempotency_key=_require_str(data.get("idempotencyKey"), "idempotencyKey"),
        job_sha256=require_sha256(data.get("jobSha256"), "jobSha256"),
        session_id=session_id,
        output_kind=output_kind,
        output_schema=output_schema,
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


def validate_completed_result(expectation: JobExpectation, result: Any) -> None:
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
        item.canonical and item.kind == expectation.output_kind and item.schema == expectation.output_schema
        for item in artifacts
    ):
        raise WorkflowProtocolError(
            f"completed {expectation.stage} requires a canonical {expectation.output_kind} artifact"
        )
    if kind in REVIEW_OUTPUT_KINDS:
        _reject_approved_blocking_findings(payload)


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
    elif verdict == "needs_human":
        if question is None or not question.strip():
            raise WorkflowProtocolError("needs_human acceptance requires an explicit question")
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
    return all(isinstance(item, Mapping) and item.get("status") == "passed" for item in checks)


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
    if agent.get("adapter") != "pi":
        raise WorkflowProtocolError("agent.adapter must be pi")
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
    if verification and stage != "implement":
        raise WorkflowProtocolError("verification is only allowed on implement jobs")
    limits = _require_mapping(data.get("limits"), "limits")
    if "timeoutSeconds" not in limits:
        raise WorkflowProtocolError("limits.timeoutSeconds is required")
    timeout = limits.get("timeoutSeconds")
    if timeout is not None:
        _require_int(timeout, "limits.timeoutSeconds", minimum=1)
    return data


def is_transport_failure(status: Any) -> bool:
    return status in TRANSPORT_FAILURE_STATUSES
