"""Git baseline, candidate fingerprint, and fail-closed drift detection."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugin_imports import import_plugin

_guard = import_plugin("controller.git_guard")
_types = import_plugin("controller.types")

CandidateFingerprint = _types.CandidateFingerprint
GitBaseline = _types.GitBaseline
WorkflowProtocolError = _types.WorkflowProtocolError
assert_fingerprint_matches = _guard.assert_fingerprint_matches
assert_planning_baseline = _guard.assert_planning_baseline
assert_post_implement_baseline = _guard.assert_post_implement_baseline
capture_candidate_fingerprint = _guard.capture_candidate_fingerprint
capture_git_baseline = _guard.capture_git_baseline


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        shell=False,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    _git(repo, "config", "core.filemode", "true")
    (repo / "tracked.txt").write_text("hello\n", encoding="utf-8")
    (repo / "keep.txt").write_text("keep\n", encoding="utf-8")
    (repo / "mode.sh").write_text("echo hi\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt", "keep.txt", "mode.sh")
    _git(repo, "commit", "-m", "init")
    return repo


class GitGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-git-")
        self.root = Path(self._tmp.name)
        self.repo = _init_repo(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _baseline(self, **overrides) -> GitBaseline:
        data = dict(
            repo_root=str(self.repo.resolve()),
            branch="main",
            head=_git(self.repo, "rev-parse", "HEAD"),
            clean=True,
        )
        data.update(overrides)
        return GitBaseline(**data)

    def test_source_only_allows_readonly_git_argv(self) -> None:
        source = Path(_guard.__file__).read_text(encoding="utf-8")
        self.assertIn("shell=False", source)
        self.assertNotIn("shell=True", source)
        for verb in ("stash", "reset", "checkout", "clean", "revert"):
            self.assertNotIn(f'"{verb}"', source)
            self.assertNotIn(f"'{verb}'", source)

    def test_git_invocations_are_argv_readonly(self) -> None:
        recorded: list[tuple[list[str], bool]] = []
        original = subprocess.run

        def wrapper(argv, *args, **kwargs):
            recorded.append((list(argv), bool(kwargs.get("shell", False))))
            return original(argv, *args, **kwargs)

        with patch.object(_guard.subprocess, "run", wrapper):
            capture_git_baseline(str(self.repo), expected_branch="main")
            capture_candidate_fingerprint(str(self.repo))
        self.assertTrue(recorded)
        forbidden = {"stash", "reset", "checkout", "clean", "revert", "commit", "push"}
        for argv, shell in recorded:
            self.assertFalse(shell)
            self.assertIsInstance(argv, list)
            self.assertEqual(argv[0], "git")
            commands = {item for item in argv if item in forbidden}
            self.assertEqual(commands, set())

    def test_planning_requires_declared_realpath_branch_head_and_clean(self) -> None:
        baseline = capture_git_baseline(str(self.repo), expected_branch="main")
        self.assertEqual(baseline.repo_root, str(self.repo.resolve()))
        self.assertEqual(baseline.branch, "main")
        self.assertTrue(baseline.clean)
        assert_planning_baseline(str(self.repo), baseline)

        alias = self.root / "alias"
        alias.symlink_to(self.repo)
        capture_git_baseline(str(alias), expected_branch="main", declared_repo=str(self.repo))

        with self.assertRaises(WorkflowProtocolError):
            capture_git_baseline(str(self.repo), expected_branch="dev")

        (self.repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(WorkflowProtocolError):
            assert_planning_baseline(str(self.repo), baseline)
        other = self.root / "other"
        other.mkdir()
        with self.assertRaises(WorkflowProtocolError):
            capture_git_baseline(str(other), expected_branch="main", declared_repo=str(self.repo))

    def test_post_implement_allows_dirty_but_requires_baseline_branch_and_head(self) -> None:
        baseline = capture_git_baseline(str(self.repo), expected_branch="main")
        (self.repo / "tracked.txt").write_text("implement\n", encoding="utf-8")
        assert_post_implement_baseline(str(self.repo), baseline)
        _git(self.repo, "add", "tracked.txt")
        _git(self.repo, "commit", "-m", "not allowed")
        with self.assertRaises(WorkflowProtocolError):
            assert_post_implement_baseline(str(self.repo), baseline)

    def test_fingerprint_covers_tracked_untracked_rename_delete_mode_and_index_only(self) -> None:
        clean = capture_candidate_fingerprint(str(self.repo))
        again = capture_candidate_fingerprint(str(self.repo))
        self.assertEqual(clean, again)

        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        tracked = capture_candidate_fingerprint(str(self.repo))
        self.assertNotEqual(tracked.porcelain_sha256, clean.porcelain_sha256)
        self.assertNotEqual(tracked.diff_sha256, clean.diff_sha256)
        self.assertNotEqual(tracked.file_hashes, clean.file_hashes)

        (self.repo / "tracked.txt").write_text("hello\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("new\n", encoding="utf-8")
        untracked = capture_candidate_fingerprint(str(self.repo))
        self.assertNotEqual(untracked, clean)
        (self.repo / "untracked.txt").unlink()

        _git(self.repo, "mv", "keep.txt", "renamed.txt")
        renamed = capture_candidate_fingerprint(str(self.repo))
        self.assertNotEqual(renamed, clean)
        _git(self.repo, "mv", "renamed.txt", "keep.txt")

        (self.repo / "mode.sh").unlink()
        deleted = capture_candidate_fingerprint(str(self.repo))
        self.assertNotEqual(deleted, clean)
        _git(self.repo, "checkout", "--", "mode.sh")

        mode_path = self.repo / "mode.sh"
        mode_path.chmod(mode_path.stat().st_mode | stat.S_IXUSR)
        mode_changed = capture_candidate_fingerprint(str(self.repo))
        self.assertNotEqual(mode_changed, clean)
        mode_path.chmod(mode_path.stat().st_mode & ~stat.S_IXUSR)

        original = (self.repo / "tracked.txt").read_text(encoding="utf-8")
        (self.repo / "tracked.txt").write_text("index-only\n", encoding="utf-8")
        _git(self.repo, "add", "tracked.txt")
        (self.repo / "tracked.txt").write_text(original, encoding="utf-8")
        index_only = capture_candidate_fingerprint(str(self.repo))
        self.assertNotEqual(index_only, clean)
        self.assertNotEqual(index_only.diff_sha256, clean.diff_sha256)

    def test_review_and_acceptance_fail_closed_on_drift(self) -> None:
        baseline = capture_git_baseline(str(self.repo), expected_branch="main")
        (self.repo / "tracked.txt").write_text("implementation\n", encoding="utf-8")
        assert_post_implement_baseline(str(self.repo), baseline)
        review = capture_candidate_fingerprint(str(self.repo))
        assert_fingerprint_matches(str(self.repo), review)
        (self.repo / "tracked.txt").write_text("drifted\n", encoding="utf-8")
        with self.assertRaises(WorkflowProtocolError):
            assert_fingerprint_matches(str(self.repo), review)
        with self.assertRaises(WorkflowProtocolError):
            assert_fingerprint_matches(str(self.repo), review)


if __name__ == "__main__":
    unittest.main()
