"""Typed product-acceptance coordinator. The plugin writes canonical evidence JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .completion import (
    block_on_commit_failure,
    card_title,
    completion_commit_message,
    ensure_completion_commit,
    finalize_applied_lifecycle,
)
from .git_commit import (
    is_clean_at_head,
    replay_completion_at_head,
)
from .git_guard import capture_candidate_fingerprint, fingerprint_digest
from .lifecycle import apply_pending_lifecycle, make_pending_lifecycle
from .policy import MAX_IMPLEMENT_REWORK
from .protocol import parse_acceptance, require_absolute_path, sha256_file_if_exists
from .store import WorkflowStore, canonical_dumps, sha256_file
from .templates import get_template
from .types import PluginConfig, WorkflowProtocolError, WorkflowStatus

DispatchFn = Callable[..., str]
ACCEPTANCE_SCHEMA = "autonomous-development.acceptance.v1"
ACCEPTANCE_KIND = "product-acceptance"


def is_review_lane(shown: Mapping[str, Any], run_id: str) -> bool:
    events = shown.get("events") if isinstance(shown.get("events"), list) else []
    for event in reversed(events):
        if not isinstance(event, Mapping):
            continue
        if event.get("kind") != "claimed":
            continue
        if str(event.get("run_id") or "") != str(run_id):
            continue
        payload = _event_payload(event.get("payload"))
        if payload.get("source_status") == "review":
            return True
    runs = shown.get("runs") if isinstance(shown.get("runs"), list) else []
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        if str(run.get("id") or "") != str(run_id):
            continue
        metadata = run.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("source_status") == "review":
            return True
    return False


def submit_typed_acceptance(
    *,
    store: WorkflowStore,
    config: PluginConfig,
    dispatch_tool: DispatchFn,
    board: str,
    task_id: str,
    run_id: str,
    shown: Mapping[str, Any],
    submission: Mapping[str, Any],
) -> dict[str, Any]:
    del config
    manifest = store.get_manifest(board, task_id)
    if manifest is None:
        raise WorkflowProtocolError("no workflow manifest is bound to this task")
    template = get_template(str(manifest.get("templateId") or ""))
    if not template.uses_product_acceptance:
        raise WorkflowProtocolError("product acceptance is not part of this workflow template")
    if manifest.get("workflowStatus") != WorkflowStatus.PRODUCT_ACCEPTANCE.value:
        raise WorkflowProtocolError("product acceptance is only available in product_acceptance")
    if not is_review_lane(shown, run_id):
        raise WorkflowProtocolError("product acceptance requires a review-lane Worker run")
    stored = manifest.get("candidateFingerprint")
    if not isinstance(stored, str) or not stored:
        raise WorkflowProtocolError("candidate fingerprint is missing; old acceptance cannot proceed")
    candidate = capture_candidate_fingerprint(
        str(manifest["repoRoot"]), declared_repo=str(manifest["repoRoot"])
    )
    current = fingerprint_digest(candidate)
    # Commit-before-complete: once the controller's completion commit exists
    # the live fingerprint legitimately differs from the accepted candidate
    # (the candidate now lives at HEAD). Heal that replay instead of failing.
    completion_committed = _completion_already_committed(manifest, shown)
    if current != stored and not completion_committed:
        raise WorkflowProtocolError("candidate fingerprint drift; old acceptance verdict is invalid")
    payload = dict(submission)
    # The verdict applies to the stored candidate fingerprint.
    payload["candidateFingerprint"] = stored
    parsed = parse_acceptance(payload, expected_fingerprint=stored)
    if completion_committed and parsed.verdict != "passed":
        raise WorkflowProtocolError(
            "completion commit already exists; only a passed acceptance can complete this card"
        )
    if parsed.verdict == "passed":
        # Acceptance passed -> controller commits the candidate -> complete.
        # On commit failure the card blocks (never completed uncommitted);
        # the passed artifact is recorded only once the commit succeeded.
        updated, failure = ensure_completion_commit(
            store, manifest, title=card_title(shown)
        )
        if failure is not None:
            blocked = block_on_commit_failure(
                store, manifest, run_id=run_id, failure=failure
            )
            applied_block = apply_pending_lifecycle(
                blocked["pendingLifecycle"],
                current_run_id=run_id,
                task_id=task_id,
                board=board,
                dispatch=dispatch_tool,
            )
            if applied_block.get("applied"):
                blocked = finalize_applied_lifecycle(
                    store, blocked, pending=blocked["pendingLifecycle"], result=applied_block
                )
            return {
                "ok": True,
                "workflowStatus": blocked.get("workflowStatus"),
                "revision": blocked.get("revision"),
                "stageAttempt": blocked.get("stageAttempt"),
                "activeJobId": blocked.get("activeJobId"),
                "nextAction": "noop",
                "inProgress": False,
                "pendingLifecycle": blocked.get("pendingLifecycle"),
                "lastLifecycle": blocked.get("lastLifecycle"),
                "outcome": "blocked",
                "commitFailure": failure["reason"],
            }
        manifest = updated
    evidence = _evidence_records(parsed.scenarios)
    target, pending_args, resume_status, implement_rework = _verdict_transition(
        parsed.verdict,
        summary=parsed.summary,
        question=parsed.question,
        implement_rework_count=int(manifest.get("implementReworkCount") or 0),
    )
    version = store.next_artifact_version(board, task_id, ACCEPTANCE_KIND)
    artifact_path = _write_acceptance_artifact(
        store,
        board=board,
        task_id=task_id,
        version=version,
        parsed=parsed,
        evidence=evidence,
        fingerprint=stored,
        run_id=run_id,
    )
    pending = make_pending_lifecycle(
        target_status=target.value,
        run_id=run_id,
        workflow_revision=int(manifest["revision"]) + 1,
        args=pending_args,
    )
    updated = dict(manifest)
    updated["revision"] = int(manifest["revision"]) + 1
    updated["workflowStatus"] = target.value
    updated["pendingLifecycle"] = pending
    updated["resumeStatus"] = resume_status
    if implement_rework:
        updated["implementReworkCount"] = int(manifest.get("implementReworkCount") or 0) + 1
    store.checkpoint(
        board=board,
        task_id=task_id,
        expected_revision=int(manifest["revision"]),
        manifest=updated,
        artifacts=[
            {
                "job_id": f"acceptance:{task_id}:v{version}",
                "kind": ACCEPTANCE_KIND,
                "version": version,
                "path": str(artifact_path),
                "sha256": sha256_file(artifact_path),
            }
        ],
    )
    applied = apply_pending_lifecycle(
        pending,
        current_run_id=run_id,
        task_id=task_id,
        board=board,
        dispatch=dispatch_tool,
    )
    if applied.get("applied"):
        cleared = finalize_applied_lifecycle(store, updated, pending=pending, result=applied)
        updated = cleared
        if target is WorkflowStatus.COMPLETED:
            lease = store.get_repo_lease(str(manifest["repoRoot"]))
            if lease and lease.get("released_at") is None:
                store.release_repo_lease(
                    str(manifest["repoRoot"]),
                    board=board,
                    task_id=task_id,
                    reason="completed",
                )
    return {
        "ok": True,
        "workflowStatus": updated["workflowStatus"],
        "revision": updated["revision"],
        "stageAttempt": updated.get("stageAttempt"),
        "activeJobId": updated.get("activeJobId"),
        "nextAction": "noop",
        "inProgress": False,
        "pendingLifecycle": updated.get("pendingLifecycle"),
        "outcome": "blocked" if target is WorkflowStatus.BLOCKED else "ok",
        "acceptanceArtifact": str(artifact_path),
    }


def _completion_already_committed(
    manifest: Mapping[str, Any], shown: Mapping[str, Any]
) -> bool:
    """True when the controller's completion commit already exists.

    Accepts either the durable ``completionCommit`` receipt with a clean tree
    at its HEAD, or (crash between commit and receipt) a repository holding
    exactly one commit beyond the baseline whose subject is the card title.
    """
    repo = str(manifest["repoRoot"])
    marker = manifest.get("completionCommit")
    if isinstance(marker, Mapping) and marker.get("head"):
        return is_clean_at_head(repo, expected_head=str(marker["head"]), declared_repo=repo)
    baseline = manifest.get("baseline") if isinstance(manifest.get("baseline"), Mapping) else {}
    expected_branch = str(baseline.get("branch") or "")
    expected_head = str(baseline.get("head") or "")
    if not expected_branch or not expected_head:
        return False
    message = completion_commit_message(card_title(shown))
    if not message:
        return False
    return (
        replay_completion_at_head(
            repo,
            expected_branch=expected_branch,
            expected_head=expected_head,
            message=message,
            declared_repo=repo,
        )
        is not None
    )


def _event_payload(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, Mapping) else {}
    return {}


def _evidence_records(scenarios) -> tuple[dict[str, str], ...]:
    records: list[dict[str, str]] = []
    for scenario in scenarios:
        for item in scenario.evidence:
            path = require_absolute_path(item, "scenario.evidence")
            digest = sha256_file_if_exists(path)
            records.append({"path": path, "sha256": digest})
    return tuple(records)


def _verdict_transition(
    verdict: str,
    *,
    summary: str,
    question: str | None,
    implement_rework_count: int,
) -> tuple[WorkflowStatus, dict[str, Any], str | None, bool]:
    if verdict == "passed":
        return WorkflowStatus.COMPLETED, {"summary": summary}, None, False
    if verdict == "failed":
        if implement_rework_count >= MAX_IMPLEMENT_REWORK:
            return (
                WorkflowStatus.BLOCKED,
                {"reason": summary, "kind": "capability"},
                WorkflowStatus.PRODUCT_ACCEPTANCE.value,
                False,
            )
        return (
            WorkflowStatus.IMPLEMENT_REWORK,
            {"reason": summary},
            None,
            True,
        )
    if verdict == "needs_human":
        return (
            WorkflowStatus.BLOCKED,
            {"reason": question or summary, "kind": "needs_input"},
            WorkflowStatus.PRODUCT_ACCEPTANCE.value,
            False,
        )
    return (
        WorkflowStatus.BLOCKED,
        {"reason": summary, "kind": "dependency"},
        WorkflowStatus.PRODUCT_ACCEPTANCE.value,
        False,
    )


def _write_acceptance_artifact(
    store: WorkflowStore,
    *,
    board: str,
    task_id: str,
    version: int,
    parsed,
    evidence: tuple[dict[str, str], ...],
    fingerprint: str,
    run_id: str,
) -> Path:
    directory = store.state_root / "boards" / board / task_id / "acceptance"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"product-acceptance-v{version}.json"
    if path.exists():
        raise WorkflowProtocolError(f"{path.name} already exists and is immutable")
    document = {
        "schema": ACCEPTANCE_SCHEMA,
        "kind": ACCEPTANCE_KIND,
        "version": version,
        "board": board,
        "taskId": task_id,
        "runId": str(run_id),
        "verdict": parsed.verdict,
        "summary": parsed.summary,
        "scenarios": [
            {"name": item.name, "status": item.status, "evidence": list(item.evidence)}
            for item in parsed.scenarios
        ],
        "findings": [dict(item.details) for item in parsed.findings],
        "question": parsed.question,
        "candidateFingerprint": fingerprint,
        "evidence": list(evidence),
        "canonical": True,
    }
    text = canonical_dumps(document)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path
