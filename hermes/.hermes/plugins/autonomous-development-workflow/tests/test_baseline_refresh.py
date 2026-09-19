"""Stale-baseline refresh, precondition failure classification, operator reset.

Reproduces the dotfile t_bf68d977 failure chain end to end against the mock
harness (which mirrors the real harness workspace preflight):

1. Cards queued behind an upstream card pin ``baseline.head`` at intake;
   once the upstream card commits, the pinned ``expectedHead`` would fail
   every Harness preflight.
2. Preflight ``workspace_mismatch`` Results must be classified as
   precondition failures, not transport failures, so they never burn the
   ``MAX_STAGE_TRANSPORT_FAILURES`` budget.
3. Clearing ``runFailureCounts`` alone re-derives a Job identity that
   collides with consumed dead Jobs; the operator repair must also null
   ``activeJobId`` in the same Manifest revision.
"""

from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path

from helpers import SmokeEnv, git
from plugin_imports import import_plugin

_cli = import_plugin("cli")
_types = import_plugin("controller.types")

WorkflowProtocolError = _types.WorkflowProtocolError
handle_autodev = _cli.handle_autodev
setup_autodev_cli = _cli.setup_autodev_cli


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


class BaselineRefreshTests(unittest.TestCase):
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

    def _commit_upstream(self, name: str = "upstream.txt") -> str:
        (self.env.repo / name).write_text("upstream change\n", encoding="utf-8")
        git(self.env.repo, "add", ".")
        git(self.env.repo, "commit", "-m", "upstream advances HEAD")
        return git(self.env.repo, "rev-parse", "HEAD")

    def test_unconsumed_workflow_refreshes_stale_baseline_before_first_job(self) -> None:
        """Acceptance 1+4: enqueue-time HEAD goes stale, the first Job must be
        created against the refreshed baseline, preflight passes, and the
        workflow never approaches transport_failure_limit."""
        self.env.set_script({"direct_implement:1:0": {"status": "completed"}})
        created = self._enqueue_direct()
        task_id = created["task_id"]
        manifest = self.env.store.get_manifest("project-board", task_id)
        stale_head = manifest["baseline"]["head"]

        new_head = self._commit_upstream()
        self.assertNotEqual(new_head, stale_head)

        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"completed"})
        self.assertEqual(result["workflowStatus"], "completed")

        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["baseline"]["head"], new_head)
        self.assertEqual(manifest["runFailureCounts"], {})
        rows = self.env.store.list_jobs("project-board", task_id)
        self.assertEqual(len(rows), 1)
        job_doc = json.loads(Path(rows[0]["job_path"]).read_text(encoding="utf-8"))
        self.assertEqual(job_doc["workspace"]["expectedHead"], new_head)
        # The mock harness genuinely validated branch/HEAD/clean-tree against
        # the refreshed expectedHead before completing the run.
        self.assertEqual(self.env.launch_count(), 1)
        self.assertTrue((Path(rows[0]["run_dir"]) / "result.json").is_file())

    def test_consumed_workflow_keeps_stale_baseline_pinned(self) -> None:
        """Acceptance 2: once a Job has been consumed the baseline is the
        relay contract between stages; a later HEAD advance must NOT refresh
        it, and the pinned Job fails as a precondition (not transport)."""
        self.env.set_script(
            {
                "direct_implement:1:0": {
                    "status": "completed",
                    "checks": "failed",
                    "sessionId": "sess_direct_1",
                },
            }
        )
        created = self._enqueue_direct()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"implement_rework"})

        # Upstream (or an operator) commits the in-tree candidate: HEAD
        # advances past the pinned baseline while a Job is already consumed.
        git(self.env.repo, "add", ".")
        git(self.env.repo, "commit", "-m", "candidate lands")
        pinned_head = self.env.store.get_manifest("project-board", task_id)["baseline"]["head"]
        self.assertNotEqual(git(self.env.repo, "rev-parse", "HEAD"), pinned_head)

        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"blocked"})
        self.assertEqual(result["workflowStatus"], "blocked")

        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["baseline"]["head"], pinned_head)
        # Pinned Job kept the stale contract and failed as a precondition —
        # no transport retry was minted and no count was recorded.
        self.assertEqual(manifest["runFailureCounts"], {})
        rows = [
            row
            for row in self.env.store.list_jobs("project-board", task_id)
            if row["stage"] == "direct_implement"
        ]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["transport_retry"] == 0 for row in rows))
        rework_doc = json.loads(Path(rows[1]["job_path"]).read_text(encoding="utf-8"))
        self.assertEqual(rework_doc["workspace"]["expectedHead"], pinned_head)
        block_calls = [
            args for name, args in self.env.kanban.tool_calls if name == "kanban_block"
        ]
        self.assertTrue(block_calls)
        self.assertIn("precondition", str(block_calls[-1].get("reason")))

    def test_dirty_tree_preflight_mismatch_blocks_without_transport_count(self) -> None:
        """Acceptance 3: a preflight workspace_mismatch (dirty tree where a
        clean start was required) blocks as a precondition failure and never
        increments runFailureCounts or creates a transport retry."""
        self.env.set_script({"direct_implement:1:0": {"status": "completed"}})
        created = self._enqueue_direct()
        task_id = created["task_id"]
        (self.env.repo / "stray.txt").write_text("uncommitted noise\n", encoding="utf-8")

        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"blocked"}, limit=6)
        self.assertEqual(result["workflowStatus"], "blocked")

        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["runFailureCounts"], {})
        self.assertEqual(manifest["resumeStatus"], "implementing")
        rows = self.env.store.list_jobs("project-board", task_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["transport_retry"], 0)
        result_doc = json.loads((Path(rows[0]["run_dir"]) / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result_doc["status"], "failed")
        self.assertEqual(result_doc["error"]["kind"], "workspace_mismatch")
        self.assertEqual(result_doc["paths"]["adapterRuns"], [])
        block_calls = [
            args for name, args in self.env.kanban.tool_calls if name == "kanban_block"
        ]
        self.assertTrue(block_calls)
        self.assertIn("precondition failure: workspace_mismatch", str(block_calls[-1].get("reason")))


class ReconcileResetFailuresTests(unittest.TestCase):
    """Operator two-step repair (t_bf68d977 second blockage)."""

    def setUp(self) -> None:
        self.env = SmokeEnv()
        self.verification = self.env.root / "verification.json"
        self.verification.write_text(json.dumps(_verification_document()), encoding="utf-8")
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

    def test_reset_failures_clears_counts_and_active_job_then_recovers(self) -> None:
        self.env.set_script(
            {
                "direct_implement:1:0": {"status": "failed", "sessionId": "sess_direct_1"},
                "direct_implement:1:1": {"status": "failed", "sessionId": "sess_direct_1"},
                "direct_implement:2:0": {"status": "completed"},
            }
        )
        created = self.env.enqueue(flow="direct", verification=str(self.verification))
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        blocked = self.env.advance_until(task_id=task_id, statuses={"blocked"}, limit=12)
        self.assertEqual(blocked["workflowStatus"], "blocked")
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["runFailureCounts"], {"direct_implement": 2})
        self.assertIsNotNone(manifest["activeJobId"])

        reset_args = self.parser.parse_args(
            ["reconcile", "--board", "project-board", task_id, "--reset-failures"]
        )
        rc = handle_autodev(reset_args, config_loader=self._loader, run_command=self.env.kanban.run_argv)
        self.assertEqual(rc, 0)

        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["runFailureCounts"], {})
        self.assertIsNone(manifest["activeJobId"])

        # Unblock, reclaim, and finish on a fresh business attempt without
        # any "job document identity conflict".
        self.env.kanban.run_argv(
            ["hermes", "kanban", "--board", "project-board", "unblock", task_id]
        )
        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"completed"}, limit=12)
        self.assertEqual(result["workflowStatus"], "completed")
        rows = self.env.store.list_jobs("project-board", task_id)
        self.assertEqual(
            [(row["business_attempt"], row["transport_retry"]) for row in rows],
            [(1, 0), (1, 1), (2, 0)],
        )
        self.assertEqual(len({row["job_id"] for row in rows}), 3)
        self.assertEqual(len({row["run_dir"] for row in rows}), 3)


if __name__ == "__main__":
    unittest.main()
