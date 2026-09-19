"""Commit-before-complete: the controller commits candidate changes at completion.

The coding agent and the dispatched Worker never move HEAD; the Job contract
is unchanged. Immediately before a card's ``completed`` lifecycle is written
and dispatched, the controller itself stages and commits the candidate
changes left in the working tree, so the next serial card starts from a HEAD
that already contains this card's output.

Timing by flow:

- direct flow: after all verification checks passed, before completing.
- full flow: only after product acceptance passed (a rejected acceptance
  keeps reworking on the uncommitted tree).

Behavior:

- Commit message is derived from the card title; author/committer come from
  the repository's git config.
- Empty diff (the card produced no changes): skip the commit, complete
  normally — not a failure.
- Commit failure (hook error, git error, unexpected HEAD advance): the card
  blocks for operator triage with ``kind=commit_failed``; it is never
  completed uncommitted and the failure is never silently skipped.
- Push remains out of scope (operator action or a future opt-in).
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from .git_commit import CandidateCommitError, commit_candidate
from .lifecycle import make_pending_lifecycle
from .store import WorkflowStore
from .types import WorkflowStatus

COMMIT_FAILURE_KIND = "commit_failed"


def completion_commit_message(title: str) -> str:
    """Collapse the card title onto one line; the subject is the title."""
    return " ".join(str(title).split())


def card_title(shown: Mapping[str, Any]) -> str:
    task = shown.get("task") if isinstance(shown.get("task"), Mapping) else shown
    if isinstance(task, Mapping):
        return str(task.get("title") or "")
    return ""


def _completion_failure(reason: str) -> dict[str, str]:
    return {"kind": COMMIT_FAILURE_KIND, "reason": reason}


def ensure_completion_commit(
    store: WorkflowStore,
    manifest: Mapping[str, Any],
    *,
    title: str,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Ensure the completion commit exists before a completed lifecycle is written.

    Returns ``(updated_manifest, None)`` on success — the manifest gains a
    durable ``completionCommit`` receipt in the same CAS that observed the
    commit — or ``(manifest, failure)`` when the card must block instead.

    Idempotent: a manifest that already carries a ``completionCommit`` receipt
    (or a repository that already holds exactly the completion commit, e.g.
    after a crash between commit and receipt) is accepted without committing
    again.
    """
    marker = manifest.get("completionCommit")
    if isinstance(marker, Mapping) and marker.get("head"):
        return dict(manifest), None
    baseline = manifest.get("baseline") if isinstance(manifest.get("baseline"), Mapping) else {}
    expected_branch = str(baseline.get("branch") or "")
    expected_head = str(baseline.get("head") or "")
    message = completion_commit_message(title)
    if not expected_branch or not expected_head:
        return dict(manifest), _completion_failure(
            "completion commit is unavailable: the manifest baseline is missing"
        )
    if not message:
        return dict(manifest), _completion_failure(
            "completion commit is unavailable: the card title is missing"
        )
    try:
        commit = commit_candidate(
            str(manifest["repoRoot"]),
            message=message,
            expected_branch=expected_branch,
            expected_head=expected_head,
            declared_repo=str(manifest["repoRoot"]),
        )
    except CandidateCommitError as exc:
        return dict(manifest), _completion_failure(f"completion commit failed: {exc}")
    updated = dict(manifest)
    updated["revision"] = int(manifest["revision"]) + 1
    updated["completionCommit"] = {
        "head": commit.head,
        "message": commit.message,
        "skipped": commit.skipped,
        "replayed": commit.replayed,
        "committedAt": int(time.time()),
    }
    store.cas_update_manifest(
        manifest["board"],
        manifest["taskId"],
        expected_revision=int(manifest["revision"]),
        manifest=updated,
    )
    return updated, None


def block_on_commit_failure(
    store: WorkflowStore,
    manifest: Mapping[str, Any],
    *,
    run_id: str,
    failure: Mapping[str, str],
) -> dict[str, Any]:
    """Block the card for operator triage instead of completing uncommitted.

    Must be called while the manifest still holds its pre-completion status
    (the store refuses ``completed -> blocked`` transitions), so the commit is
    ensured before the completed lifecycle is ever written. ``resumeStatus``
    keeps the pre-completion stage so an unblock retries the completion
    (including the commit) instead of restarting the stage.
    """
    resume_status = str(manifest.get("workflowStatus") or "")
    pending = make_pending_lifecycle(
        target_status=WorkflowStatus.BLOCKED.value,
        run_id=str(run_id),
        workflow_revision=int(manifest["revision"]) + 1,
        args={"reason": failure["reason"], "kind": COMMIT_FAILURE_KIND},
    )
    updated = dict(manifest)
    updated["revision"] = int(manifest["revision"]) + 1
    updated["workflowStatus"] = WorkflowStatus.BLOCKED.value
    updated["pendingLifecycle"] = pending
    if resume_status and resume_status not in {
        WorkflowStatus.BLOCKED.value,
        WorkflowStatus.COMPLETED.value,
    }:
        updated["resumeStatus"] = resume_status
    store.cas_update_manifest(
        manifest["board"],
        manifest["taskId"],
        expected_revision=int(manifest["revision"]),
        manifest=updated,
    )
    return updated


def finalize_applied_lifecycle(
    store: WorkflowStore,
    manifest: Mapping[str, Any],
    *,
    pending: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Clear an applied pendingLifecycle and record the saga receipt."""
    updated = dict(manifest)
    updated["revision"] = int(manifest["revision"]) + 1
    # Receipt for the saga close-out: once pendingLifecycle clears,
    # later observers can still tell "applied" from "stuck".
    updated["lastLifecycle"] = {
        "tool": pending["tool"],
        "targetStatus": pending["targetStatus"],
        "kanbanStatus": pending["kanbanStatus"],
        "dispatched": result["dispatched"],
        "appliedAt": int(time.time()),
        "workflowRevision": pending["workflowRevision"],
    }
    if result.get("skipped"):
        updated["lastLifecycle"]["skipped"] = str(result["skipped"])
    updated["pendingLifecycle"] = None
    store.cas_update_manifest(
        manifest["board"],
        manifest["taskId"],
        expected_revision=int(manifest["revision"]),
        manifest=updated,
    )
    return updated
