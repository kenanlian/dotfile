"""Typed product-acceptance coordinator. The plugin writes canonical evidence JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .git_guard import capture_candidate_fingerprint, fingerprint_digest
from .lifecycle import apply_pending_lifecycle, make_pending_lifecycle
from .policy import MAX_IMPLEMENT_REWORK
from .protocol import parse_acceptance, require_absolute_path, sha256_file_if_exists
from .store import WorkflowStore, canonical_dumps, sha256_file
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
    if manifest.get("workflowStatus") != WorkflowStatus.PRODUCT_ACCEPTANCE.value:
        raise WorkflowProtocolError("product acceptance is only available in product_acceptance")
    if not is_review_lane(shown, run_id):
        raise WorkflowProtocolError("product acceptance requires a review-lane Worker run")
    stored = manifest.get("candidateFingerprint")
    if not isinstance(stored, str) or not stored:
        raise WorkflowProtocolError("candidate fingerprint is missing; old acceptance cannot proceed")
    current = fingerprint_digest(
        capture_candidate_fingerprint(str(manifest["repoRoot"]), declared_repo=str(manifest["repoRoot"]))
    )
    if current != stored:
        raise WorkflowProtocolError("candidate fingerprint drift; old acceptance verdict is invalid")
    payload = dict(submission)
    payload["candidateFingerprint"] = current
    parsed = parse_acceptance(payload, expected_fingerprint=stored)
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
        fingerprint=current,
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
        cleared = dict(updated)
        cleared["revision"] = int(updated["revision"]) + 1
        cleared["pendingLifecycle"] = None
        store.cas_update_manifest(
            board, task_id, expected_revision=int(updated["revision"]), manifest=cleared
        )
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
