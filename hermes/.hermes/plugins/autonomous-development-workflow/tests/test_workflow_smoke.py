"""External workflow smoke: 15 recovery scenarios, mock harness, CLI doctor/reconcile/abandon."""

from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import SmokeEnv, pre_tool_call
from plugin_imports import import_plugin

_cli = import_plugin("cli")
_hooks = import_plugin("hooks")
_service = import_plugin("controller.service")
_store = import_plugin("controller.store")
_types = import_plugin("controller.types")

WorkflowProtocolError = _types.WorkflowProtocolError
handle_autodev = _cli.handle_autodev
setup_autodev_cli = _cli.setup_autodev_cli
doctor_report = _service.doctor_report


class WorkflowSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = SmokeEnv()

    def tearDown(self) -> None:
        self.env.close()

    def test_01_intake_to_native_review(self) -> None:
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.assertEqual(self.env.kanban.cards[task_id]["status"], "ready")
        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        self.assertEqual(result["workflowStatus"], "review_requested")
        self.assertEqual(self.env.kanban.cards[task_id]["status"], "review")
        self.assertTrue(any(name == "kanban_request_review" for name, _ in self.env.kanban.tool_calls))
        jobs = {row["stage"] for row in self.env.store.list_jobs("project-board", task_id)}
        self.assertEqual(jobs, {"plan", "plan_review", "implement"})

    def test_02_fresh_review_to_acceptance_done(self) -> None:
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        self.env.kanban.claim_review(task_id, run_id="2")
        result = self.env.advance_until(task_id=task_id, run_id="2", outcomes={"acceptance_required"})
        self.assertEqual(result["outcome"], "acceptance_required")
        accepted = self.env.accept(task_id)
        self.assertEqual(accepted["workflowStatus"], "completed")
        self.assertEqual(self.env.kanban.cards[task_id]["status"], "done")
        exec_jobs = [
            row for row in self.env.store.list_jobs("project-board", task_id) if row["stage"] == "execute_review"
        ]
        self.assertEqual(len(exec_jobs), 1)

    def test_03_plan_request_changes_resumes_planner_reviewer_fresh(self) -> None:
        self.env.set_script(
            {
                "plan:1:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:1:0": {"status": "completed", "verdict": "request_changes"},
                "plan:2:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:2:0": {"status": "completed", "verdict": "approved"},
                "implement:1:0": {"status": "completed", "checks": "passed", "sessionId": "sess_impl_1"},
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        plan_jobs = [row for row in self.env.store.list_jobs("project-board", task_id) if row["stage"] == "plan"]
        review_jobs = [
            row for row in self.env.store.list_jobs("project-board", task_id) if row["stage"] == "plan_review"
        ]
        self.assertEqual(len(plan_jobs), 2)
        first = json.loads(Path(plan_jobs[0]["job_path"]).read_text(encoding="utf-8"))
        second = json.loads(Path(plan_jobs[1]["job_path"]).read_text(encoding="utf-8"))
        self.assertIsNone(first["agent"]["sessionId"])
        self.assertEqual(second["agent"]["sessionId"], "sess_plan_1")
        for row in review_jobs:
            job = json.loads(Path(row["job_path"]).read_text(encoding="utf-8"))
            self.assertIsNone(job["agent"]["sessionId"])

    def test_04_execute_review_request_changes_resumes_implementer(self) -> None:
        self.env.set_script(
            {
                **json.loads((self.env.script_path).read_text(encoding="utf-8")),
                "execute_review:1:0": {"status": "completed", "verdict": "request_changes"},
                "implement:2:0": {"status": "completed", "checks": "passed", "sessionId": "sess_impl_1"},
                "execute_review:2:0": {"status": "completed", "verdict": "approved"},
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        self.env.kanban.claim_review(task_id, run_id="2")
        self.env.advance_until(task_id=task_id, run_id="2", statuses={"implement_rework"})
        self.assertEqual(self.env.kanban.cards[task_id]["status"], "todo")
        self.env.kanban.claim_ready(task_id, run_id="3")
        self.env.advance_until(task_id=task_id, run_id="3", statuses={"review_requested"})
        impl_jobs = [
            row for row in self.env.store.list_jobs("project-board", task_id) if row["stage"] == "implement"
        ]
        self.assertGreaterEqual(len(impl_jobs), 2)
        first = json.loads(Path(impl_jobs[0]["job_path"]).read_text(encoding="utf-8"))
        second = json.loads(Path(impl_jobs[1]["job_path"]).read_text(encoding="utf-8"))
        self.assertIsNone(first["agent"]["sessionId"])
        self.assertEqual(second["agent"]["sessionId"], "sess_impl_1")

    def test_05_result_before_checkpoint_does_not_relaunch(self) -> None:
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        original = self.env.store.checkpoint

        def boom(*args, **kwargs):
            raise RuntimeError("checkpoint crash")

        with patch.object(self.env.store, "checkpoint", boom):
            with self.assertRaises(RuntimeError):
                self.env.advance_until(task_id=task_id, statuses={"plan_reviewing"}, limit=3)
        del original
        launches = self.env.launch_count()
        self.assertGreaterEqual(launches, 1)
        consumed = self.env.controller().advance(
            board="project-board", task_id=task_id, run_id="1", wait_seconds=8
        )
        self.assertEqual(consumed["workflowStatus"], "plan_reviewing")
        self.assertEqual(self.env.launch_count(), launches)

    def test_06_checkpoint_before_lifecycle_applies_once(self) -> None:
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        from plugin_imports import import_plugin

        lifecycle = import_plugin("controller.lifecycle")
        original = lifecycle.apply_pending_lifecycle

        def crash_apply(*args, **kwargs):
            raise RuntimeError("after pending write")

        with patch.object(lifecycle, "apply_pending_lifecycle", crash_apply), patch.object(
            _service, "apply_pending_lifecycle", crash_apply
        ):
            with self.assertRaises(RuntimeError):
                self.env.advance_until(task_id=task_id, statuses={"review_requested"}, limit=8)
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertIsNotNone(manifest.get("pendingLifecycle"))
        reviews_before = [name for name, _ in self.env.kanban.tool_calls if name == "kanban_request_review"]
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        reviews = [name for name, _ in self.env.kanban.tool_calls if name == "kanban_request_review"]
        self.assertEqual(len(reviews), len(reviews_before) + 1)
        self.env.controller().advance(board="project-board", task_id=task_id, run_id="1")
        reviews_again = [name for name, _ in self.env.kanban.tool_calls if name == "kanban_request_review"]
        self.assertEqual(len(reviews_again), len(reviews))
        del original

    def test_07_late_result_from_old_run_does_not_move_new_run(self) -> None:
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        manifest = self.env.store.get_manifest("project-board", task_id)
        revision = manifest["revision"]
        jobs = self.env.store.list_jobs("project-board", task_id)
        late = Path(jobs[0]["run_dir"]) / "late-result.json"
        late.write_text(json.dumps({"schema": "coding-agent.result.v1", "status": "completed"}), encoding="utf-8")
        self.env.kanban.claim_review(task_id, run_id="99")
        pending = make_old_pending(manifest)
        if pending:
            current = self.env.store.get_manifest("project-board", task_id)
            current["pendingLifecycle"] = pending
            current["revision"] = int(current["revision"]) + 1
            self.env.store.cas_update_manifest(
                "project-board", task_id, expected_revision=int(current["revision"]) - 1, manifest=current
            )
            with self.assertRaises(WorkflowProtocolError):
                self.env.controller().advance(board="project-board", task_id=task_id, run_id="99")
        after = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(after["workflowStatus"], "review_requested")
        self.assertGreaterEqual(after["revision"], revision)

    def test_08_transport_failure_uses_new_retry_job_without_rework(self) -> None:
        self.env.set_script(
            {
                "plan:1:0": {"status": "failed", "error": "unavailable"},
                "plan:1:1": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:1:0": {"status": "completed", "verdict": "approved"},
                "implement:1:0": {"status": "completed", "checks": "passed"},
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        plan_jobs = [row for row in self.env.store.list_jobs("project-board", task_id) if row["stage"] == "plan"]
        self.assertEqual(len(plan_jobs), 2)
        self.assertEqual(plan_jobs[0]["transport_retry"], 0)
        self.assertEqual(plan_jobs[1]["transport_retry"], 1)
        self.assertNotEqual(plan_jobs[0]["run_dir"], plan_jobs[1]["run_dir"])
        self.assertNotEqual(plan_jobs[0]["job_id"], plan_jobs[1]["job_id"])
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["planReworkCount"], 0)

    def test_09_orphan_lock_is_diagnosed_and_not_silently_overwritten(self) -> None:
        self.env.set_script({"plan:1:0": {"status": "completed", "crash": "after_lock"}})
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        first = self.env.advance_until(task_id=task_id, outcomes={"in_progress", "ok", "blocked"}, limit=4)
        del first
        launches = self.env.launch_count()
        job = self.env.store.list_jobs("project-board", task_id)[0]
        lock = Path(job["run_dir"]) / "run.lock"
        self.assertTrue(lock.is_file())
        report = doctor_report(
            self.env.store,
            board="project-board",
            task_id=task_id,
            shown=self.env.kanban.show_payload(task_id),
            config=self.env.config,
        )
        self.assertTrue(any(item["code"] == "orphan_lock" for item in report["findings"]))
        before = lock.read_text(encoding="utf-8")
        self.env.controller().advance(board="project-board", task_id=task_id, run_id="1", wait_seconds=5)
        self.assertTrue(lock.is_file())
        self.assertEqual(lock.read_text(encoding="utf-8"), before)
        self.assertEqual(self.env.launch_count(), launches)

    def test_10_invalid_result_artifact_input_and_drift_cannot_advance(self) -> None:
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        self.env.kanban.claim_review(task_id, run_id="2")
        self.env.advance_until(task_id=task_id, run_id="2", outcomes={"acceptance_required"})
        (self.env.repo / "src" / "app.txt").write_text("drifted after review\n", encoding="utf-8")
        with self.assertRaises(WorkflowProtocolError):
            self.env.accept(task_id)
        plan = self.env.store.latest_artifact("project-board", task_id, "plan")
        Path(plan["path"]).write_text('{"tampered": true}', encoding="utf-8")
        report = doctor_report(self.env.store, board="project-board", task_id=task_id, config=self.env.config)
        self.assertTrue(any(item["code"] == "artifact_hash" for item in report["findings"]))

    def test_11_rework_limit_blocks(self) -> None:
        self.env.set_script(
            {
                "plan:1:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:1:0": {"status": "completed", "verdict": "request_changes"},
                "plan:2:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:2:0": {"status": "completed", "verdict": "request_changes"},
                "plan:3:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:3:0": {"status": "completed", "verdict": "request_changes"},
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"blocked"}, limit=16)
        self.assertEqual(result["workflowStatus"], "blocked")

    def test_12_acceptance_passed_failed_and_needs_human(self) -> None:
        def _to_acceptance(env: SmokeEnv) -> str:
            created = env.enqueue()
            task_id = created["task_id"]
            env.kanban.claim_ready(task_id)
            env.advance_until(task_id=task_id, statuses={"review_requested"})
            env.kanban.claim_review(task_id, run_id="2")
            env.advance_until(task_id=task_id, run_id="2", outcomes={"acceptance_required"})
            return task_id

        passed_id = _to_acceptance(self.env)
        passed = self.env.accept(passed_id)
        self.assertEqual(passed["workflowStatus"], "completed")

        failed_env = SmokeEnv()
        try:
            failed_id = _to_acceptance(failed_env)
            failed = failed_env.accept(
                failed_id,
                verdict="failed",
                summary="Checkout 500s",
                scenarios=[
                    {
                        "name": "checkout",
                        "status": "failed",
                        "evidence": [str(failed_env.evidence)],
                    }
                ],
                findings=[{"severity": "blocking", "problem": "500"}],
            )
            self.assertEqual(failed["workflowStatus"], "implement_rework")
        finally:
            failed_env.close()

        human_env = SmokeEnv()
        try:
            human_id = _to_acceptance(human_env)
            human = human_env.accept(
                human_id,
                verdict="needs_human",
                summary="Need copy",
                scenarios=[],
                question="What empty-state copy should we use?",
            )
            self.assertEqual(human["workflowStatus"], "blocked")
        finally:
            human_env.close()

    def test_13_serial_successor_stays_todo_while_predecessor_is_active(self) -> None:
        first = self.env.enqueue(title="first", key="first")
        second = self.env.enqueue(title="second", key="second")
        self.assertEqual(self.env.kanban.cards[second["task_id"]]["status"], "todo")
        self.env.kanban.claim_ready(first["task_id"])
        self.env.advance_until(task_id=first["task_id"], statuses={"review_requested"})
        self.assertEqual(self.env.kanban.cards[second["task_id"]]["status"], "todo")
        self.env.kanban.cards[first["task_id"]]["status"] = "blocked"
        self.assertEqual(self.env.kanban.cards[second["task_id"]]["status"], "todo")

    def test_14_final_txt_done_does_not_drive_protocol(self) -> None:
        self.env.set_script(
            {
                "plan:1:0": {
                    "status": "completed",
                    "crash": "before_result_write",
                    "finalText": '{"verdict":"approved"}\ndone\n',
                }
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, outcomes={"in_progress", "ok", "blocked"}, limit=4)
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertNotEqual(manifest["workflowStatus"], "plan_reviewing")
        job = self.env.store.list_jobs("project-board", task_id)[0]
        final = Path(job["run_dir"]) / "final.txt"
        self.assertTrue(final.is_file())
        self.assertIn("done", final.read_text(encoding="utf-8"))
        self.assertFalse((Path(job["run_dir"]) / "result.json").is_file())

    def test_15_ordinary_card_without_manifest_is_ignored_by_guard(self) -> None:
        class Ctx:
            def get_config(self, key, default=None):
                return {
                    "state_root": str(self_env.state_root),
                    "profile": "autodev",
                    "harness_command": list(self_env.config.harness_command),
                    "main_branch": "main",
                    "poll_interval_seconds": 5,
                    "advance_wait_seconds": 60,
                }.get(key, default)

        self_env = self.env
        result = pre_tool_call(
            ctx=Ctx(),
            tool_name="kanban_complete",
            args={"summary": "done"},
            task_id="session",
            environ={"HERMES_KANBAN_TASK": "t_ordinary", "HERMES_KANBAN_BOARD": "project-board"},
        )
        self.assertIsNone(result)


class CliRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = SmokeEnv()
        self.parser = argparse.ArgumentParser()
        setup_autodev_cli(self.parser)

    def tearDown(self) -> None:
        self.env.close()

    def _loader(self, key, default=None):
        mapping = {
            "profile": "autodev",
            "state_root": str(self.env.state_root),
            "harness_command": list(self.env.config.harness_command),
            "main_branch": "main",
            "poll_interval_seconds": 5,
            "advance_wait_seconds": 60,
        }
        return mapping.get(key, default)

    def test_status_doctor_reconcile_and_abandon(self) -> None:
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        status_args = self.parser.parse_args(["status", "--board", "project-board", task_id])
        rc = handle_autodev(status_args, config_loader=self._loader, run_command=self.env.kanban.run_argv)
        self.assertEqual(rc, 0)
        doctor_args = self.parser.parse_args(["doctor", "--board", "project-board", task_id])
        rc = handle_autodev(doctor_args, config_loader=self._loader, run_command=self.env.kanban.run_argv)
        self.assertIn(rc, {0, 1})
        recon_args = self.parser.parse_args(["reconcile", "--board", "project-board", task_id])
        rc = handle_autodev(recon_args, config_loader=self._loader, run_command=self.env.kanban.run_argv)
        self.assertEqual(rc, 0)
        abandon_args = self.parser.parse_args(
            ["abandon", "--board", "project-board", task_id, "--reason", "operator stop"]
        )
        rc = handle_autodev(abandon_args, config_loader=self._loader, run_command=self.env.kanban.run_argv)
        self.assertEqual(rc, 0)
        lease = self.env.store.get_repo_lease(str(self.env.repo.resolve()))
        self.assertIsNotNone(lease["released_at"])
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["workflowStatus"], "blocked")
        self.assertEqual(manifest["abandonReason"], "operator stop")


def make_old_pending(manifest):
    from plugin_imports import import_plugin

    lifecycle = import_plugin("controller.lifecycle")
    current = manifest.get("pendingLifecycle")
    if current:
        bound = dict(current)
        bound["runId"] = "old-run"
        return bound
    return lifecycle.make_pending_lifecycle(
        target_status="completed",
        run_id="old-run",
        workflow_revision=int(manifest["revision"]) + 1,
    )


if __name__ == "__main__":
    unittest.main()
