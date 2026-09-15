"""Shared smoke fixtures: git repo, Kanban double, mock-harness controller."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from plugin_imports import import_plugin

_git_guard = import_plugin("controller.git_guard")
_hooks = import_plugin("hooks")
_service = import_plugin("controller.service")
_store = import_plugin("controller.store")
_types = import_plugin("controller.types")

PluginConfig = _types.PluginConfig
WORKFLOW_SCHEMA = _types.WORKFLOW_SCHEMA
WORKFLOW_TEMPLATE_ID = _types.WORKFLOW_TEMPLATE_ID
WorkflowStore = _store.WorkflowStore
WorkflowController = _service.WorkflowController
enqueue_workflow = _service.enqueue_workflow
fingerprint_digest = _git_guard.fingerprint_digest
capture_candidate_fingerprint = _git_guard.capture_candidate_fingerprint
clear_guard_failures = _hooks.clear_guard_failures
pre_tool_call = _hooks.pre_tool_call

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
MOCK_HARNESS = FIXTURES / "mock_harness.mjs"
REPO_FIXTURE = FIXTURES / "repo"
HAPPY_SCRIPT = FIXTURES / "jobs" / "happy-path.script.json"

AGENTS = {
    "planner": {"model": "planner-model", "thinking": "high"},
    "plan-reviewer": {"model": "review-model", "thinking": "high"},
    "implementer": {"model": "impl-model", "thinking": "high"},
    "execute-reviewer": {"model": "review-model", "thinking": "medium"},
}


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        shell=False,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def init_fixture_repo(destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(REPO_FIXTURE, destination)
    git(destination, "init", "-b", "main")
    git(destination, "config", "user.email", "dev@example.com")
    git(destination, "config", "user.name", "Dev")
    git(destination, "add", ".")
    git(destination, "commit", "-m", "fixture")
    return destination


class SmokeKanban:
    """CLI argv runner + native tool dispatcher for the same fake board."""

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.tool_calls: list[tuple[str, dict]] = []
        self.cards: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.links: list[tuple[str, str]] = []
        self.run_id = "1"
        self.review = False
        self._n = 0

    def run_argv(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(argv))
        action = _kanban_action(argv)
        if action == "create":
            return self._create(argv)
        if action == "link":
            parent, child = argv[-2], argv[-1]
            self.links.append((parent, child))
            return 0, f"Linked {parent} -> {child}\n", ""
        if action == "show":
            task_id = argv[argv.index("show") + 1]
            return 0, json.dumps(self.show_payload(task_id)), ""
        if action == "unblock":
            task_id = argv[argv.index("unblock") + 1]
            task = self.cards[task_id]
            parents = [parent for parent, child in self.links if child == task_id]
            task["status"] = "todo" if parents else "ready"
            return 0, json.dumps({"ok": True, "task": dict(task)}), ""
        if action in {"complete", "request-review", "request-changes", "block"}:
            return 0, json.dumps({"ok": True}), ""
        raise AssertionError(f"unexpected argv {argv}")

    def dispatch(self, name: str, args: dict, **kwargs) -> str:
        self.tool_calls.append((name, dict(args)))
        task_id = args.get("task_id") or next(iter(self.cards), "t_1")
        if name == "kanban_show":
            return json.dumps(self.show_payload(task_id))
        if name == "kanban_request_review":
            self.cards[task_id]["status"] = "review"
            return json.dumps({"ok": True, "task_id": task_id})
        if name == "kanban_complete":
            self.cards[task_id]["status"] = "done"
            return json.dumps({"ok": True, "task_id": task_id})
        if name == "kanban_request_changes":
            self.cards[task_id]["status"] = "todo"
            self.review = False
            return json.dumps({"ok": True, "task_id": task_id})
        if name == "kanban_block":
            self.cards[task_id]["status"] = "blocked"
            self.cards[task_id]["block_kind"] = args.get("kind")
            return json.dumps({"ok": True, "task_id": task_id})
        if name == "kanban_heartbeat":
            return json.dumps({"ok": True})
        return json.dumps({"error": f"unknown tool {name}"})

    def show_payload(self, task_id: str) -> dict[str, Any]:
        task = dict(self.cards[task_id])
        task["current_run_id"] = self.run_id
        parents = [parent for parent, child in self.links if child == task_id]
        payload = {"source_status": "review" if self.review else "ready"}
        return {
            "task": task,
            "parents": parents,
            "children": [child for parent, child in self.links if parent == task_id],
            "comments": [],
            "events": [
                {
                    "kind": "claimed",
                    "run_id": self.run_id,
                    "payload": payload,
                    "created_at": 1,
                }
            ],
            "runs": [{"id": self.run_id, "status": "running", "metadata": payload}],
        }

    def claim_review(self, task_id: str, run_id: str = "2") -> None:
        self.review = True
        self.run_id = run_id
        self.cards[task_id]["status"] = "running"

    def claim_ready(self, task_id: str, run_id: str = "1") -> None:
        self.review = False
        self.run_id = run_id
        if self.cards[task_id]["status"] in {"ready", "todo", "review"}:
            self.cards[task_id]["status"] = "running"

    def _create(self, argv: list[str]) -> tuple[int, str, str]:
        key = _flag(argv, "--idempotency-key")
        if key in self.by_key:
            task = self.cards[self.by_key[key]]
            return 0, json.dumps(task), ""
        self._n += 1
        task_id = f"t_{self._n}"
        workspace = _flag(argv, "--workspace")
        path = workspace.split(":", 1)[1]
        task = {
            "id": task_id,
            "title": argv[argv.index("create") + 1],
            "assignee": _flag(argv, "--assignee"),
            "status": "blocked",
            "workspace_kind": "dir",
            "workspace_path": path,
            "current_run_id": self.run_id,
        }
        self.cards[task_id] = task
        self.by_key[key] = task_id
        return 0, json.dumps(task), ""


class SmokeEnv:
    def __init__(self, *, script: Mapping[str, Any] | None = None) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-smoke-")
        self.root = Path(self._tmp.name)
        self.state_root = self.root / "state"
        self.state_root.mkdir()
        self.repo = init_fixture_repo(self.root / "repo")
        self.requirement = self.repo / "requirement.md"
        self.script_path = self.root / "harness.script.json"
        self.launch_log = self.root / "harness.launches.jsonl"
        payload = script if script is not None else json.loads(HAPPY_SCRIPT.read_text(encoding="utf-8"))
        self.script_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.kanban = SmokeKanban()
        self.store = WorkflowStore(str(self.state_root))
        self.config = PluginConfig(
            profile="autodev",
            state_root=str(self.state_root),
            harness_command=("node", str(MOCK_HARNESS)),
            main_branch="main",
            poll_interval_seconds=1,
            advance_wait_seconds=30,
        )
        self.evidence = self.root / "evidence" / "login.png"
        self.evidence.parent.mkdir()
        self.evidence.write_bytes(b"png")
        clear_guard_failures()

    def close(self) -> None:
        clear_guard_failures()
        self._tmp.cleanup()

    def controller(self) -> WorkflowController:
        return WorkflowController(
            store=self.store,
            config=self.config,
            dispatch_tool=self.kanban.dispatch,
            agents=AGENTS,
            sleep_fn=lambda seconds: __import__("time").sleep(min(float(seconds), 0.05)),
        )

    def enqueue(self, *, title: str = "Smoke card", key: str | None = None) -> dict[str, Any]:
        return enqueue_workflow(
            board="project-board",
            repo=str(self.repo),
            title=title,
            requirement=str(self.requirement),
            profile="autodev",
            config=self.config,
            store=self.store,
            run_argv=self.kanban.run_argv,
            idempotency_key=key,
        )

    def harness_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["MOCK_HARNESS_SCRIPT"] = str(self.script_path)
        env["MOCK_HARNESS_LAUNCH_LOG"] = str(self.launch_log)
        return env

    def set_script(self, script: Mapping[str, Any]) -> None:
        self.script_path.write_text(json.dumps(script, indent=2), encoding="utf-8")

    def launch_count(self) -> int:
        if not self.launch_log.is_file():
            return 0
        return len([line for line in self.launch_log.read_text(encoding="utf-8").splitlines() if line.strip()])

    def launches(self) -> list[dict[str, Any]]:
        if not self.launch_log.is_file():
            return []
        return [json.loads(line) for line in self.launch_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def advance_until(
        self,
        *,
        task_id: str,
        run_id: str | None = None,
        outcomes: set[str] | None = None,
        statuses: set[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        controller = self.controller()
        env = self.harness_env()
        result = None
        for _ in range(limit):
            with _patched_env(env):
                result = controller.advance(
                    board="project-board",
                    task_id=task_id,
                    run_id=str(run_id or self.kanban.run_id),
                    wait_seconds=8,
                )
            if outcomes and result.get("outcome") in outcomes:
                return result
            if statuses and result.get("workflowStatus") in statuses:
                return result
            if result.get("outcome") in {"blocked", "acceptance_required"}:
                return result
            if result.get("nextAction") == "noop" and result.get("workflowStatus") in {
                "review_requested",
                "completed",
                "blocked",
            }:
                return result
        raise AssertionError(f"did not reach {outcomes or statuses}: last={result}")

    def accept(self, task_id: str, **submission) -> dict[str, Any]:
        payload = {
            "verdict": "passed",
            "summary": "Login works.",
            "scenarios": [
                {"name": "login", "status": "passed", "evidence": [str(self.evidence)]}
            ],
            "findings": [],
            "question": None,
        }
        payload.update(submission)
        return self.controller().submit_acceptance(
            board="project-board",
            task_id=task_id,
            run_id=str(self.kanban.run_id),
            **payload,
        )


class _patched_env:
    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = env
        self._patch = None

    def __enter__(self):
        from unittest.mock import patch

        self._patch = patch.dict(os.environ, self.env, clear=False)
        return self._patch.__enter__()

    def __exit__(self, *args):
        return self._patch.__exit__(*args)


def _kanban_action(argv: list[str]) -> str:
    for item in ("create", "link", "show", "unblock", "complete", "request-review", "request-changes", "block"):
        if item in argv:
            return item
    return ""


def _flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]
