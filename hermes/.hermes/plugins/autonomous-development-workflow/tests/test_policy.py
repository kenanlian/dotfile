"""Table-driven transition policy: unique next action, rework and transport limits."""

from __future__ import annotations

import inspect
import unittest

from plugin_imports import import_plugin

_policy = import_plugin("controller.policy")
_types = import_plugin("controller.types")

ALLOWED_TRANSITIONS = _types.ALLOWED_TRANSITIONS
WorkflowConflict = _types.WorkflowConflict
WorkflowProtocolError = _types.WorkflowProtocolError
WorkflowStatus = _types.WorkflowStatus
ActiveJobView = _policy.ActiveJobView
PolicySnapshot = _policy.PolicySnapshot
WorkflowAction = _policy.WorkflowAction
next_action = _policy.next_action
next_allowed_transitions = _policy.next_allowed_transitions

LEGAL_EDGES = (
    (WorkflowStatus.QUEUED, WorkflowStatus.PLANNING),
    (WorkflowStatus.PLANNING, WorkflowStatus.PLAN_REVIEWING),
    (WorkflowStatus.PLAN_REVIEWING, WorkflowStatus.PLAN_REWORK),
    (WorkflowStatus.PLAN_REVIEWING, WorkflowStatus.BLOCKED),
    (WorkflowStatus.PLAN_REVIEWING, WorkflowStatus.IMPLEMENTING),
    (WorkflowStatus.PLAN_REWORK, WorkflowStatus.PLANNING),
    (WorkflowStatus.IMPLEMENTING, WorkflowStatus.VERIFYING),
    (WorkflowStatus.VERIFYING, WorkflowStatus.IMPLEMENT_REWORK),
    (WorkflowStatus.VERIFYING, WorkflowStatus.REVIEW_REQUESTED),
    (WorkflowStatus.REVIEW_REQUESTED, WorkflowStatus.CODE_REVIEWING),
    (WorkflowStatus.IMPLEMENT_REWORK, WorkflowStatus.IMPLEMENTING),
    (WorkflowStatus.CODE_REVIEWING, WorkflowStatus.IMPLEMENT_REWORK),
    (WorkflowStatus.CODE_REVIEWING, WorkflowStatus.BLOCKED),
    (WorkflowStatus.CODE_REVIEWING, WorkflowStatus.PRODUCT_ACCEPTANCE),
    (WorkflowStatus.PRODUCT_ACCEPTANCE, WorkflowStatus.IMPLEMENT_REWORK),
    (WorkflowStatus.PRODUCT_ACCEPTANCE, WorkflowStatus.BLOCKED),
    (WorkflowStatus.PRODUCT_ACCEPTANCE, WorkflowStatus.COMPLETED),
)

ILLEGAL_EDGES = (
    (WorkflowStatus.QUEUED, WorkflowStatus.COMPLETED),
    (WorkflowStatus.QUEUED, WorkflowStatus.IMPLEMENTING),
    (WorkflowStatus.PLANNING, WorkflowStatus.PRODUCT_ACCEPTANCE),
    (WorkflowStatus.COMPLETED, WorkflowStatus.PLANNING),
    (WorkflowStatus.REVIEW_REQUESTED, WorkflowStatus.IMPLEMENTING),
    (WorkflowStatus.PLAN_REVIEWING, WorkflowStatus.VERIFYING),
    (WorkflowStatus.BLOCKED, WorkflowStatus.PLANNING),
    (WorkflowStatus.VERIFYING, WorkflowStatus.CODE_REVIEWING),
    (WorkflowStatus.VERIFYING, WorkflowStatus.COMPLETED),
    (WorkflowStatus.IMPLEMENTING, WorkflowStatus.BLOCKED),
)


def _snapshot(**overrides) -> PolicySnapshot:
    data = dict(
        status=WorkflowStatus.QUEUED,
        plan_rework_count=0,
        implement_rework_count=0,
        run_failure_counts={},
        active_job=None,
        last_consumed_job_id=None,
        last_consumed_result_sha256=None,
        pending_lifecycle=None,
        planner_session_id=None,
        implementer_session_id=None,
        resume_status=None,
        implement_checks=None,
        kanban_status=None,
        template_id="autonomous-development.v1",
    )
    data.update(overrides)
    return PolicySnapshot(**data)


