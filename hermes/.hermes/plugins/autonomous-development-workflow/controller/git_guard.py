"""Read-only Git baseline and candidate fingerprint guards."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .protocol import require_absolute_path
from .types import CandidateFingerprint, GitBaseline, WorkflowProtocolError

_MUTATING = frozenset("stash reset checkout clean revert commit push switch restore merge rebase".split())


def capture_git_baseline(
    repo: str,
    *,
    expected_branch: str,
    expected_head: str | None = None,
    declared_repo: str | None = None,
    require_clean: bool = True,
) -> GitBaseline:
    real = _resolved_repo(repo, declared_repo=declared_repo)
    branch = _git(real, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(real, "rev-parse", "HEAD")
    porcelain = _git(real, "status", "--porcelain=v1", "--untracked-files=all")
    clean = porcelain == ""
    if branch != expected_branch:
        raise WorkflowProtocolError(f"branch {branch!r} is not {expected_branch!r}")
    if expected_head is not None and head != expected_head:
        raise WorkflowProtocolError("HEAD does not match the expected baseline")
    if require_clean and not clean:
        raise WorkflowProtocolError("working tree must be clean")
    return GitBaseline(repo_root=real, branch=branch, head=head, clean=clean)


def assert_planning_baseline(repo: str, baseline: GitBaseline) -> GitBaseline:
    return capture_git_baseline(
        repo,
        expected_branch=baseline.branch,
        expected_head=baseline.head,
        declared_repo=baseline.repo_root,
        require_clean=True,
    )


def assert_post_implement_baseline(repo: str, baseline: GitBaseline) -> GitBaseline:
    current = capture_git_baseline(
        repo,
        expected_branch=baseline.branch,
        expected_head=baseline.head,
        declared_repo=baseline.repo_root,
        require_clean=False,
    )
    if current.branch != baseline.branch or current.head != baseline.head:
        raise WorkflowProtocolError("post-implement branch/HEAD must equal the baseline")
    return current


def capture_candidate_fingerprint(repo: str, *, declared_repo: str | None = None) -> CandidateFingerprint:
    real = _resolved_repo(repo, declared_repo=declared_repo)
    branch = _git(real, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(real, "rev-parse", "HEAD")
    porcelain = _git(real, "status", "--porcelain=v1", "--untracked-files=all")
    worktree_diff = _git(real, "diff", "--binary", "HEAD")
    index_diff = _git(real, "diff", "--binary", "--cached")
    hashes = tuple(
        (path, _hash_path(Path(real) / path))
        for path in _paths_from_porcelain(porcelain)
    )
    return CandidateFingerprint(
        branch=branch,
        head=head,
        porcelain_sha256=_sha(porcelain.encode("utf-8")),
        diff_sha256=_sha((worktree_diff + "\0" + index_diff).encode("utf-8")),
        file_hashes=hashes,
    )


def assert_fingerprint_matches(
    repo: str, expected: CandidateFingerprint, *, declared_repo: str | None = None
) -> CandidateFingerprint:
    actual = capture_candidate_fingerprint(repo, declared_repo=declared_repo)
    if actual != expected:
        raise WorkflowProtocolError("candidate fingerprint drift")
    return actual


def _resolved_repo(repo: str, *, declared_repo: str | None) -> str:
    real = str(Path(require_absolute_path(repo, "repo")).resolve())
    declared = str(Path(require_absolute_path(declared_repo or repo, "declared repo")).resolve())
    if real != declared:
        raise WorkflowProtocolError("repo realpath must match the declared repository")
    if not Path(real).is_dir():
        raise WorkflowProtocolError("repo does not exist")
    toplevel = str(Path(_git(real, "rev-parse", "--show-toplevel")).resolve())
    if toplevel != declared:
        raise WorkflowProtocolError("repo path must be the repository root")
    return real


def _git(repo: str, *args: str) -> str:
    command = next((item for item in args if not item.startswith("-")), "")
    if command in _MUTATING:
        raise WorkflowProtocolError("mutating git commands are not allowed")
    argv = ["git", "-C", repo, *args]
    completed = subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise WorkflowProtocolError(completed.stderr.strip() or completed.stdout.strip() or "git failed")
    return completed.stdout.rstrip("\n")


def _paths_from_porcelain(porcelain: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in porcelain.splitlines():
        if not line:
            continue
        body = line[3:] if len(line) >= 3 else line
        if " -> " in body:
            left, right = body.split(" -> ", 1)
            paths.extend((left, right))
        else:
            paths.append(body)
    return tuple(sorted(set(paths)))


def _hash_path(path: Path) -> str:
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if path.is_symlink() or path.exists():
        return _sha(str(path.stat().st_mode).encode("utf-8"))
    return _sha(b"")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
