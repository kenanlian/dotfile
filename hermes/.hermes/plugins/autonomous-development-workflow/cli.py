"""Plugin CLI: argv builders and autodev enqueue/status/doctor/reconcile/abandon."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Callable

from .config import load_plugin_config
from .controller.service import (
    WorkflowController,
    build_kanban_create_argv,
    build_kanban_link_argv,
    build_kanban_show_argv,
    build_kanban_unblock_argv,
    doctor_report,
    enqueue_workflow,
    run_argv,
)
from .controller.store import WorkflowStore
from .controller.types import WorkflowProtocolError


def invoke_hermes(argv: list[str]) -> tuple[int, str, str]:
    """Run a Hermes argv list with subprocess shell=False."""
    completed = subprocess.run(
        list(argv),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def setup_autodev_cli(parser) -> None:
    sub = parser.add_subparsers(dest="autodev_command", required=True)
    enqueue = sub.add_parser("enqueue", help="Create a blocked autonomous development card and publish it")
    enqueue.add_argument("--board", required=True, help="Kanban board slug")
    enqueue.add_argument("--repo", required=True, help="Absolute git repository path")
    enqueue.add_argument("--title", required=True, help="Card title")
    enqueue.add_argument("--requirement", required=True, help="Absolute requirement markdown path")
    enqueue.add_argument("--profile", default="autodev", help="Worker profile assignee")
    enqueue.add_argument("--idempotency-key", default=None, help="Stable replay key")
    enqueue.add_argument(
        "--flow",
        choices=("full", "direct"),
        default="full",
        help="Allowlisted workflow template: full or direct",
    )
    enqueue.add_argument(
        "--verification",
        default=None,
        help="Absolute autodev.verification.v1 JSON path (required for --flow direct)",
    )
    enqueue.add_argument(
        "--notify-platform",
        default=None,
        help="Subscribe a chat to card completion/block events (requires --notify-chat-id)",
    )
    enqueue.add_argument(
        "--notify-chat-id",
        default=None,
        help="Chat id to notify (requires --notify-platform)",
    )
    enqueue.add_argument(
        "--notify-chat-type",
        choices=("dm", "group", "channel", "thread"),
        default=None,
        help="Optional chat type recorded for wake routing",
    )
    enqueue.add_argument("--notify-thread-id", default=None, help="Optional thread/topic id")
    enqueue.add_argument("--notify-user-id", default=None, help="Optional operator user id")
    enqueue.add_argument(
        "--notify-user-id-alt",
        default=None,
        help="Optional alternate user id (Feishu union_id, Signal UUID, ...)",
    )
    enqueue.add_argument(
        "--notify-mode",
        choices=("notify", "notify+wake", "wake"),
        default=None,
        help="Delivery mode (default: kanban CLI default)",
    )

    status = sub.add_parser("status", help="Show the external workflow checkpoint")
    status.add_argument("--board", required=True, help="Kanban board slug")
    status.add_argument("task_id", help="Kanban task id")

    doctor = sub.add_parser("doctor", help="Read-only workflow diagnostics")
    doctor.add_argument("--board", required=True, help="Kanban board slug")
    doctor.add_argument("task_id", nargs="?", default=None, help="Optional Kanban task id")

    reconcile = sub.add_parser("reconcile", help="Apply proven-idempotent workflow recovery")
    reconcile.add_argument("--board", required=True, help="Kanban board slug")
    reconcile.add_argument("task_id", help="Kanban task id")
    reconcile.add_argument(
        "--reset-failures",
        action="store_true",
        help=(
            "Operator repair for transport-failure-limited cards: clear "
            "runFailureCounts and null activeJobId in one step (avoids the "
            "job identity conflict of clearing counts alone)"
        ),
    )

    abandon = sub.add_parser("abandon", help="Operator-only abandon: record reason and release the repo lease")
    abandon.add_argument("--board", required=True, help="Kanban board slug")
    abandon.add_argument("task_id", help="Kanban task id")
    abandon.add_argument("--reason", required=True, help="Why this card is being abandoned")


def handle_autodev(
    args,
    *,
    config_loader: Callable[..., Any],
    run_command: Callable[[list[str]], tuple[int, str, str]] = run_argv,
) -> int:
    command = getattr(args, "autodev_command", None)
    config = load_plugin_config(
        {
            "profile": config_loader("profile", "autodev"),
            "state_root": config_loader("state_root", ""),
            "harness_command": config_loader("harness_command", []),
            "main_branch": config_loader("main_branch", "main"),
            "poll_interval_seconds": config_loader("poll_interval_seconds", 5),
            "advance_wait_seconds": config_loader("advance_wait_seconds", 60),
            "stage_agents": config_loader("stage_agents", {}),
        }
    )
    store = WorkflowStore(config.state_root)
    if command == "enqueue":
        result = enqueue_workflow(
            board=args.board,
            repo=args.repo,
            title=args.title,
            requirement=args.requirement,
            profile=args.profile or config.profile,
            idempotency_key=args.idempotency_key,
            flow=getattr(args, "flow", "full"),
            verification=getattr(args, "verification", None),
            notify={
                "platform": args.notify_platform,
                "chat_id": args.notify_chat_id,
                "chat_type": args.notify_chat_type,
                "thread_id": args.notify_thread_id,
                "user_id": args.notify_user_id,
                "user_id_alt": args.notify_user_id_alt,
                "delivery_mode": args.notify_mode,
            },
            config=config,
            store=store,
            run_argv=run_command,
        )
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    if command == "status":
        shown = _show_task(run_command, board=args.board, task_id=args.task_id)
        controller = _readonly_controller(
            store,
            config,
            run_command,
            board=args.board,
            agents=config_loader("agents", None),
        )
        result = controller.status(board=args.board, task_id=args.task_id)
        result["kanbanStatus"] = (shown.get("task") or shown).get("status") if shown else None
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    if command == "doctor":
        shown = None
        if args.task_id:
            shown = _show_task(run_command, board=args.board, task_id=args.task_id)
        result = doctor_report(
            store, board=args.board, task_id=args.task_id, shown=shown, config=config
        )
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    if command == "reconcile":
        controller = _readonly_controller(
            store,
            config,
            run_command,
            board=args.board,
            agents=config_loader("agents", None),
        )
        if getattr(args, "reset_failures", False):
            result = controller.reset_failure_counts(board=args.board, task_id=args.task_id)
        else:
            result = controller.reconcile(board=args.board, task_id=args.task_id)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    if command == "abandon":
        controller = _readonly_controller(store, config, run_command, board=args.board)
        result = controller.abandon(board=args.board, task_id=args.task_id, reason=args.reason)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    print("autodev CLI is not implemented", file=sys.stderr)
    return 2


def _readonly_controller(
    store,
    config,
    run_command,
    *,
    board: str,
    agents: Any = None,
) -> WorkflowController:
    def dispatch(name: str, args: dict, **kwargs) -> str:
        if name != "kanban_show":
            raise WorkflowProtocolError("CLI cannot dispatch Kanban lifecycle tools")
        code, stdout, stderr = run_command(
            build_kanban_show_argv(board=board, task_id=str(args.get("task_id")))
        )
        if code != 0:
            raise WorkflowProtocolError(stderr.strip() or stdout.strip() or "kanban show failed")
        return stdout

    return WorkflowController(
        store=store,
        config=config,
        dispatch_tool=dispatch,
        agents=agents,
        stage_agents=config.stage_agents,
    )


def _show_task(run_command, *, board: str, task_id: str) -> dict[str, Any] | None:
    try:
        code, stdout, stderr = run_command(build_kanban_show_argv(board=board, task_id=task_id))
    except Exception:
        return None
    if code != 0:
        return None
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
