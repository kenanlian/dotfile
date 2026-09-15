"""Direct-implementation.v1 workflow: no plan/review/acceptance, host checks only."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import SmokeEnv, _patched_env
from plugin_imports import import_plugin

_types = import_plugin("controller.types")
WorkflowProtocolError = _types.WorkflowProtocolError


def _verification_document(checks=None) -> dict:
    return {
        "schema": "autodev.verification.v1",
        "checks": checks
        if checks is not None
        else [
            {
                "id": "unit",
                "argv": ["true"],
                "cwd": ".",
                "timeoutSeconds": 30,
                "expectedExitCode": 0,
            }
        ],
    }


class DirectWorkflowSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = SmokeEnv()
        self.verification = self.env.root / "verification.json"
        self.verification.write_text(json.dumps(_verification_document()), encoding="utf-8")

    def tearDown(self) -> None:
        self.env.close()

    def _enqueue_direct(self, **overrides):
        kwargs = {"flow": "direct", "verification": str(self.verification)}
        kwargs.update(overrides)
        return self.env.enqueue(**kwargs)

    def test_direct_happy_path_completes_natively_without_review_or_acceptance(self) -> None:
        created = self._enqueue_direct()
        task_id = created["task_id"]
        self.assertEqual(created["flow"], "direct")
        self.assertEqual(created["templateId"], "direct-implementation.v1")
        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"completed"})
        self.assertEqual(result["workflowStatus"], "completed")
        self.assertEqual(result["flow"], "direct")
        self.assertEqual(self.env.kanban.cards[task_id]["status"], "done")
        self.assertFalse(any(name == "kanban_request_review" for name, _ in self.env.kanban.tool_calls))
        self.assertTrue(any(name == "kanban_complete" for name, _ in self.env.kanban.tool_calls))
        jobs = {row["stage"] for row in self.env.store.list_jobs("project-board", task_id)}
        self.assertEqual(jobs, {"direct_implement"})
        self.assertIsNone(self.env.store.latest_artifact("project-board", task_id, "plan"))
        self.assertIsNone(self.env.store.latest_artifact("project-board", task_id, "product-acceptance"))
        self.assertIsNotNone(self.env.store.latest_artifact("project-board", task_id, "direct-implementation"))
        job = json.loads(
            Path(self.env.store.list_jobs("project-board", task_id)[0]["job_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(job["inputs"][0]["kind"], "requirement")
        self.assertEqual(job["verification"][0]["id"], "unit")

    def test_direct_check_failure_resumes_same_implementer_session_and_honors_rework_limit(self) -> None:
        self.env.set_script(
            {
                "direct_implement:1:0": {
                    "status": "completed",
                    "checks": "failed",
                    "sessionId": "sess_direct_1",
                },
                "direct_implement:2:0": {
                    "status": "completed",
                    "checks": "passed",
                    "sessionId": "sess_direct_1",
                },
            }
        )
        created = self._enqueue_direct()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        recorded: list[str] = []
        store = self.env.store
        orig_cas = store.cas_update_manifest
        orig_checkpoint = store.checkpoint

        def _note(manifest):
            status = manifest.get("workflowStatus")
            if status and (not recorded or recorded[-1] != status):
                recorded.append(status)

        def cas(board, task_id, *, expected_revision, manifest):
            _note(manifest)
            return orig_cas(board, task_id, expected_revision=expected_revision, manifest=manifest)

        def checkpoint(**kwargs):
            _note(kwargs["manifest"])
            return orig_checkpoint(**kwargs)

        store.cas_update_manifest = cas
        store.checkpoint = checkpoint
        controller = self.env.controller()
        env = self.env.harness_env()
        result = None
        for _ in range(20):
            with _patched_env(env):
                result = controller.advance(
                    board="project-board",
                    task_id=task_id,
                    run_id=str(self.env.kanban.run_id),
                    wait_seconds=8,
                )
            if result["workflowStatus"] == "completed":
                break
        else:
            raise AssertionError(f"did not complete: last={result} seen={recorded}")
        self.assertIn(
            ["verifying", "implement_rework", "implementing"],
            [recorded[i : i + 3] for i in range(len(recorded) - 2)],
        )
        self.assertEqual(result["workflowStatus"], "completed")
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(int(manifest.get("implementReworkCount") or 0), 1)
        self.assertTrue(any(name == "kanban_request_changes" for name, _ in self.env.kanban.tool_calls))
        rows = [
            row
            for row in self.env.store.list_jobs("project-board", task_id)
            if row["stage"] == "direct_implement"
        ]
        self.assertEqual(len(rows), 2)
        first = json.loads(Path(rows[0]["job_path"]).read_text(encoding="utf-8"))
        second = json.loads(Path(rows[1]["job_path"]).read_text(encoding="utf-8"))
        self.assertIsNone(first["agent"]["sessionId"])
        self.assertEqual(second["agent"]["sessionId"], "sess_direct_1")
        self.assertFalse(any(name == "kanban_request_review" for name, _ in self.env.kanban.tool_calls))

        limited = SmokeEnv()
        try:
            verification = limited.root / "verification.json"
            verification.write_text(json.dumps(_verification_document()), encoding="utf-8")
            limited.set_script(
                {
                    "direct_implement:1:0": {"status": "completed", "checks": "failed", "sessionId": "sess_a"},
                    "direct_implement:2:0": {"status": "completed", "checks": "failed", "sessionId": "sess_a"},
                    "direct_implement:3:0": {"status": "completed", "checks": "failed", "sessionId": "sess_a"},
                }
            )
            card = limited.enqueue(flow="direct", verification=str(verification))
            limited.kanban.claim_ready(card["task_id"])
            blocked = limited.advance_until(task_id=card["task_id"], statuses={"blocked"}, limit=12)
            self.assertEqual(blocked["workflowStatus"], "blocked")
            jobs = [
                row
                for row in limited.store.list_jobs("project-board", card["task_id"])
                if row["stage"] == "direct_implement"
            ]
            self.assertEqual(len(jobs), 3)
        finally:
            limited.close()

    def test_direct_blocked_structured_outcome_blocks_rather_than_completing(self) -> None:
        self.env.set_script(
            {
                "direct_implement:1:0": {
                    "status": "completed",
                    "outcome": "blocked",
                    "blockingIssues": ["external credential missing"],
                    "sessionId": "sess_direct_block",
                }
            }
        )
        created = self._enqueue_direct()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"blocked"})
        self.assertEqual(result["workflowStatus"], "blocked")
        self.assertEqual(self.env.kanban.cards[task_id]["status"], "blocked")
        self.assertFalse(any(name == "kanban_complete" for name, _ in self.env.kanban.tool_calls))
        jobs = {row["stage"] for row in self.env.store.list_jobs("project-board", task_id)}
        self.assertEqual(jobs, {"direct_implement"})

    def test_direct_transport_failures_resume_session_or_stay_fresh(self) -> None:
        cases = (
            ("failed", "sess_direct_failed", True),
            ("timed_out", None, False),
            ("aborted", "sess_direct_aborted", True),
            ("unavailable", None, False),
        )
        for status, session_id, resume in cases:
            with self.subTest(status=status, resume=resume):
                env = SmokeEnv()
                try:
                    verification = env.root / "verification.json"
                    verification.write_text(json.dumps(_verification_document()), encoding="utf-8")
                    first_spec = {"status": status, "sessionId": session_id}
                    second_spec = {"status": "completed", "checks": "passed"}
                    if resume:
                        second_spec["sessionId"] = session_id
                    env.set_script(
                        {
                            "direct_implement:1:0": first_spec,
                            "direct_implement:1:1": second_spec,
                        }
                    )
                    card = env.enqueue(flow="direct", verification=str(verification))
                    env.kanban.claim_ready(card["task_id"])
                    result = env.advance_until(task_id=card["task_id"], statuses={"completed"})
                    self.assertEqual(result["workflowStatus"], "completed")
                    rows = [
                        row
                        for row in env.store.list_jobs("project-board", card["task_id"])
                        if row["stage"] == "direct_implement"
                    ]
                    self.assertEqual(len(rows), 2)
                    self.assertEqual(rows[0]["transport_retry"], 0)
                    self.assertEqual(rows[1]["transport_retry"], 1)
                    first = json.loads(Path(rows[0]["job_path"]).read_text(encoding="utf-8"))
                    second = json.loads(Path(rows[1]["job_path"]).read_text(encoding="utf-8"))
                    self.assertIsNone(first["agent"]["sessionId"])
                    if resume:
                        self.assertEqual(second["agent"]["sessionId"], session_id)
                    else:
                        self.assertIsNone(second["agent"]["sessionId"])
                    manifest = env.store.get_manifest("project-board", card["task_id"])
                    self.assertEqual(int(manifest.get("implementReworkCount") or 0), 0)
                finally:
                    env.close()

    def test_direct_transport_retry_rejects_a_different_session(self) -> None:
        self.env.set_script(
            {
                "direct_implement:1:0": {"status": "failed", "sessionId": "sess_keep"},
                "direct_implement:1:1": {
                    "status": "completed",
                    "checks": "passed",
                    "sessionId": "sess_other",
                },
            }
        )
        created = self._enqueue_direct()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"blocked"})
        self.assertEqual(result["workflowStatus"], "blocked")
        rows = [
            row
            for row in self.env.store.list_jobs("project-board", task_id)
            if row["stage"] == "direct_implement"
        ]
        self.assertEqual(len(rows), 2)
        second = json.loads(Path(rows[1]["job_path"]).read_text(encoding="utf-8"))
        self.assertEqual(second["agent"]["sessionId"], "sess_keep")

    def test_product_acceptance_is_rejected_for_direct_template(self) -> None:
        created = self._enqueue_direct()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"completed"})
        with self.assertRaises(WorkflowProtocolError):
            self.env.accept(task_id)


if __name__ == "__main__":
    unittest.main()
