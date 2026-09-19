"""Commit-before-complete: the controller commits candidate changes at completion.

Requirement (dotfile t_fdef1a52):

1. direct flow: verification green -> exactly one commit before complete,
   message from the card title, HEAD advances.
2. empty diff -> no commit, the card still completes normally.
3. commit failure (hook error) -> the card blocks, never completes, the
   candidate stays uncommitted in the tree; after repair + unblock the
   completion retries the commit.
4. full flow: no commit before product acceptance passes; a rejected
   acceptance keeps reworking the uncommitted tree; commit then complete
   once acceptance passes.

The Job contract is unchanged: agents never move HEAD; only the controller
commits, immediately before the completed lifecycle is applied.
"""

from __future__ import annotations

import json
import stat
import subprocess
import unittest

from helpers import SmokeEnv, git
from plugin_imports import import_plugin

_git_commit = import_plugin("controller.git_commit")

CandidateCommitError = _git_commit.CandidateCommitError
commit_candidate = _git_commit.commit_candidate
replay_completion_at_head = _git_commit.replay_completion_at_head


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


def _install_failing_pre_commit_hook(repo) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)


def _remove_pre_commit_hook(repo) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    if hook.exists():
        hook.unlink()


def _commit_count(repo, since: str) -> int:
    return int(git(repo, "rev-list", "--count", f"{since}..HEAD"))


def _porcelain(repo) -> list[str]:
    """Raw `git status --porcelain` lines (helpers.git strips the leading XY space)."""
    completed = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1"],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.splitlines()


class DirectFlowCommitTests(unittest.TestCase):
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

    def test_verification_green_commits_candidate_before_complete(self) -> None:
        title = "Direct   commit\n card"
        created = self._enqueue_direct(title=title)
        task_id = created["task_id"]
        baseline_head = git(self.env.repo, "rev-parse", "HEAD")

        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"completed"})

        self.assertEqual(result["workflowStatus"], "completed")
        self.assertTrue(any(name == "kanban_complete" for name, _ in self.env.kanban.tool_calls))
        self.assertEqual(self.env.kanban.cards[task_id]["status"], "done")
        # Exactly one commit, message from the (whitespace-collapsed) title,
        # author/committer from the repository's git config, tree left clean.
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 1)
        self.assertEqual(git(self.env.repo, "log", "-1", "--format=%s"), "Direct commit card")
        self.assertEqual(git(self.env.repo, "log", "-1", "--format=%an"), "Dev")
        self.assertEqual(git(self.env.repo, "log", "-1", "--format=%ae"), "dev@example.com")
        self.assertEqual(git(self.env.repo, "status", "--porcelain=v1"), "")
        manifest = self.env.store.get_manifest("project-board", task_id)
        marker = manifest["completionCommit"]
        self.assertEqual(marker["head"], git(self.env.repo, "rev-parse", "HEAD"))
        self.assertEqual(marker["message"], "Direct commit card")
        self.assertFalse(marker["skipped"])

    def test_empty_diff_skips_commit_and_completes(self) -> None:
        self.env.set_script(
            {"direct_implement:1:0": {"status": "completed", "checks": "passed", "dirty": False}}
        )
        created = self._enqueue_direct()
        task_id = created["task_id"]
        baseline_head = git(self.env.repo, "rev-parse", "HEAD")

        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"completed"})

        self.assertEqual(result["workflowStatus"], "completed")
        self.assertTrue(any(name == "kanban_complete" for name, _ in self.env.kanban.tool_calls))
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 0)
        self.assertEqual(git(self.env.repo, "status", "--porcelain=v1"), "")
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertTrue(manifest["completionCommit"]["skipped"])
        self.assertEqual(manifest["completionCommit"]["head"], baseline_head)

    def test_commit_failure_blocks_keeps_candidate_then_retries_after_repair(self) -> None:
        _install_failing_pre_commit_hook(self.env.repo)
        created = self._enqueue_direct(title="Hook blocked card")
        task_id = created["task_id"]
        baseline_head = git(self.env.repo, "rev-parse", "HEAD")

        self.env.kanban.claim_ready(task_id)
        blocked = self.env.advance_until(task_id=task_id, statuses={"blocked"})

        self.assertEqual(blocked["workflowStatus"], "blocked")
        self.assertEqual(self.env.kanban.cards[task_id]["status"], "blocked")
        self.assertEqual(self.env.kanban.cards[task_id]["block_kind"], "commit_failed")
        self.assertFalse(any(name == "kanban_complete" for name, _ in self.env.kanban.tool_calls))
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 0)
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["workflowStatus"], "blocked")
        self.assertEqual(manifest["resumeStatus"], "verifying")
        self.assertIsNone(manifest.get("completionCommit"))
        # The candidate is still in the tree, unstaged (the failed attempt
        # reset the index), ready for the retry.
        self.assertTrue((self.env.repo / "src" / "app.txt").is_file())
        self.assertEqual(_porcelain(self.env.repo), [" M src/app.txt"])

        # Operator repairs the hook cause and unblocks; the resumed workflow
        # retries the completion (and the commit) without a new Job.
        _remove_pre_commit_hook(self.env.repo)
        self.env.kanban.run_argv(
            ["hermes", "kanban", "--board", "project-board", "unblock", task_id]
        )
        self.env.kanban.claim_ready(task_id)
        done = self.env.advance_until(task_id=task_id, statuses={"completed"})

        self.assertEqual(done["workflowStatus"], "completed")
        self.assertTrue(any(name == "kanban_complete" for name, _ in self.env.kanban.tool_calls))
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 1)
        self.assertEqual(git(self.env.repo, "log", "-1", "--format=%s"), "Hook blocked card")
        self.assertEqual(git(self.env.repo, "status", "--porcelain=v1"), "")
        rows = [
            row
            for row in self.env.store.list_jobs("project-board", task_id)
            if row["stage"] == "direct_implement"
        ]
        self.assertEqual(len(rows), 1)


class FullFlowCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = SmokeEnv()

    def tearDown(self) -> None:
        self.env.close()

    def _to_acceptance(self, title: str) -> str:
        created = self.env.enqueue(title=title)
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        self.env.kanban.claim_review(task_id, run_id="2")
        self.env.advance_until(task_id=task_id, run_id="2", outcomes={"acceptance_required"})
        return task_id

    def test_commit_happens_only_after_acceptance_passes(self) -> None:
        task_id = self._to_acceptance("Full flow card")
        baseline_head = git(self.env.repo, "rev-parse", "HEAD")
        # Verification and execute review passed, acceptance is pending:
        # the candidate must still be uncommitted in the tree.
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 0)
        self.assertIn("M", git(self.env.repo, "status", "--porcelain=v1"))
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["workflowStatus"], "product_acceptance")
        self.assertIsNone(manifest.get("completionCommit"))

        accepted = self.env.accept(task_id)

        self.assertEqual(accepted["workflowStatus"], "completed")
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 1)
        self.assertEqual(git(self.env.repo, "log", "-1", "--format=%s"), "Full flow card")
        self.assertEqual(git(self.env.repo, "log", "-1", "--format=%an"), "Dev")
        self.assertEqual(git(self.env.repo, "status", "--porcelain=v1"), "")
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(
            manifest["completionCommit"]["head"], git(self.env.repo, "rev-parse", "HEAD")
        )
        self.assertFalse(manifest["completionCommit"]["skipped"])

    def test_commit_failure_at_acceptance_blocks_and_can_retry_after_repair(self) -> None:
        _install_failing_pre_commit_hook(self.env.repo)
        task_id = self._to_acceptance("Hook at acceptance")
        baseline_head = git(self.env.repo, "rev-parse", "HEAD")

        blocked = self.env.accept(task_id)

        self.assertEqual(blocked["workflowStatus"], "blocked")
        self.assertEqual(blocked["outcome"], "blocked")
        self.assertIn("completion commit failed", blocked["commitFailure"])
        self.assertEqual(self.env.kanban.cards[task_id]["status"], "blocked")
        self.assertEqual(self.env.kanban.cards[task_id]["block_kind"], "commit_failed")
        self.assertFalse(any(name == "kanban_complete" for name, _ in self.env.kanban.tool_calls))
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 0)
        self.assertTrue(any(line.startswith(" M ") for line in _porcelain(self.env.repo)))
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["workflowStatus"], "blocked")
        self.assertEqual(manifest["resumeStatus"], "product_acceptance")
        self.assertIsNone(manifest.get("completionCommit"))
        self.assertFalse(
            (self.env.state_root / "boards" / "project-board" / task_id / "acceptance").exists()
        )

        # Repair + unblock: the worker resubmits acceptance, the commit
        # succeeds, and only then is the passed artifact recorded.
        _remove_pre_commit_hook(self.env.repo)
        self.env.kanban.run_argv(
            ["hermes", "kanban", "--board", "project-board", "unblock", task_id]
        )
        self.env.kanban.claim_review(task_id, run_id="9")
        resumed = self.env.controller().advance(
            board="project-board", task_id=task_id, run_id="9"
        )
        self.assertEqual(resumed["workflowStatus"], "product_acceptance")
        self.assertEqual(resumed["outcome"], "acceptance_required")
        passed = self.env.accept(task_id)

        self.assertEqual(passed["workflowStatus"], "completed")
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 1)
        self.assertEqual(git(self.env.repo, "log", "-1", "--format=%s"), "Hook at acceptance")
        self.assertEqual(git(self.env.repo, "status", "--porcelain=v1"), "")

    def test_rejected_acceptance_reworks_uncommitted_tree_then_commits_on_pass(self) -> None:
        task_id = self._to_acceptance("Rework stays uncommitted")
        baseline_head = git(self.env.repo, "rev-parse", "HEAD")

        rejected = self.env.accept(
            task_id,
            verdict="failed",
            summary="Checkout 500s",
            scenarios=[
                {"name": "checkout", "status": "failed", "evidence": [str(self.env.evidence)]}
            ],
            findings=[{"severity": "blocking", "problem": "500"}],
        )

        self.assertEqual(rejected["workflowStatus"], "implement_rework")
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 0)
        self.assertTrue(any(line.startswith(" M ") for line in _porcelain(self.env.repo)))
        self.assertIsNone(
            self.env.store.get_manifest("project-board", task_id).get("completionCommit")
        )

        # Rework continues on the uncommitted tree; the next acceptance pass
        # commits and completes.
        self.env.kanban.claim_ready(task_id, run_id="3")
        self.env.advance_until(task_id=task_id, run_id="3", statuses={"review_requested"})
        self.env.kanban.claim_review(task_id, run_id="4")
        self.env.advance_until(task_id=task_id, run_id="4", outcomes={"acceptance_required"})
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 0)
        passed = self.env.accept(task_id)

        self.assertEqual(passed["workflowStatus"], "completed")
        self.assertEqual(_commit_count(self.env.repo, baseline_head), 1)
        self.assertEqual(git(self.env.repo, "log", "-1", "--format=%s"), "Rework stays uncommitted")
        self.assertEqual(git(self.env.repo, "status", "--porcelain=v1"), "")


