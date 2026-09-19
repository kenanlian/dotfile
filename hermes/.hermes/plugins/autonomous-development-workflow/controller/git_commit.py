"""Controller-owned completion commit (commit-before-complete).

Sibling of :mod:`controller.git_guard`, which stays the strictly read-only,
agent-facing guard module (enforced at source level by its tests). This
module is the controller's deliberate write path: immediately before a card
completes, the controller — never a coding agent and never the dispatched
Worker — stages and commits the candidate changes left in the working tree,
so the next serial card starts from a HEAD that already contains this card's
output and the operator's mid-flight `git add` can no longer mix cards.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .git_guard import _git, _resolved_repo
from .types import WorkflowProtocolError


@dataclass(frozen=True)
class CompletionCommit:
    """Outcome of the controller-owned completion commit.

    ``skipped`` means the working tree was already clean at the baseline HEAD
    (the card produced no candidate changes), so no commit was created.
    ``replayed`` means an earlier attempt already created exactly this commit
    (crash-recovery idempotency) and it was accepted as-is.
    """

    head: str
    message: str
    skipped: bool
    replayed: bool = False


class CandidateCommitError(RuntimeError):
    """The completion commit could not be produced.

    The candidate must stay uncommitted in the working tree; the caller
    blocks the card for operator triage instead of completing it.
    """


def commit_candidate(
    repo: str,
    *,
    message: str,
    expected_branch: str,
    expected_head: str,
    declared_repo: str | None = None,
) -> CompletionCommit:
    """Stage and commit every candidate change in the working tree.

    Contract (autodev commit-before-complete):

    - Only runs when HEAD still equals the workflow baseline; agents must
      never have moved HEAD, and an unexpected HEAD advance is an error the
      operator must triage — except a replay of exactly this commit.
    - Empty diff (no candidate changes): skip the commit, report ``skipped``.
    - ``git add -A`` + ``git commit -m <message>``; author/committer come from
      the repository's own git config.
    - On any failure the index is unstaged again (best-effort ``git reset``)
      so the candidate tree is preserved byte-for-byte for a retry, and
      :class:`CandidateCommitError` is raised.
    """
    if not isinstance(message, str) or not message.strip():
        raise CandidateCommitError("commit message must be a non-empty string")
    try:
        real = _resolved_repo(repo, declared_repo=declared_repo)
        branch = _git(real, "rev-parse", "--abbrev-ref", "HEAD")
        head = _git(real, "rev-parse", "HEAD")
        porcelain = _git(real, "status", "--porcelain=v1", "--untracked-files=all")
    except WorkflowProtocolError as exc:
        raise CandidateCommitError(f"repository inspection failed: {exc}") from exc
    if branch != expected_branch:
        raise CandidateCommitError(f"branch {branch!r} is not the expected {expected_branch!r}")
    if head != expected_head:
        replayed = replay_completion_at_head(
            real,
            expected_branch=expected_branch,
            expected_head=expected_head,
            message=message,
            declared_repo=real,
        )
        if replayed is not None:
            return CompletionCommit(head=replayed, message=message, skipped=False, replayed=True)
        raise CandidateCommitError(
            "HEAD does not match the workflow baseline and no completion commit replay was found"
        )
    if porcelain == "":
        return CompletionCommit(head=head, message=message, skipped=True)
    code, _stdout, stderr = _run_git(real, "add", "-A")
    if code != 0:
        _unstage(real)
        raise CandidateCommitError(stderr.strip() or "git add failed")
    code, _stdout, stderr = _run_git(real, "commit", "-m", message)
    if code != 0:
        _unstage(real)
        raise CandidateCommitError(stderr.strip() or "git commit failed")
    new_head = _git(real, "rev-parse", "HEAD")
    if new_head == head:
        raise CandidateCommitError("git commit did not advance HEAD")
    return CompletionCommit(head=new_head, message=message, skipped=False)


def replay_completion_at_head(
    repo: str,
    *,
    expected_branch: str,
    expected_head: str,
    message: str,
    declared_repo: str | None = None,
) -> str | None:
    """HEAD when the repo already holds exactly the completion commit, else None.

    Recognizes the crash window between a successful completion commit and
    its Manifest receipt: exactly one commit ahead of the baseline, subject
    equal to the expected message, and a clean tree. Anything else (more
    commits, a foreign subject, a dirty tree) is None so the caller treats
    the HEAD advance as an anomaly.
    """
    try:
        real = _resolved_repo(repo, declared_repo=declared_repo)
        branch = _git(real, "rev-parse", "--abbrev-ref", "HEAD")
        if branch != expected_branch:
            return None
        head = _git(real, "rev-parse", "HEAD")
        count = _git(real, "rev-list", "--count", f"{expected_head}..{head}")
        subject = _git(real, "log", "-1", "--format=%s", head)
        porcelain = _git(real, "status", "--porcelain=v1", "--untracked-files=all")
    except WorkflowProtocolError:
        return None
    if count == "1" and subject == message and porcelain == "":
        return head
    return None


def is_clean_at_head(
    repo: str,
    *,
    expected_head: str,
    declared_repo: str | None = None,
) -> bool:
    """Best-effort check that the tree is clean at exactly ``expected_head``."""
    try:
        real = _resolved_repo(repo, declared_repo=declared_repo)
        head = _git(real, "rev-parse", "HEAD")
        porcelain = _git(real, "status", "--porcelain=v1", "--untracked-files=all")
    except WorkflowProtocolError:
        return False
    return head == expected_head and porcelain == ""


def _run_git(repo: str, *args: str) -> tuple[int, str, str]:
    """Run a git command the completion commit is allowed to use (incl. mutating)."""
    completed = subprocess.run(
        ["git", "-C", repo, *args],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _unstage(repo: str) -> None:
    """Best-effort mixed reset so a failed attempt leaves the pre-attempt tree."""
    try:
        _run_git(repo, "reset", "--mixed", "--quiet")
    except Exception:
        pass
