"""Tool handlers. Registration stays side-effect free; handlers use the bound PluginContext."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from .config import load_plugin_config
from .controller.service import FORBIDDEN_ADVANCE_KEYS, WorkflowController
from .controller.store import WorkflowStore
from .controller.types import WorkflowProtocolError
from .hooks import assert_guard_clear

_DEFAULT_AGENTS = {
    "planner": {"model": "unconfigured", "thinking": "high"},
    "plan-reviewer": {"model": "unconfigured", "thinking": "high"},
    "implementer": {"model": "unconfigured", "thinking": "high"},
    "execute-reviewer": {"model": "unconfigured", "thinking": "high"},
}


def workflow_status(args: dict, **kwargs) -> str:
    try:
        controller, board, task_id, run_id = _controller_scope(args, kwargs, mutate=False)
        return json.dumps(
            controller.status(board=board, task_id=task_id, run_id=run_id),
            sort_keys=True,
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def workflow_advance(args: dict, **kwargs) -> str:
    try:
        extra = dict(args or {})
        controller, board, task_id, run_id = _controller_scope(extra, kwargs, mutate=True)
        wait_seconds = extra.pop("wait_seconds", 60)
        extra.pop("task_id", None)
        extra.pop("board", None)
        if extra:
            raise WorkflowProtocolError(f"advance does not accept {sorted(extra)}")
        if not run_id:
            raise WorkflowProtocolError("advance requires a Dispatcher Worker run")
        return json.dumps(
            controller.advance(
                board=board,
                task_id=task_id,
                run_id=str(run_id),
                wait_seconds=int(wait_seconds),
                extra_args=args,
            ),
            sort_keys=True,
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def submit_acceptance(args: dict, **kwargs) -> str:
    try:
        extra = dict(args or {})
        controller, board, task_id, run_id = _controller_scope(extra, kwargs, mutate=True)
        extra.pop("task_id", None)
        extra.pop("board", None)
        if not run_id:
            raise WorkflowProtocolError("acceptance requires a Dispatcher Worker run")
        return json.dumps(
            controller.submit_acceptance(
                board=board,
                task_id=task_id,
                run_id=str(run_id),
                verdict=extra.pop("verdict", None),
                summary=extra.pop("summary", None),
                scenarios=extra.pop("scenarios", None),
                findings=extra.pop("findings", None),
                question=extra.pop("question", None),
            ),
            sort_keys=True,
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def _controller_scope(
    args: Mapping[str, Any],
    kwargs: Mapping[str, Any],
    *,
    mutate: bool,
) -> tuple[WorkflowController, str, str, str | None]:
    ctx = kwargs.get("ctx")
    if ctx is None:
        raise WorkflowProtocolError("plugin context is required")
    environ = kwargs.get("environ") or os.environ
    env_task = environ.get("HERMES_KANBAN_TASK")
    env_board = environ.get("HERMES_KANBAN_BOARD")
    env_run = environ.get("HERMES_KANBAN_RUN_ID")
    if mutate and not env_task:
        raise WorkflowProtocolError("advance/acceptance require a Dispatcher Worker context")
    task_id = args.get("task_id") or env_task
    board = args.get("board") or env_board
    if not task_id or not board:
        raise WorkflowProtocolError("board and task_id are required")
    if env_task and str(task_id) != str(env_task):
        raise WorkflowProtocolError("task_id does not match the current Worker task")
    if env_board and str(board) != str(env_board):
        raise WorkflowProtocolError("board does not match the current Worker board")
    if args.get("stage") or FORBIDDEN_ADVANCE_KEYS.intersection(args):
        raise WorkflowProtocolError("caller cannot pass stage, target state, or lifecycle parameters")
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
    if mutate:
        assert_guard_clear(str(board), str(task_id))
    agents = ctx.get_config("agents", _DEFAULT_AGENTS)
    dispatch = (
        kwargs.get("dispatch_tool")
        or kwargs.get("dispatch_override")
        or getattr(ctx, "dispatch_tool", None)
    )
    if dispatch is None:
        raise WorkflowProtocolError("plugin context is required")
    controller = WorkflowController(
        store=store,
        config=config,
        dispatch_tool=dispatch,
        agents=agents,
        popen=kwargs.get("popen"),
        identity_fn=kwargs.get("identity_fn"),
        sleep_fn=kwargs.get("sleep_fn"),
        monotonic_fn=kwargs.get("monotonic_fn"),
    )
    return controller, str(board), str(task_id), str(env_run) if env_run else None
