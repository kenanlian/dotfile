"""External workflow protocol types. Stdlib only."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


WORKFLOW_TEMPLATE_ID = "autonomous-development.v1"
WORKFLOW_SCHEMA = "autonomous-development.workflow.v1"
JOB_SCHEMA = "coding-agent.job.v1"
RESULT_SCHEMA = "coding-agent.result.v1"
ARTIFACT_SCHEMA = "coding-agent.artifact.v1"
VERIFICATION_SCHEMA = "autodev.verification.v1"
VERIFICATION_CHECK_FIELDS = ("id", "argv", "cwd", "timeoutSeconds", "expectedExitCode")
RESULT_CHECK_FIELD_KEYS = (
    "id",
    "status",
    "argv",
    "cwd",
    "expectedExitCode",
    "exitCode",
    "signal",
    "startedAt",
    "finishedAt",
    "stdoutPath",
    "stderrPath",
)

SHA256_PATTERN = r"^[a-f0-9]{64}$"
GIT_HEAD_PATTERN = r"^[a-f0-9]{40}$|^[a-f0-9]{64}$"
ISO_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"

STAGE_OUTPUT = {
    "plan": ("plan", "plan.v1"),
    "plan_review": ("plan-review", "plan-review.v1"),
    "implement": ("implementation", "implementation.v1"),
    "execute_review": ("execute-review", "execute-review.v1"),
    "direct_implement": ("direct-implementation", "direct-implementation.v1"),
}
REVIEWER_STAGES = frozenset({"plan_review", "execute_review"})
RESUME_STAGES = frozenset({"plan", "implement", "direct_implement"})
REVIEW_OUTPUT_KINDS = frozenset({"plan-review", "execute-review"})
TRANSPORT_FAILURE_STATUSES = frozenset({"failed", "timed_out", "aborted", "unavailable"})
TERMINAL_JOB_STATUSES = frozenset({"completed", *TRANSPORT_FAILURE_STATUSES})
STAGE_PROFILES = {
    "plan": "planner",
    "plan_review": "plan-reviewer",
    "implement": "implementer",
    "execute_review": "execute-reviewer",
    "direct_implement": "implementer",
}
STAGE_PERMISSIONS = {
    "plan": "read-only",
    "plan_review": "read-only",
    "implement": "write",
    "execute_review": "read-only",
    "direct_implement": "write",
}
STAGE_INPUT_KINDS = {
    "plan": ("requirement",),
    "plan_review": ("requirement", "plan"),
    "implement": ("plan",),
    "execute_review": ("requirement", "plan", "implementation"),
    "direct_implement": ("requirement",),
}
VERIFICATION_STAGES = frozenset({"implement", "direct_implement"})


class WorkflowStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    PLAN_REVIEWING = "plan_reviewing"
    PLAN_REWORK = "plan_rework"
    IMPLEMENTING = "implementing"
    VERIFYING = "verifying"
    REVIEW_REQUESTED = "review_requested"
    IMPLEMENT_REWORK = "implement_rework"
    CODE_REVIEWING = "code_reviewing"
    PRODUCT_ACCEPTANCE = "product_acceptance"
    BLOCKED = "blocked"
    COMPLETED = "completed"


ALLOWED_TRANSITIONS: Mapping[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.QUEUED: frozenset({WorkflowStatus.PLANNING}),
    WorkflowStatus.PLANNING: frozenset({WorkflowStatus.PLAN_REVIEWING}),
    WorkflowStatus.PLAN_REVIEWING: frozenset(
        {WorkflowStatus.PLAN_REWORK, WorkflowStatus.BLOCKED, WorkflowStatus.IMPLEMENTING}
    ),
    WorkflowStatus.PLAN_REWORK: frozenset({WorkflowStatus.PLANNING}),
    WorkflowStatus.IMPLEMENTING: frozenset({WorkflowStatus.VERIFYING}),
    WorkflowStatus.VERIFYING: frozenset(
        {WorkflowStatus.IMPLEMENT_REWORK, WorkflowStatus.REVIEW_REQUESTED}
    ),
    WorkflowStatus.REVIEW_REQUESTED: frozenset({WorkflowStatus.CODE_REVIEWING}),
    WorkflowStatus.IMPLEMENT_REWORK: frozenset({WorkflowStatus.IMPLEMENTING}),
    WorkflowStatus.CODE_REVIEWING: frozenset(
        {WorkflowStatus.IMPLEMENT_REWORK, WorkflowStatus.BLOCKED, WorkflowStatus.PRODUCT_ACCEPTANCE}
    ),
    WorkflowStatus.PRODUCT_ACCEPTANCE: frozenset(
        {WorkflowStatus.IMPLEMENT_REWORK, WorkflowStatus.BLOCKED, WorkflowStatus.COMPLETED}
    ),
    WorkflowStatus.BLOCKED: frozenset(),
    WorkflowStatus.COMPLETED: frozenset(),
}


class WorkflowProtocolError(ValueError):
    """Unknown or inconsistent workflow/job/result/acceptance payload."""


class WorkflowConflict(RuntimeError):
    """Identity or CAS conflict against an existing workflow record."""


LEASE_RELEASE_REASONS = frozenset({"completed", "archived", "abandon"})
TERMINAL_WORKFLOW_STATUSES = frozenset({WorkflowStatus.COMPLETED})


@dataclass(frozen=True)
class GitBaseline:
    repo_root: str
    branch: str
    head: str
    clean: bool


@dataclass(frozen=True)
class CandidateFingerprint:
    branch: str
    head: str
    porcelain_sha256: str
    diff_sha256: str
    file_hashes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ArtifactRef:
    kind: str
    path: str
    sha256: str
    schema: str
    canonical: bool


@dataclass(frozen=True)
class JobExpectation:
    job_id: str
    task_id: str
    stage: str
    idempotency_key: str
    job_sha256: str
    session_id: str | None
    output_kind: str
    output_schema: str


@dataclass(frozen=True)
class WorkflowManifest:
    schema: str
    template_id: str
    board: str
    task_id: str
    repo_root: str
    status: WorkflowStatus
    revision: int
    baseline: GitBaseline | None
    candidate_fingerprint: str | None
    approved_plan: str | None


@dataclass(frozen=True)
class AcceptanceScenario:
    name: str
    status: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class AcceptanceFinding:
    severity: str
    problem: str
    details: Mapping[str, Any]


@dataclass(frozen=True)
class AcceptanceSubmission:
    verdict: str
    summary: str
    scenarios: tuple[AcceptanceScenario, ...]
    findings: tuple[AcceptanceFinding, ...]
    question: str | None
    candidate_fingerprint: str | None


@dataclass(frozen=True)
class PluginConfig:
    profile: str
    state_root: str
    harness_command: tuple[str, ...]
    main_branch: str
    poll_interval_seconds: int
    advance_wait_seconds: int
