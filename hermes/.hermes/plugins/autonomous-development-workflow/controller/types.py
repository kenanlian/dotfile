"""External workflow protocol types. Stdlib only."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


WORKFLOW_TEMPLATE_ID = "autonomous-development.v1"
WORKFLOW_SCHEMA = "autonomous-development.workflow.v1"
JOB_SCHEMA = "coding-agent.job.v1"
RESULT_SCHEMA = "coding-agent.result.v1"

SHA256_PATTERN = r"^[a-f0-9]{64}$"
GIT_HEAD_PATTERN = r"^[a-f0-9]{40}$|^[a-f0-9]{64}$"

STAGE_OUTPUT = {
    "plan": ("plan", "plan.v1"),
    "plan_review": ("plan-review", "plan-review.v1"),
    "implement": ("implementation", "implementation.v1"),
    "execute_review": ("execute-review", "execute-review.v1"),
}
REVIEWER_STAGES = frozenset({"plan_review", "execute_review"})
RESUME_STAGES = frozenset({"plan", "implement"})
REVIEW_OUTPUT_KINDS = frozenset({"plan-review", "execute-review"})


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
    branch: str
    head: str


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