def _job(**overrides) -> ActiveJobView:
    data = dict(
        job_id="job_plan1",
        stage="plan",
        status="running",
        result=None,
        consumed=False,
        result_sha256=None,
        business_attempt=1,
        transport_retry=0,
    )
    data.update(overrides)
    return ActiveJobView(**data)


class NextAllowedTransitionsTests(unittest.TestCase):
    def test_legal_edges_are_derived_from_the_status_table(self) -> None:
        for source, target in LEGAL_EDGES:
            with self.subTest(source=source.value, target=target.value):
                allowed = next_allowed_transitions(source)
                self.assertIn(target, allowed)
                self.assertEqual(allowed, ALLOWED_TRANSITIONS[source])

    def test_illegal_edges_are_absent(self) -> None:
        for source, target in ILLEGAL_EDGES:
            with self.subTest(source=source.value, target=target.value):
                self.assertNotIn(target, next_allowed_transitions(source))

    def test_caller_cannot_pass_extra_transitions(self) -> None:
        parameters = inspect.signature(next_allowed_transitions).parameters
        self.assertEqual(tuple(parameters), ("status",))


class WorkflowActionKindTests(unittest.TestCase):
    def test_action_is_frozen_with_seven_kinds(self) -> None:
        action = WorkflowAction(kind="noop")
        self.assertTrue(action.__dataclass_fields__["kind"])  # type: ignore[attr-defined]
        with self.assertRaises(Exception):
            action.kind = "block"  # type: ignore[misc]
        kinds = {spec.kind for spec in (
            WorkflowAction(kind="create_job", stage="plan", target_status=WorkflowStatus.PLANNING),
            WorkflowAction(kind="observe_job", stage="plan"),
            WorkflowAction(kind="consume_job", stage="plan"),
            WorkflowAction(kind="apply_lifecycle", target_status=WorkflowStatus.REVIEW_REQUESTED),
            WorkflowAction(kind="await_acceptance"),
            WorkflowAction(kind="block", target_status=WorkflowStatus.BLOCKED, reason="limit"),
            WorkflowAction(kind="noop"),
        )}
        self.assertEqual(
            kinds,
            {
                "create_job",
                "observe_job",
                "consume_job",
                "apply_lifecycle",
                "await_acceptance",
                "block",
                "noop",
            },
        )


