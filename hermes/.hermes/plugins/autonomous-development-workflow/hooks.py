"""Runtime guards. Fail closed for Manifest-bound autonomous tasks; no-op otherwise."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any, Mapping

from .config import load_plugin_config
from .controller.store import WorkflowStore
from .controller.types import WorkflowProtocolError

LIFECYCLE_TOOLS = frozenset(
    {
        "kanban_complete",
        "kanban_request_review",
        "kanban_request_changes",
        "kanban_block",
    }
)
PASSTHROUGH_TOOLS = frozenset({"kanban_show", "kanban_comment", "kanban_heartbeat"})
FORBIDDEN_KANBAN_SUBCOMMANDS = frozenset(
    {"complete", "request-review", "request-changes", "block"}
)
_FLAG_WITH_VALUE = frozenset(
    {
        "--board",
        "-p",
        "--profile",
        "--reason",
        "--summary",
        "--idempotency-key",
        "--assignee",
        "--workspace",
    }
)

_GUARD_FAILURES: dict[tuple[str, str], str] = {}


def clear_guard_failures() -> None:
    _GUARD_FAILURES.clear()


def guard_failure_for(board: str, task_id: str) -> str | None:
    return _GUARD_FAILURES.get((board, task_id))


def consume_guard_failure(board: str, task_id: str) -> str | None:
    return _GUARD_FAILURES.pop((board, task_id), None)


def record_guard_failure(board: str, task_id: str, message: str) -> None:
    _GUARD_FAILURES[(board, task_id)] = message


def pre_tool_call(*, ctx=None, **kwargs: Any) -> dict[str, str] | None:
    try:
        return _guard_body(ctx=ctx, **kwargs)
    except Exception as exc:
        board, task_id = _scope(kwargs)
        if board and task_id:
            record_guard_failure(board, task_id, str(exc))
            tool_name = str(kwargs.get("tool_name") or "")
            if tool_name in LIFECYCLE_TOOLS or _is_lifecycle_terminal(tool_name, kwargs.get("args") or {}):
                return {
                    "action": "block",
                    "message": f"workflow guard failed closed: {exc}",
                }
        return None


def _guard_body(*, ctx=None, **kwargs: Any) -> dict[str, str] | None:
    tool_name = str(kwargs.get("tool_name") or "")
    args = kwargs.get("args") if isinstance(kwargs.get("args"), Mapping) else {}
    board, task_id = _scope(kwargs)
    if not board or not task_id:
        return None
    manifest = _lookup_manifest(ctx, board, task_id, kwargs)
    if manifest is None:
        return None
    if tool_name in PASSTHROUGH_TOOLS:
        return None
    if tool_name in LIFECYCLE_TOOLS:
        pending = manifest.get("pendingLifecycle")
        if _pending_matches(pending, tool_name, args):
            return None
        return {
            "action": "block",
            "message": (
                f"{tool_name} is blocked unless it exactly matches pendingLifecycle "
                "for this autonomous task"
            ),
        }
    if _is_lifecycle_terminal(tool_name, args):
        return {
            "action": "block",
            "message": "direct hermes kanban lifecycle commands are blocked for autonomous tasks",
        }
    return None


def _lookup_manifest(ctx, board: str, task_id: str, kwargs: Mapping[str, Any]):
    del kwargs
    if ctx is None:
        return None
    config = load_plugin_config(
        {
            "profile": ctx.get_config("profile", "autodev"),
            "state_root": ctx.get_config("state_root", ""),
            "harness_command": ctx.get_config("harness_command", []),
            "main_branch": ctx.get_config("main_branch", "main"),
            "poll_interval_seconds": ctx.get_config("poll_interval_seconds", 5),
            "advance_wait_seconds": ctx.get_config("advance_wait_seconds", 60),
        }
    )
    store = WorkflowStore(config.state_root)
    return store.get_manifest(board, task_id)


def _scope(kwargs: Mapping[str, Any]) -> tuple[str | None, str | None]:
    environ = kwargs.get("environ") or os.environ
    args = kwargs.get("args") if isinstance(kwargs.get("args"), Mapping) else {}
    task_id = environ.get("HERMES_KANBAN_TASK") or args.get("task_id")
    board = environ.get("HERMES_KANBAN_BOARD") or args.get("board")
    return (
        str(board) if board else None,
        str(task_id) if task_id else None,
    )


def _pending_matches(pending: Any, tool_name: str, args: Mapping[str, Any]) -> bool:
    if not isinstance(pending, Mapping):
        return False
    if pending.get("tool") != tool_name:
        return False
    expected = pending.get("args") if isinstance(pending.get("args"), Mapping) else {}
    for key, value in expected.items():
        if args.get(key) != value:
            return False
    return True


def _is_lifecycle_terminal(tool_name: str, args: Mapping[str, Any]) -> bool:
    if tool_name not in {"terminal", "bash", "shell"}:
        return False
    command = args.get("command")
    if not isinstance(command, str):
        return False
    return is_forbidden_hermes_kanban_lifecycle(command)


def is_forbidden_hermes_kanban_lifecycle(command: str) -> bool:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.replace(";", " ").replace("|", " ").split()
    names = [Path(token).name for token in tokens]
    try:
        hermes_at = next(index for index, name in enumerate(names) if name == "hermes")
    except StopIteration:
        return False
    try:
        kanban_at = next(
            index for index, name in enumerate(names[hermes_at + 1 :], start=hermes_at + 1) if name == "kanban"
        )
    except StopIteration:
        return False
    index = kanban_at + 1
    while index < len(tokens):
        token = tokens[index]
        if token in _FLAG_WITH_VALUE:
            index += 2
            continue
        if token.startswith("-"):
            if token == "--json":
                index += 1
                continue
            index += 1
            continue
        return token in FORBIDDEN_KANBAN_SUBCOMMANDS
    return False


def assert_guard_clear(board: str, task_id: str) -> None:
    message = consume_guard_failure(board, task_id)
    if message:
        raise WorkflowProtocolError(f"workflow guard failed closed: {message}")
