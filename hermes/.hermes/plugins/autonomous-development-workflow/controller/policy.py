"""Table-driven workflow policy. Pure functions; no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

from .protocol import checks_passed
from .types import (
    ALLOWED_TRANSITIONS,
    TERMINAL_JOB_STATUSES,
    TRANSPORT_FAILURE_STATUSES,
    WorkflowConflict,
    WorkflowStatus,
)

MAX_PLAN_REWORK = 2
MAX_IMPLEMENT_REWORK = 2
MAX_STAGE_TRANSPORT_FAILURES = 2

ActionKind = Literal[
    "create_job",
    "observe_job",
    "consume_job",
    "apply_lifecycle",
    "await_acceptance",
    "block",
    "noop",
]


@dataclass(frozen=True)
class WorkflowAction:
    kind: ActionKind
    stage: str | None = None
    target_status: WorkflowStatus | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ActiveJobView:
    job_id: str
    stage: str
    status: str
    result: Mapping[str, Any] | None = None
    consumed: bool = False
    result_sha256: str | None = None
    business_attempt: int = 1
    transport_retry: int = 0


@dataclass(frozen=True)
class PolicySnapshot:
    status: WorkflowStatus
    plan_rework_count: int = 0
    implement_rework_count: int = 0
    run_failure_counts: Mapping[str, int] = field(default_factory=dict)
    active_job: ActiveJobView | None = None
    last_consumed_job_id: str | None = None
    last_consumed_result_sha256: str | None = None
    pending_lifecycle: Mapping[str, Any] | None = None
    planner_session_id: str | None = None
    implementer_session_id: str | None = None
    resume_status: str | None = None
    implement_checks: tuple[Mapping[str, Any], ...] | None = None
    review_verdict: str | None = None
    kanban_status: str | None = None


def snapshot_from_manifest(
    manifest: Mapping[str, Any],
    *,
    active_job: ActiveJobView | None = None,
    implement_checks: tuple[Mapping[str, Any], ...] | None = None,
    review_verdict: str | None = None,
    last_consumed_result_sha256: str | None = None,
    kanban_status: str | None = None,
) -> PolicySnapshot:
    status = manifest.get("workflowStatus")
    parsed = status if isinstance(status, WorkflowStatus) else WorkflowStatus(str(status))
    failures = manifest.get("runFailureCounts") or {}
    if not isinstance(failures, Mapping):
        failures = {}
    return PolicySnapshot(
        status=parsed,
        plan_rework_count=int(manifest.get("planReworkCount") or 0),
        implement_rework_count=int(manifest.get("implementReworkCount") or 0),
        run_failure_counts={str(key): int(value) for key, value in failures.items()},
        active_job=active_job,
        last_consumed_job_id=manifest.get("lastConsumedJobId"),
        last_consumed_result_sha256=last_consumed_result_sha256,
        pending_lifecycle=manifest.get("pendingLifecycle"),
        planner_session_id=manifest.get("plannerSessionId"),
        implementer_session_id=manifest.get("implementerSessionId"),
        resume_status=manifest.get("resumeStatus"),
        implement_checks=implement_checks,
        review_verdict=review_verdict,
        kanban_status=kanban_status,
    )


def next_allowed_transitions(status: WorkflowStatus) -> frozenset[WorkflowStatus]:
    return ALLOWED_TRANSITIONS.get(status, frozenset())


def next_action(snapshot: PolicySnapshot) -> WorkflowAction:
    if snapshot.pending_lifecycle:
        return WorkflowAction(
            kind="apply_lifecycle",
            target_status=snapshot.status,
            reason="pending_lifecycle",
        )

    if snapshot.status is WorkflowStatus.BLOCKED:
        return _action_for_blocked(snapshot)

    job = snapshot.active_job
    if job is not None and not job.consumed:
        if job.status in TERMINAL_JOB_STATUSES:
            return WorkflowAction(kind="consume_job", stage=job.stage)
        return WorkflowAction(kind="observe_job", stage=job.stage)

    if job is not None and job.consumed:
        if (
            snapshot.last_consumed_job_id == job.job_id
            and snapshot.last_consumed_result_sha256
            and job.result_sha256
            and snapshot.last_consumed_result_sha256 != job.result_sha256
        ):
            raise WorkflowConflict("different Result bound to the same Job")
        if job.status in TRANSPORT_FAILURE_STATUSES:
            failures = int(snapshot.run_failure_counts.get(job.stage, 0))
            if failures >= MAX_STAGE_TRANSPORT_FAILURES:
                return WorkflowAction(
                    kind="block",
                    target_status=WorkflowStatus.BLOCKED,
                    reason="transport_failure_limit",
                )
            return WorkflowAction(
                kind="create_job",
                stage=job.stage,
                target_status=snapshot.status,
                reason="transport_retry",
            )

    return _action_for_status(snapshot)


def _action_for_status(snapshot: PolicySnapshot) -> WorkflowAction:
    status = snapshot.status
    verdict = snapshot.review_verdict

    if status is WorkflowStatus.QUEUED:
        return WorkflowAction(
            kind="create_job", stage="plan", target_status=WorkflowStatus.PLANNING
        )
    if status is WorkflowStatus.PLANNING:
        return WorkflowAction(kind="create_job", stage="plan", target_status=WorkflowStatus.PLANNING)
    if status is WorkflowStatus.PLAN_REWORK:
        return WorkflowAction(
            kind="create_job",
            stage="plan",
            target_status=WorkflowStatus.PLANNING,
            reason="plan_rework",
        )
    if status is WorkflowStatus.PLAN_REVIEWING:
        if verdict == "blocked":
            return WorkflowAction(
                kind="block", target_status=WorkflowStatus.BLOCKED, reason="review_blocked"
            )
        if verdict == "request_changes":
            if snapshot.plan_rework_count >= MAX_PLAN_REWORK:
                return WorkflowAction(
                    kind="block",
                    target_status=WorkflowStatus.BLOCKED,
                    reason="plan_rework_limit",
                )
            return WorkflowAction(
                kind="create_job",
                stage="plan",
                target_status=WorkflowStatus.PLANNING,
                reason="plan_rework",
            )
        if verdict == "approved":
            return WorkflowAction(
                kind="create_job",
                stage="implement",
                target_status=WorkflowStatus.IMPLEMENTING,
            )
        return WorkflowAction(
            kind="create_job", stage="plan_review", target_status=WorkflowStatus.PLAN_REVIEWING
        )
    if status is WorkflowStatus.IMPLEMENTING:
        return WorkflowAction(
            kind="create_job", stage="implement", target_status=WorkflowStatus.IMPLEMENTING
        )
    if status is WorkflowStatus.IMPLEMENT_REWORK:
        return WorkflowAction(
            kind="create_job",
            stage="implement",
            target_status=WorkflowStatus.IMPLEMENTING,
            reason="implement_rework",
        )
    if status is WorkflowStatus.VERIFYING:
        passed = checks_passed(snapshot.implement_checks or ())
        if passed:
            return WorkflowAction(
                kind="apply_lifecycle",
                target_status=WorkflowStatus.REVIEW_REQUESTED,
            )
        return _implement_rework_or_block(snapshot, kind="create_job")
    if status is WorkflowStatus.REVIEW_REQUESTED:
        return WorkflowAction(kind="noop")
    if status is WorkflowStatus.CODE_REVIEWING:
        if verdict == "blocked":
            return WorkflowAction(
                kind="block", target_status=WorkflowStatus.BLOCKED, reason="review_blocked"
            )
        if verdict == "request_changes":
            return _implement_rework_or_block(snapshot, kind="apply_lifecycle")
        if verdict == "approved":
            return WorkflowAction(
                kind="apply_lifecycle",
                target_status=WorkflowStatus.PRODUCT_ACCEPTANCE,
            )
        return WorkflowAction(
            kind="create_job",
            stage="execute_review",
            target_status=WorkflowStatus.CODE_REVIEWING,
        )
    if status is WorkflowStatus.PRODUCT_ACCEPTANCE:
        if verdict in {"failed", "request_changes"}:
            return _implement_rework_or_block(snapshot, kind="apply_lifecycle")
        if verdict == "blocked":
            return WorkflowAction(
                kind="block", target_status=WorkflowStatus.BLOCKED, reason="acceptance_blocked"
            )
        return WorkflowAction(kind="await_acceptance")
    if status is WorkflowStatus.COMPLETED:
        return WorkflowAction(kind="noop")
    return WorkflowAction(kind="noop")


def _kanban_has_left_blocked(kanban_status: str | None) -> bool:
    return bool(kanban_status) and kanban_status != WorkflowStatus.BLOCKED.value


def _resume_workflow_status(raw: str | None) -> WorkflowStatus | None:
    if not raw:
        return None
    try:
        status = raw if isinstance(raw, WorkflowStatus) else WorkflowStatus(str(raw))
    except ValueError:
        return None
    if status in {WorkflowStatus.BLOCKED, WorkflowStatus.COMPLETED}:
        return None
    return status


def _action_for_blocked(snapshot: PolicySnapshot) -> WorkflowAction:
    if not _kanban_has_left_blocked(snapshot.kanban_status):
        return WorkflowAction(kind="noop")
    resumed = _resume_workflow_status(snapshot.resume_status)
    if resumed is not None:
        return next_action(replace(snapshot, status=resumed, resume_status=None))
    job = snapshot.active_job
    if job is not None and job.status == "completed":
        return WorkflowAction(kind="consume_job", stage=job.stage)
    return WorkflowAction(kind="noop")


def _implement_rework_or_block(snapshot: PolicySnapshot, *, kind: ActionKind) -> WorkflowAction:
    if snapshot.implement_rework_count >= MAX_IMPLEMENT_REWORK:
        return WorkflowAction(
            kind="block",
            target_status=WorkflowStatus.BLOCKED,
            reason="implement_rework_limit",
        )
    if kind == "create_job":
        return WorkflowAction(
            kind="create_job",
            stage="implement",
            target_status=WorkflowStatus.IMPLEMENTING,
            reason="implement_rework",
        )
    return WorkflowAction(
        kind="apply_lifecycle",
        target_status=WorkflowStatus.IMPLEMENT_REWORK,
        reason="implement_rework",
    )
