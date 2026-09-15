"""Protocol, Result binding, Acceptance, and config validators (stdlib unittest)."""

from __future__ import annotations

import hashlib
import unittest

from plugin_imports import import_plugin

_config = import_plugin("config")
_protocol = import_plugin("controller.protocol")
_types = import_plugin("controller.types")

load_plugin_config = _config.load_plugin_config
assert_allowed_transition = _protocol.assert_allowed_transition
bind_result = _protocol.bind_result
parse_acceptance = _protocol.parse_acceptance
parse_artifact_ref = _protocol.parse_artifact_ref
parse_job_expectation = _protocol.parse_job_expectation
parse_manifest = _protocol.parse_manifest
validate_completed_result = _protocol.validate_completed_result
JOB_SCHEMA = _types.JOB_SCHEMA
RESULT_SCHEMA = _types.RESULT_SCHEMA
WORKFLOW_SCHEMA = _types.WORKFLOW_SCHEMA
WORKFLOW_TEMPLATE_ID = _types.WORKFLOW_TEMPLATE_ID
WorkflowProtocolError = _types.WorkflowProtocolError
WorkflowStatus = _types.WorkflowStatus


def _sha(text: str = "payload") -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _manifest(**overrides):
    data = {
        "schema": WORKFLOW_SCHEMA,
        "templateId": WORKFLOW_TEMPLATE_ID,
        "board": "project-board",
        "taskId": "t_abc",
        "repoRoot": "/abs/repo",
        "workflowStatus": "planning",
        "revision": 1,
        "baseline": {"branch": "main", "head": "a" * 40},
        "candidateFingerprint": None,
        "approvedPlan": None,
    }
    data.update(overrides)
    return data


def _expectation(**overrides):
    data = {
        "jobId": "job_plan1",
        "taskId": "t_abc",
        "stage": "plan",
        "idempotencyKey": "board:t_abc:plan:1:0:deadbeef",
        "jobSha256": _sha("job"),
        "sessionId": None,
        "outputKind": "plan",
        "outputSchema": "plan.v1",
    }
    data.update(overrides)
    return data


def _result(**overrides):
    job_hash = overrides.pop("jobSha256", _sha("job"))
    stage = overrides.get("stage", "plan")
    kind = {
        "plan": "plan",
        "plan_review": "plan-review",
        "implement": "implementation",
        "execute_review": "execute-review",
    }[stage]
    schema = f"{kind}.v1" if kind != "plan-review" else "plan-review.v1"
    if kind == "implementation":
        schema = "implementation.v1"
    if kind == "execute-review":
        schema = "execute-review.v1"
    artifact = {
        "kind": kind,
        "path": f"/abs/artifacts/{kind}.json",
        "sha256": _sha(kind),
        "schema": schema,
        "canonical": True,
    }
    data = {
        "schema": RESULT_SCHEMA,
        "jobId": "job_plan1",
        "idempotencyKey": "board:t_abc:plan:1:0:deadbeef",
        "jobSha256": job_hash,
        "taskId": "t_abc",
        "stage": "plan",
        "status": "completed",
        "sessionId": None,
        "structuredOutput": {"kind": kind, "payload": {"schema": schema, "summary": "ok"}},
        "artifacts": [artifact],
    }
    data.update(overrides)
    return data


def _acceptance(**overrides):
    data = {
        "verdict": "passed",
        "summary": "Login and dashboard work.",
        "scenarios": [
            {"name": "login", "status": "passed", "evidence": ["/abs/evidence/login.png"]},
        ],
        "findings": [],
        "question": None,
        "candidateFingerprint": _sha("candidate"),
    }
    data.update(overrides)
    return data


