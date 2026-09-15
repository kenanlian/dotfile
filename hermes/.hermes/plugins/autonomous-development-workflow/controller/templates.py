"""Allowlisted, versioned workflow templates. No DAG DSL or feature switches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .types import (
    ALLOWED_TRANSITIONS,
    WORKFLOW_TEMPLATE_ID,
    WorkflowProtocolError,
    WorkflowStatus,
)

FULL_TEMPLATE_ID = WORKFLOW_TEMPLATE_ID
DIRECT_TEMPLATE_ID = "direct-implementation.v1"

_FULL_LANES: Mapping[str, frozenset[str]] = {
    "queued": frozenset({"ready", "todo"}),
    "planning": frozenset({"running"}),
    "plan_reviewing": frozenset({"running"}),
    "plan_rework": frozenset({"running", "todo"}),
    "implementing": frozenset({"running"}),
    "verifying": frozenset({"running"}),
    "review_requested": frozenset({"review"}),
    "implement_rework": frozenset({"todo", "running"}),
    "code_reviewing": frozenset({"running"}),
    "product_acceptance": frozenset({"running"}),
    "blocked": frozenset({"blocked", "todo"}),
    "completed": frozenset({"done"}),
}

_DIRECT_LANES: Mapping[str, frozenset[str]] = {
    "queued": frozenset({"ready", "todo"}),
    "implementing": frozenset({"running"}),
    "verifying": frozenset({"running"}),
    "implement_rework": frozenset({"todo", "running"}),
    "blocked": frozenset({"blocked", "todo"}),
    "completed": frozenset({"done"}),
}
_DIRECT_STATUSES = frozenset(
    {
        WorkflowStatus.QUEUED,
        WorkflowStatus.IMPLEMENTING,
        WorkflowStatus.VERIFYING,
        WorkflowStatus.IMPLEMENT_REWORK,
        WorkflowStatus.BLOCKED,
        WorkflowStatus.COMPLETED,
    }
)
_DIRECT_TRANSITIONS: Mapping[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.QUEUED: frozenset({WorkflowStatus.IMPLEMENTING}),
    WorkflowStatus.IMPLEMENTING: frozenset({WorkflowStatus.VERIFYING, WorkflowStatus.BLOCKED}),
    WorkflowStatus.VERIFYING: frozenset({WorkflowStatus.IMPLEMENT_REWORK, WorkflowStatus.COMPLETED}),
    WorkflowStatus.IMPLEMENT_REWORK: frozenset({WorkflowStatus.IMPLEMENTING}),
    WorkflowStatus.BLOCKED: frozenset(),
    WorkflowStatus.COMPLETED: frozenset(),
}


@dataclass(frozen=True)
class WorkflowTemplate:
    id: str
    flow: str
    initial_stage: str
    initial_status: WorkflowStatus
    implement_stage: str
    allowed_stages: frozenset[str]
    allowed_statuses: frozenset[WorkflowStatus]
    allowed_transitions: Mapping[WorkflowStatus, frozenset[WorkflowStatus]]
    verification_source: str
    uses_review_lane: bool
    uses_product_acceptance: bool
    expected_kanban_lanes: Mapping[str, frozenset[str]]
    completion_summary: str

    def verifying_passed_status(self) -> WorkflowStatus:
        if self.uses_review_lane:
            return WorkflowStatus.REVIEW_REQUESTED
        return WorkflowStatus.COMPLETED

    def completed_next_status(
        self,
        stage: str,
        *,
        verdict: str | None = None,
        outcome: str | None = None,
    ) -> WorkflowStatus:
        if stage == "plan":
            return WorkflowStatus.PLAN_REVIEWING
        if stage in {"implement", "direct_implement"}:
            if stage == "direct_implement" and outcome == "blocked":
                return WorkflowStatus.BLOCKED
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

    def require_clean_at_start(self, stage: str, *, implement_rework_count: int) -> bool:
        if stage in {"plan", "plan_review"}:
            return True
        if stage == self.implement_stage:
            return implement_rework_count == 0
        return False


FULL_TEMPLATE = WorkflowTemplate(
    id=FULL_TEMPLATE_ID,
    flow="full",
    initial_stage="plan",
    initial_status=WorkflowStatus.PLANNING,
    implement_stage="implement",
    allowed_stages=frozenset({"plan", "plan_review", "implement", "execute_review"}),
    allowed_statuses=frozenset(WorkflowStatus),
    allowed_transitions=ALLOWED_TRANSITIONS,
    verification_source="plan",
    uses_review_lane=True,
    uses_product_acceptance=True,
    expected_kanban_lanes=_FULL_LANES,
    completion_summary="Product acceptance passed.",
)

DIRECT_TEMPLATE = WorkflowTemplate(
    id=DIRECT_TEMPLATE_ID,
    flow="direct",
    initial_stage="direct_implement",
    initial_status=WorkflowStatus.IMPLEMENTING,
    implement_stage="direct_implement",
    allowed_stages=frozenset({"direct_implement"}),
    allowed_statuses=_DIRECT_STATUSES,
    allowed_transitions=_DIRECT_TRANSITIONS,
    verification_source="intake",
    uses_review_lane=False,
    uses_product_acceptance=False,
    expected_kanban_lanes=_DIRECT_LANES,
    completion_summary="Direct implementation verification passed.",
)

TEMPLATES: Mapping[str, WorkflowTemplate] = {
    FULL_TEMPLATE_ID: FULL_TEMPLATE,
    DIRECT_TEMPLATE_ID: DIRECT_TEMPLATE,
}

FLOW_TO_TEMPLATE: Mapping[str, str] = {
    "full": FULL_TEMPLATE_ID,
    "direct": DIRECT_TEMPLATE_ID,
}


def get_template(template_id: str) -> WorkflowTemplate:
    template = TEMPLATES.get(template_id)
    if template is None:
        raise WorkflowProtocolError(f"unknown workflow template {template_id!r}")
    return template


def template_for_flow(flow: str) -> WorkflowTemplate:
    template_id = FLOW_TO_TEMPLATE.get(flow)
    if template_id is None:
        raise WorkflowProtocolError(f"unknown workflow flow {flow!r}")
    return get_template(template_id)