class NextActionTests(unittest.TestCase):
    def test_pending_lifecycle_wins_over_job_creation(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.REVIEW_REQUESTED,
                pending_lifecycle={"tool": "kanban_request_review", "runId": "run_1"},
            )
        )
        self.assertEqual(action.kind, "apply_lifecycle")
        self.assertEqual(action.target_status, WorkflowStatus.REVIEW_REQUESTED)

    def test_queued_creates_fresh_plan_job(self) -> None:
        action = next_action(_snapshot(status=WorkflowStatus.QUEUED))
        self.assertEqual(action.kind, "create_job")
        self.assertEqual(action.stage, "plan")
        self.assertEqual(action.target_status, WorkflowStatus.PLANNING)

    def test_planning_without_job_creates_plan_job(self) -> None:
        action = next_action(_snapshot(status=WorkflowStatus.PLANNING))
        self.assertEqual(action.kind, "create_job")
        self.assertEqual(action.stage, "plan")

    def test_running_job_is_observed(self) -> None:
        action = next_action(
            _snapshot(status=WorkflowStatus.PLANNING, active_job=_job(status="running"))
        )
        self.assertEqual(action.kind, "observe_job")
        self.assertEqual(action.stage, "plan")

    def test_pending_job_is_observed_until_started(self) -> None:
        action = next_action(
            _snapshot(status=WorkflowStatus.PLANNING, active_job=_job(status="pending"))
        )
        self.assertEqual(action.kind, "observe_job")

    def test_unconsumed_terminal_result_is_consumed(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.PLANNING,
                active_job=_job(status="completed", result={"status": "completed"}, result_sha256="a" * 64),
            )
        )
        self.assertEqual(action.kind, "consume_job")

    def test_same_result_reconsume_is_noop_then_advances_from_status(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.PLAN_REVIEWING,
                last_consumed_job_id="job_plan1",
                last_consumed_result_sha256="a" * 64,
                active_job=_job(
                    status="completed",
                    consumed=True,
                    result={"status": "completed"},
                    result_sha256="a" * 64,
                ),
            )
        )
        self.assertEqual(action.kind, "create_job")
        self.assertEqual(action.stage, "plan_review")

    def test_different_result_for_same_job_conflicts(self) -> None:
        with self.assertRaises(WorkflowConflict):
            next_action(
                _snapshot(
                    status=WorkflowStatus.PLANNING,
                    last_consumed_job_id="job_plan1",
                    last_consumed_result_sha256="a" * 64,
                    active_job=_job(
                        status="completed",
                        consumed=True,
                        result={"status": "completed"},
                        result_sha256="b" * 64,
                    ),
                )
            )

    def test_plan_review_approved_path_creates_implement_job_from_implementing(self) -> None:
        action = next_action(_snapshot(status=WorkflowStatus.IMPLEMENTING))
        self.assertEqual(action.kind, "create_job")
        self.assertEqual(action.stage, "implement")

    def test_plan_rework_resumes_planner(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.PLAN_REWORK,
                plan_rework_count=1,
                planner_session_id="sess_plan",
            )
        )
        self.assertEqual(action.kind, "create_job")
        self.assertEqual(action.stage, "plan")
        self.assertEqual(action.target_status, WorkflowStatus.PLANNING)

    def test_third_plan_rework_is_blocked(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.PLAN_REVIEWING,
                plan_rework_count=2,
                active_job=_job(
                    job_id="job_review",
                    stage="plan_review",
                    status="completed",
                    consumed=True,
                    result={"structuredOutput": {"payload": {"verdict": "request_changes"}}},
                    result_sha256="a" * 64,
                ),
                last_consumed_job_id="job_review",
                last_consumed_result_sha256="a" * 64,
                review_verdict="request_changes",
            )
        )
        self.assertEqual(action.kind, "block")
        self.assertEqual(action.target_status, WorkflowStatus.BLOCKED)
        self.assertEqual(action.reason, "plan_rework_limit")

    def test_first_two_plan_reworks_are_allowed(self) -> None:
        for count in (0, 1):
            with self.subTest(count=count):
                action = next_action(
                    _snapshot(
                        status=WorkflowStatus.PLAN_REVIEWING,
                        plan_rework_count=count,
                        review_verdict="request_changes",
                        active_job=_job(
                            job_id="job_review",
                            stage="plan_review",
                            status="completed",
                            consumed=True,
                            result_sha256="a" * 64,
                        ),
                        last_consumed_job_id="job_review",
                        last_consumed_result_sha256="a" * 64,
                    )
                )
                self.assertEqual(action.kind, "create_job")
                self.assertEqual(action.stage, "plan")
                self.assertEqual(action.target_status, WorkflowStatus.PLANNING)
                self.assertEqual(action.reason, "plan_rework")

    def test_verify_uses_implement_checks_without_a_fifth_agent(self) -> None:
        passed = next_action(
            _snapshot(
                status=WorkflowStatus.VERIFYING,
                implement_checks=(
                    {"id": "unit", "status": "passed"},
                    {"id": "lint", "status": "passed"},
                ),
            )
        )
        self.assertEqual(passed.kind, "apply_lifecycle")
        self.assertEqual(passed.target_status, WorkflowStatus.REVIEW_REQUESTED)
        self.assertEqual(passed.stage, None)

        failed = next_action(
            _snapshot(
                status=WorkflowStatus.VERIFYING,
                implement_rework_count=0,
                implementer_session_id="sess_impl",
                implement_checks=({"id": "unit", "status": "failed"},),
            )
        )
        self.assertEqual(failed.kind, "apply_lifecycle")
        self.assertEqual(failed.target_status, WorkflowStatus.IMPLEMENT_REWORK)
        self.assertEqual(failed.reason, "implement_rework")

    def test_empty_checks_fail_verification(self) -> None:
        action = next_action(_snapshot(status=WorkflowStatus.VERIFYING, implement_checks=()))
        self.assertEqual(action.kind, "apply_lifecycle")
        self.assertEqual(action.target_status, WorkflowStatus.IMPLEMENT_REWORK)
        self.assertEqual(action.reason, "implement_rework")

    def test_implement_rework_limit_from_verify_execute_review_and_acceptance(self) -> None:
        for status, extra in (
            (
                WorkflowStatus.VERIFYING,
                dict(implement_checks=({"id": "unit", "status": "failed"},)),
            ),
            (WorkflowStatus.CODE_REVIEWING, dict(review_verdict="request_changes")),
            (WorkflowStatus.PRODUCT_ACCEPTANCE, dict(review_verdict="failed")),
        ):
            with self.subTest(status=status.value):
                action = next_action(
                    _snapshot(
                        status=status,
                        implement_rework_count=2,
                        implementer_session_id="sess_impl",
                        **extra,
                    )
                )
                self.assertEqual(action.kind, "block")
                self.assertEqual(action.reason, "implement_rework_limit")

    def test_two_implement_reworks_are_allowed(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.VERIFYING,
                implement_rework_count=1,
                implementer_session_id="sess_impl",
                implement_checks=({"id": "unit", "status": "failed"},),
            )
        )
        self.assertEqual(action.kind, "apply_lifecycle")
        self.assertEqual(action.target_status, WorkflowStatus.IMPLEMENT_REWORK)

    def test_transport_failure_retries_same_business_attempt(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.PLANNING,
                run_failure_counts={"plan": 1},
                active_job=_job(
                    status="failed",
                    consumed=True,
                    result_sha256="a" * 64,
                    business_attempt=1,
                    transport_retry=0,
                ),
                last_consumed_job_id="job_plan1",
                last_consumed_result_sha256="a" * 64,
            )
        )
        self.assertEqual(action.kind, "create_job")
        self.assertEqual(action.stage, "plan")
        self.assertEqual(action.reason, "transport_retry")

    def test_third_transport_failure_per_stage_blocks(self) -> None:
        for status_name in ("failed", "timed_out", "aborted", "unavailable"):
            with self.subTest(status=status_name):
                action = next_action(
                    _snapshot(
                        status=WorkflowStatus.PLANNING,
                        run_failure_counts={"plan": 2},
                        active_job=_job(
                            status=status_name,
                            consumed=True,
                            result_sha256="a" * 64,
                        ),
                        last_consumed_job_id="job_plan1",
                        last_consumed_result_sha256="a" * 64,
                    )
                )
                self.assertEqual(action.kind, "block")
                self.assertEqual(action.reason, "transport_failure_limit")

    def test_reviewer_stages_are_always_fresh_jobs(self) -> None:
        plan_review = next_action(
            _snapshot(status=WorkflowStatus.PLAN_REVIEWING, planner_session_id="sess_plan")
        )
        self.assertEqual(plan_review.kind, "create_job")
        self.assertEqual(plan_review.stage, "plan_review")
        execute_review = next_action(
            _snapshot(status=WorkflowStatus.CODE_REVIEWING, implementer_session_id="sess_impl")
        )
        self.assertEqual(execute_review.kind, "create_job")
        self.assertEqual(execute_review.stage, "execute_review")

    def test_review_requested_without_pending_is_noop(self) -> None:
        action = next_action(_snapshot(status=WorkflowStatus.REVIEW_REQUESTED))
        self.assertEqual(action.kind, "noop")

    def test_product_acceptance_awaits_typed_submission(self) -> None:
        action = next_action(_snapshot(status=WorkflowStatus.PRODUCT_ACCEPTANCE))
        self.assertEqual(action.kind, "await_acceptance")

    def test_blocked_and_completed_are_noop(self) -> None:
        self.assertEqual(next_action(_snapshot(status=WorkflowStatus.BLOCKED)).kind, "noop")
        self.assertEqual(next_action(_snapshot(status=WorkflowStatus.COMPLETED)).kind, "noop")

    def test_blocked_stays_noop_while_kanban_is_blocked(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.BLOCKED,
                resume_status="product_acceptance",
                kanban_status="blocked",
            )
        )
        self.assertEqual(action.kind, "noop")

    def test_blocked_resumes_recorded_status_after_kanban_unblock(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.BLOCKED,
                resume_status="product_acceptance",
                kanban_status="running",
            )
        )
        self.assertEqual(action.kind, "await_acceptance")

    def test_blocked_without_resume_status_consumes_completed_active_job(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.BLOCKED,
                resume_status=None,
                kanban_status="todo",
                active_job=_job(
                    status="completed",
                    consumed=True,
                    result={"status": "completed"},
                    result_sha256="a" * 64,
                ),
            )
        )
        self.assertEqual(action.kind, "consume_job")
        self.assertEqual(action.stage, "plan")

    def test_blocked_without_resume_status_is_noop_when_no_completed_job(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.BLOCKED,
                resume_status=None,
                kanban_status="ready",
            )
        )
        self.assertEqual(action.kind, "noop")

    def test_review_blocked_verdict_blocks(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.PLAN_REVIEWING,
                review_verdict="blocked",
                active_job=_job(
                    job_id="job_review",
                    stage="plan_review",
                    status="completed",
                    consumed=True,
                    result_sha256="a" * 64,
                ),
                last_consumed_job_id="job_review",
                last_consumed_result_sha256="a" * 64,
            )
        )
        self.assertEqual(action.kind, "block")
        self.assertEqual(action.reason, "review_blocked")

    def test_code_review_approved_awaits_acceptance_via_product_acceptance_status(self) -> None:
        action = next_action(_snapshot(status=WorkflowStatus.PRODUCT_ACCEPTANCE))
        self.assertEqual(action.kind, "await_acceptance")

    def test_direct_queued_creates_direct_implement_job(self) -> None:
        action = next_action(
            _snapshot(status=WorkflowStatus.QUEUED, template_id="direct-implementation.v1")
        )
        self.assertEqual(action.kind, "create_job")
        self.assertEqual(action.stage, "direct_implement")
        self.assertEqual(action.target_status, WorkflowStatus.IMPLEMENTING)

    def test_direct_verifying_passed_completes_without_review(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.VERIFYING,
                template_id="direct-implementation.v1",
                implement_checks=({"id": "unit", "status": "passed"},),
            )
        )
        self.assertEqual(action.kind, "apply_lifecycle")
        self.assertEqual(action.target_status, WorkflowStatus.COMPLETED)

    def test_direct_check_failure_resumes_direct_implement(self) -> None:
        action = next_action(
            _snapshot(
                status=WorkflowStatus.VERIFYING,
                template_id="direct-implementation.v1",
                implement_rework_count=0,
                implementer_session_id="sess_direct",
                implement_checks=({"id": "unit", "status": "failed"},),
            )
        )
        self.assertEqual(action.kind, "apply_lifecycle")
        self.assertEqual(action.target_status, WorkflowStatus.IMPLEMENT_REWORK)
        self.assertEqual(action.reason, "implement_rework")

    def test_direct_rejects_full_only_statuses_before_full_flow_branch(self) -> None:
        for status in (
            WorkflowStatus.PLANNING,
            WorkflowStatus.PLAN_REVIEWING,
            WorkflowStatus.PLAN_REWORK,
            WorkflowStatus.REVIEW_REQUESTED,
            WorkflowStatus.CODE_REVIEWING,
            WorkflowStatus.PRODUCT_ACCEPTANCE,
        ):
            with self.subTest(status=status.value):
                with self.assertRaises(WorkflowProtocolError):
                    next_action(
                        _snapshot(status=status, template_id="direct-implementation.v1")
                    )

    def test_full_rejects_direct_implement_active_stage(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            next_action(
                _snapshot(
                    status=WorkflowStatus.IMPLEMENTING,
                    active_job=_job(stage="direct_implement", status="running"),
                )
            )

    def test_direct_rejects_plan_active_stage(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            next_action(
                _snapshot(
                    status=WorkflowStatus.IMPLEMENTING,
                    template_id="direct-implementation.v1",
                    active_job=_job(stage="plan", status="running"),
                )
            )


if __name__ == "__main__":
    unittest.main()