class ManifestValidationTests(unittest.TestCase):
    def test_valid_manifest_is_accepted(self) -> None:
        parsed = parse_manifest(_manifest())
        self.assertEqual(parsed.schema, WORKFLOW_SCHEMA)
        self.assertEqual(parsed.template_id, WORKFLOW_TEMPLATE_ID)
        self.assertEqual(parsed.status, WorkflowStatus.PLANNING)

    def test_unknown_schema_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_manifest(_manifest(schema="other.workflow.v1"))

    def test_unknown_template_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_manifest(_manifest(templateId="other.v1"))

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_manifest(_manifest(workflowStatus="deploying"))

    def test_empty_task_and_board_are_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_manifest(_manifest(taskId=""))
        with self.assertRaises(WorkflowProtocolError):
            parse_manifest(_manifest(board="   "))

    def test_relative_repo_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_manifest(_manifest(repoRoot="repo"))
        with self.assertRaises(WorkflowProtocolError):
            parse_manifest(_manifest(repoRoot="./repo"))

    def test_non_sha256_hashes_are_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_artifact_ref(
                {
                    "kind": "plan",
                    "path": "/abs/plan.json",
                    "sha256": "not-a-hash",
                    "schema": "plan.v1",
                    "canonical": True,
                }
            )
        with self.assertRaises(WorkflowProtocolError):
            parse_artifact_ref(
                {
                    "kind": "plan",
                    "path": "/abs/plan.json",
                    "sha256": "A" * 64,
                    "schema": "plan.v1",
                    "canonical": True,
                }
            )

    def test_relative_artifact_path_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_artifact_ref(
                {
                    "kind": "plan",
                    "path": "plan.json",
                    "sha256": _sha("plan"),
                    "schema": "plan.v1",
                    "canonical": True,
                }
            )


class TransitionTests(unittest.TestCase):
    def test_legal_edges_are_accepted(self) -> None:
        assert_allowed_transition("queued", "planning")
        assert_allowed_transition("planning", "plan_reviewing")
        assert_allowed_transition("plan_reviewing", "implementing")
        assert_allowed_transition("plan_reviewing", "plan_rework")
        assert_allowed_transition("plan_rework", "planning")
        assert_allowed_transition("implementing", "verifying")
        assert_allowed_transition("verifying", "review_requested")
        assert_allowed_transition("verifying", "implement_rework")
        assert_allowed_transition("implement_rework", "implementing")
        assert_allowed_transition("review_requested", "code_reviewing")
        assert_allowed_transition("code_reviewing", "product_acceptance")
        assert_allowed_transition("code_reviewing", "implement_rework")
        assert_allowed_transition("product_acceptance", "completed")
        assert_allowed_transition("product_acceptance", "implement_rework")
        assert_allowed_transition("product_acceptance", "blocked")
        assert_allowed_transition("plan_reviewing", "blocked")
        assert_allowed_transition("code_reviewing", "blocked")

    def test_illegal_edges_are_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            assert_allowed_transition("queued", "completed")
        with self.assertRaises(WorkflowProtocolError):
            assert_allowed_transition("planning", "product_acceptance")
        with self.assertRaises(WorkflowProtocolError):
            assert_allowed_transition("completed", "planning")
        with self.assertRaises(WorkflowProtocolError):
            assert_allowed_transition("review_requested", "implementing")
        with self.assertRaises(WorkflowProtocolError):
            assert_allowed_transition("plan_reviewing", "verifying")


class ResultBindingTests(unittest.TestCase):
    def test_matching_result_binds(self) -> None:
        expectation = parse_job_expectation(_expectation())
        bind_result(expectation, _result())

    def test_job_mismatch_is_rejected(self) -> None:
        expectation = parse_job_expectation(_expectation())
        with self.assertRaises(WorkflowProtocolError):
            bind_result(expectation, _result(jobId="job_other"))

    def test_task_mismatch_is_rejected(self) -> None:
        expectation = parse_job_expectation(_expectation())
        with self.assertRaises(WorkflowProtocolError):
            bind_result(expectation, _result(taskId="t_other"))

    def test_stage_mismatch_is_rejected(self) -> None:
        expectation = parse_job_expectation(_expectation())
        with self.assertRaises(WorkflowProtocolError):
            bind_result(expectation, _result(stage="implement"))

    def test_idempotency_mismatch_is_rejected(self) -> None:
        expectation = parse_job_expectation(_expectation())
        with self.assertRaises(WorkflowProtocolError):
            bind_result(expectation, _result(idempotencyKey="other"))

    def test_job_hash_mismatch_is_rejected(self) -> None:
        expectation = parse_job_expectation(_expectation())
        with self.assertRaises(WorkflowProtocolError):
            bind_result(expectation, _result(jobSha256=_sha("other-job")))

    def test_completed_requires_session_and_rejects_resume_mismatch(self) -> None:
        expectation = parse_job_expectation(_expectation())
        validate_completed_result(expectation, _result(sessionId="sess_fresh"))
        resume = parse_job_expectation(_expectation(sessionId="sess_1"))
        bind_result(resume, _result(sessionId="sess_1"))
        with self.assertRaises(WorkflowProtocolError):
            bind_result(resume, _result(sessionId="sess_2"))
        with self.assertRaises(WorkflowProtocolError):
            bind_result(resume, _result(sessionId=None))