class CommitCandidateUnitTests(unittest.TestCase):
    """Direct unit coverage for the controller-owned commit helper."""

    def setUp(self) -> None:
        self.env = SmokeEnv()
        self.repo = self.env.repo
        self.baseline_head = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.env.close()

    def _dirty(self) -> None:
        (self.repo / "src" / "app.txt").write_text("candidate change\n", encoding="utf-8")
        (self.repo / "notes.txt").write_text("untracked note\n", encoding="utf-8")

    def _commit(self, message: str = "Unit card", expected_head: str | None = None):
        return commit_candidate(
            str(self.repo),
            message=message,
            expected_branch="main",
            expected_head=expected_head or self.baseline_head,
            declared_repo=str(self.repo),
        )

    def test_commits_tracked_and_untracked_candidate(self) -> None:
        self._dirty()
        result = self._commit()
        self.assertFalse(result.skipped)
        self.assertNotEqual(result.head, self.baseline_head)
        self.assertEqual(git(self.repo, "status", "--porcelain=v1"), "")
        self.assertEqual(_commit_count(self.repo, self.baseline_head), 1)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "Unit card")
        self.assertIn("untracked note", git(self.repo, "show", "HEAD:notes.txt"))

    def test_clean_tree_is_skipped(self) -> None:
        result = self._commit()
        self.assertTrue(result.skipped)
        self.assertEqual(result.head, self.baseline_head)
        self.assertEqual(_commit_count(self.repo, self.baseline_head), 0)

    def test_second_call_replays_the_same_commit_without_a_new_one(self) -> None:
        self._dirty()
        first = self._commit()
        second = self._commit(expected_head=self.baseline_head)
        self.assertTrue(second.replayed)
        self.assertEqual(second.head, first.head)
        self.assertEqual(_commit_count(self.repo, self.baseline_head), 1)
        self.assertEqual(
            replay_completion_at_head(
                str(self.repo),
                expected_branch="main",
                expected_head=self.baseline_head,
                message="Unit card",
                declared_repo=str(self.repo),
            ),
            first.head,
        )

    def test_foreign_head_advance_is_rejected(self) -> None:
        self._dirty()
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "operator commit")
        with self.assertRaises(CandidateCommitError):
            self._commit()

    def test_hook_failure_raises_and_leaves_the_tree_unstaged(self) -> None:
        _install_failing_pre_commit_hook(self.repo)
        self._dirty()
        with self.assertRaises(CandidateCommitError):
            self._commit()
        self.assertEqual(_commit_count(self.repo, self.baseline_head), 0)
        self.assertEqual(_porcelain(self.repo), [" M src/app.txt", "?? notes.txt"])

    def test_empty_message_is_rejected(self) -> None:
        with self.assertRaises(CandidateCommitError):
            self._commit(message="   ")


if __name__ == "__main__":
    unittest.main()
