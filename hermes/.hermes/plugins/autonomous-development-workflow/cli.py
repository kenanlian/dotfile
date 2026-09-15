"""Plugin CLI: argv builders and autodev enqueue. Hermes calls use shell=False."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Callable

from .config import load_plugin_config
from .controller.service import (
    build_kanban_create_argv,
    build_kanban_link_argv,
    build_kanban_show_argv,
    build_kanban_unblock_argv,
    enqueue_workflow,
    run_argv,
)
from .controller.store import WorkflowStore


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


def handle_autodev(
    args,
    *,
    config_loader: Callable[..., Any],
    run_command: Callable[[list[str]], tuple[int, str, str]] = run_argv,
) -> int:
    if getattr(args, "autodev_command", None) != "enqueue":
        print("autodev CLI is not implemented", file=sys.stderr)
        return 2
    config = load_plugin_config(
        {
            "profile": config_loader("profile", "autodev"),
            "state_root": config_loader("state_root", ""),
            "harness_command": config_loader("harness_command", []),
            "main_branch": config_loader("main_branch", "main"),
            "poll_interval_seconds": config_loader("poll_interval_seconds", 5),
            "advance_wait_seconds": config_loader("advance_wait_seconds", 60),
        }
    )
    store = WorkflowStore(config.state_root)
    result = enqueue_workflow(
        board=args.board,
        repo=args.repo,
        title=args.title,
        requirement=args.requirement,
        profile=args.profile or config.profile,
        idempotency_key=args.idempotency_key,
        config=config,
        store=store,
        run_argv=run_command,
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0