class CompletedResultTests(unittest.TestCase):
    def test_completed_plan_requires_matching_output_and_canonical_artifact(self) -> None:
        expectation = parse_job_expectation(_expectation())
        validate_completed_result(expectation, _result())

    def test_completed_without_structured_output_is_rejected(self) -> None:
        expectation = parse_job_expectation(_expectation())
        with self.assertRaises(WorkflowProtocolError):
            validate_completed_result(expectation, _result(structuredOutput=None))

    def test_completed_with_wrong_output_kind_is_rejected(self) -> None:
        expectation = parse_job_expectation(_expectation())
        with self.assertRaises(WorkflowProtocolError):
            validate_completed_result(
                expectation,
                _result(
                    structuredOutput={
                        "kind": "implementation",
                        "payload": {"schema": "implementation.v1"},
                    }
                ),
            )

    def test_completed_without_canonical_artifact_is_rejected(self) -> None:
        expectation = parse_job_expectation(_expectation())
        with self.assertRaises(WorkflowProtocolError):
            validate_completed_result(
                expectation,
                _result(
                    artifacts=[
                        {
                            "kind": "plan",
                            "path": "/abs/artifacts/plan.json",
                            "sha256": _sha("plan"),
                            "schema": "plan.v1",
                            "canonical": False,
                        }
                    ]
                ),
            )

    def test_approved_review_cannot_include_blocking_finding(self) -> None:
        expectation = parse_job_expectation(
            _expectation(
                jobId="job_review1",
                stage="plan_review",
                outputKind="plan-review",
                outputSchema="plan-review.v1",
            )
        )
        payload = {
            "schema": "plan-review.v1",
            "verdict": "approved",
            "summary": "Looks good",
            "findings": [
                {
                    "severity": "blocking",
                    "location": "plan.md",
                    "problem": "Missing rollback",
                    "requiredChange": "Add rollback",
                }
            ],
        }
        with self.assertRaises(WorkflowProtocolError):
            validate_completed_result(
                expectation,
                _result(
                    jobId="job_review1",
                    stage="plan_review",
                    structuredOutput={"kind": "plan-review", "payload": payload},
                    artifacts=[
                        {
                            "kind": "plan-review",
                            "path": "/abs/artifacts/plan-review.json",
                            "sha256": _sha("plan-review"),
                            "schema": "plan-review.v1",
                            "canonical": True,
                        }
                    ],
                ),
            )


