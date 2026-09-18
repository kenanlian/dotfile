"""Kanban lifecycle saga: pendingLifecycle fencing, native tools, and read-back."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from .protocol import canonical_json
from .types import WorkflowProtocolError, WorkflowStatus

DispatchFn = Callable[..., str]

LIFECYCLE_TOOLS: Mapping[str, str] = {
    WorkflowStatus.REVIEW_REQUESTED.value: "kanban_request_review",
    WorkflowStatus.IMPLEMENT_REWORK.value: "kanban_request_changes",
    WorkflowStatus.BLOCKED.value: "kanban_block",
    WorkflowStatus.COMPLETED.value: "kanban_complete",
    "heartbeat": "kanban_heartbeat",
}

KANBAN_TARGET_STATUS: Mapping[str, str] = {
    WorkflowStatus.REVIEW_REQUESTED.value: "review",
    WorkflowStatus.IMPLEMENT_REWORK.value: "todo",
    WorkflowStatus.BLOCKED.value: "blocked",
    WorkflowStatus.COMPLETED.value: "done",
}

DEFAULT_LIFECYCLE_ARGS: Mapping[str, Mapping[str, str]] = {
    "kanban_request_review": {"summary": "Implementation verification passed; requesting review."},
    "kanban_request_changes": {"reason": "Workflow requested implementer rework."},
    "kanban_block": {"reason": "Autonomous workflow cannot continue."},
    "kanban_complete": {"summary": "Product acceptance passed."},
    "kanban_heartbeat": {"note": "autodev harness still running"},
}


def lifecycle_tool_for(target_status: str) -> str:
    tool = LIFECYCLE_TOOLS.get(target_status)
    if not tool:
        raise WorkflowProtocolError(f"no Kanban lifecycle tool for {target_status}")
    return tool


def make_pending_lifecycle(
    *,
    target_status: str,
    run_id: str,
    workflow_revision: int,
    args: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not run_id:
        raise WorkflowProtocolError("pendingLifecycle requires the current Kanban run id")
    tool = lifecycle_tool_for(target_status)
    payload_args = dict(DEFAULT_LIFECYCLE_ARGS.get(tool, {}))
    if args:
        payload_args.update(args)
    digest = hashlib.sha256(canonical_json(payload_args).encode("utf-8")).hexdigest()
    return {
        "tool": tool,
        "targetStatus": target_status,
        "kanbanStatus": KANBAN_TARGET_STATUS[target_status],
        "runId": str(run_id),
        "workflowRevision": workflow_revision,
        "args": payload_args,
        "argsSha256": digest,
        "applied": False,
    }


def assert_pending_run(pending: Mapping[str, Any], *, current_run_id: str) -> None:
    bound = str(pending.get("runId") or "")
    if not bound or bound != str(current_run_id):
        raise WorkflowProtocolError(
            f"pendingLifecycle is bound to run {bound!r}, not current run {current_run_id!r}"
        )


def kanban_status_of(shown: Mapping[str, Any]) -> str | None:
    task = shown.get("task") if isinstance(shown.get("task"), Mapping) else shown
    if not isinstance(task, Mapping):
        return None
    status = task.get("status")
    return str(status) if status is not None else None


def lifecycle_already_applied(shown: Mapping[str, Any], pending: Mapping[str, Any]) -> bool:
    return kanban_status_of(shown) == pending.get("kanbanStatus")


def claimed_from_review(shown: Mapping[str, Any], run_id: str) -> bool:
    """True when the current run's latest ``claimed`` event carries
    ``source_status == "review"`` (i.e. the kernel will accept
    ``kanban_request_changes`` from it)."""
    events = shown.get("events")
    if not isinstance(events, list):
        return False
    latest: Mapping[str, Any] | None = None
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if event.get("kind") != "claimed":
            continue
        if str(event.get("run_id")) != str(run_id):
            continue
        latest = event
    if latest is None:
        return False
    payload = latest.get("payload")
    return isinstance(payload, Mapping) and payload.get("source_status") == "review"


def is_in_run_implement_rework(
    pending: Mapping[str, Any], shown: Mapping[str, Any], *, current_run_id: str
) -> bool:
    """kanban_request_changes only exists for review-claimed runs. When the
    workflow itself (verify stage) requests implementer rework, the active
    run was claimed from a non-review lane, so the kernel has no transition
    to apply — and none is needed: the implement_rework lane set already
    accepts ``running``, which is where the task sits."""
    if pending.get("tool") != "kanban_request_changes":
        return False
    if pending.get("targetStatus") != WorkflowStatus.IMPLEMENT_REWORK.value:
        return False
    if kanban_status_of(shown) != "running":
        return False
    return not claimed_from_review(shown, current_run_id)


def parse_dispatch_json(raw: str, *, what: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkflowProtocolError(f"{what} did not return JSON") from exc
    if not isinstance(payload, dict):
        raise WorkflowProtocolError(f"{what} JSON must be an object")
    if payload.get("error"):
        raise WorkflowProtocolError(str(payload["error"]))
    return payload


def show_task(dispatch: DispatchFn, *, task_id: str, board: str | None) -> dict[str, Any]:
    args: dict[str, Any] = {"task_id": task_id}
    if board:
        args["board"] = board
    return parse_dispatch_json(dispatch("kanban_show", args), what="kanban_show")


def apply_pending_lifecycle(
    pending: Mapping[str, Any],
    *,
    current_run_id: str,
    task_id: str,
    board: str | None,
    dispatch: DispatchFn,
) -> dict[str, Any]:
    assert_pending_run(pending, current_run_id=current_run_id)
    shown = show_task(dispatch, task_id=task_id, board=board)
    if lifecycle_already_applied(shown, pending):
        return {"applied": True, "dispatched": False, "shown": shown}
    if is_in_run_implement_rework(pending, shown, current_run_id=current_run_id):
        return {
            "applied": True,
            "dispatched": False,
            "shown": shown,
            "skipped": "in_run_implement_rework",
        }
    args = dict(pending.get("args") or {})
    args.setdefault("task_id", task_id)
    parse_dispatch_json(dispatch(str(pending["tool"]), args), what=str(pending["tool"]))
    shown = show_task(dispatch, task_id=task_id, board=board)
    if not lifecycle_already_applied(shown, pending):
        raise WorkflowProtocolError(
            f"kanban read-back status {kanban_status_of(shown)!r} is not {pending.get('kanbanStatus')!r}"
        )
    return {"applied": True, "dispatched": True, "shown": shown}