class SessionExpectationTests(unittest.TestCase):
    def test_reviewer_expectation_must_be_fresh(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_job_expectation(
                _expectation(
                    stage="plan_review",
                    sessionId="sess_old",
                    outputKind="plan-review",
                    outputSchema="plan-review.v1",
                )
            )
        with self.assertRaises(WorkflowProtocolError):
            parse_job_expectation(
                _expectation(
                    stage="execute_review",
                    sessionId="sess_old",
                    outputKind="execute-review",
                    outputSchema="execute-review.v1",
                )
            )
        parsed = parse_job_expectation(
            _expectation(
                stage="plan_review",
                sessionId=None,
                outputKind="plan-review",
                outputSchema="plan-review.v1",
            )
        )
        self.assertIsNone(parsed.session_id)

    def test_plan_and_implement_rework_require_exact_saved_session(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_job_expectation(_expectation(sessionId=None), saved_session="sess_plan")
        with self.assertRaises(WorkflowProtocolError):
            parse_job_expectation(
                _expectation(sessionId="sess_other"),
                saved_session="sess_plan",
            )
        parsed = parse_job_expectation(
            _expectation(sessionId="sess_plan"),
            saved_session="sess_plan",
        )
        self.assertEqual(parsed.session_id, "sess_plan")
        with self.assertRaises(WorkflowProtocolError):
            parse_job_expectation(
                _expectation(
                    stage="implement",
                    sessionId=None,
                    outputKind="implementation",
                    outputSchema="implementation.v1",
                ),
                saved_session="sess_impl",
            )
        parsed_impl = parse_job_expectation(
            _expectation(
                stage="implement",
                sessionId="sess_impl",
                outputKind="implementation",
                outputSchema="implementation.v1",
            ),
            saved_session="sess_impl",
        )
        self.assertEqual(parsed_impl.session_id, "sess_impl")


class AcceptanceTests(unittest.TestCase):
    def test_passed_requires_scenarios_fingerprint_and_no_blocking_finding(self) -> None:
        parsed = parse_acceptance(_acceptance(), expected_fingerprint=_sha("candidate"))
        self.assertEqual(parsed.verdict, "passed")

    def test_passed_without_scenarios_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_acceptance(
                _acceptance(scenarios=[]),
                expected_fingerprint=_sha("candidate"),
            )

    def test_passed_with_failed_scenario_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_acceptance(
                _acceptance(
                    scenarios=[{"name": "login", "status": "failed", "evidence": []}]
                ),
                expected_fingerprint=_sha("candidate"),
            )

    def test_passed_with_fingerprint_drift_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_acceptance(
                _acceptance(),
                expected_fingerprint=_sha("other-candidate"),
            )

    def test_passed_with_blocking_finding_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_acceptance(
                _acceptance(
                    findings=[{"severity": "blocking", "problem": "Broken checkout"}]
                ),
                expected_fingerprint=_sha("candidate"),
            )

    def test_needs_human_requires_explicit_question(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            parse_acceptance(
                _acceptance(verdict="needs_human", question=None),
                expected_fingerprint=_sha("candidate"),
            )
        with self.assertRaises(WorkflowProtocolError):
            parse_acceptance(
                _acceptance(verdict="needs_human", question="  "),
                expected_fingerprint=_sha("candidate"),
            )
        parsed = parse_acceptance(
            _acceptance(
                verdict="needs_human",
                question="What is the expected empty-state copy?",
                scenarios=[],
            ),
            expected_fingerprint=_sha("candidate"),
        )
        self.assertEqual(parsed.verdict, "needs_human")


class ConfigTests(unittest.TestCase):
    def test_config_reads_only_injected_mapping(self) -> None:
        cfg = load_plugin_config(
            {
                "profile": "autodev",
                "state_root": "/abs/state",
                "harness_command": ["node", "/abs/harness.mjs"],
                "main_branch": "main",
                "poll_interval_seconds": 5,
                "advance_wait_seconds": 60,
            }
        )
        self.assertEqual(cfg.profile, "autodev")
        self.assertEqual(cfg.harness_command, ("node", "/abs/harness.mjs"))

    def test_harness_command_must_be_nonempty_argv_list(self) -> None:
        base = {
            "profile": "autodev",
            "state_root": "/abs/state",
            "main_branch": "main",
            "poll_interval_seconds": 5,
            "advance_wait_seconds": 60,
        }
        with self.assertRaises(WorkflowProtocolError):
            load_plugin_config({**base, "harness_command": "node /abs/harness.mjs"})
        with self.assertRaises(WorkflowProtocolError):
            load_plugin_config({**base, "harness_command": []})
        with self.assertRaises(WorkflowProtocolError):
            load_plugin_config({**base, "harness_command": ["", "--job"]})
        with self.assertRaises(WorkflowProtocolError):
            load_plugin_config(base)

    def test_job_schema_constants_are_stable(self) -> None:
        self.assertEqual(JOB_SCHEMA, "coding-agent.job.v1")
        self.assertEqual(RESULT_SCHEMA, "coding-agent.result.v1")


if __name__ == "__main__":
    unittest.main()
