"""Typed product acceptance, Skill rules, and pre_tool_call bypass guard."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugin_imports import import_plugin

_acceptance = import_plugin("controller.acceptance")
_git_guard = import_plugin("controller.git_guard")
_hooks = import_plugin("hooks")
_lifecycle = import_plugin("controller.lifecycle")
_plugin = import_plugin("__init__")
_protocol = import_plugin("controller.protocol")
_service = import_plugin("controller.service")
_store = import_plugin("controller.store")
_tools = import_plugin("tools")
_types = import_plugin("controller.types")

PluginConfig = _types.PluginConfig
WORKFLOW_SCHEMA = _types.WORKFLOW_SCHEMA
WORKFLOW_TEMPLATE_ID = _types.WORKFLOW_TEMPLATE_ID
WorkflowProtocolError = _types.WorkflowProtocolError
WorkflowStore = _store.WorkflowStore
WorkflowController = _service.WorkflowController
make_pending_lifecycle = _lifecycle.make_pending_lifecycle
capture_candidate_fingerprint = _git_guard.capture_candidate_fingerprint
fingerprint_digest = _git_guard.fingerprint_digest
pre_tool_call = _hooks.pre_tool_call
submit_typed_acceptance = _acceptance.submit_typed_acceptance
is_review_lane = _acceptance.is_review_lane
guard_failure_for = _hooks.guard_failure_for
clear_guard_failures = _hooks.clear_guard_failures

PLUGIN_ID = "autonomous-development-workflow"
HERMES_AGENT_ROOT = Path("/Users/kenan/.hermes/hermes-agent")
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = PLUGIN_ROOT / "skills" / "autonomous-development-workflow" / "SKILL.md"
AGENTS = {
    "planner": {"model": "planner-model", "thinking": "high"},
    "plan-reviewer": {"model": "review-model", "thinking": "high"},
    "implementer": {"model": "impl-model", "thinking": "high"},
    "execute-reviewer": {"model": "review-model", "thinking": "medium"},
}


def _ensure_hermes_on_path() -> None:
    root = str(HERMES_AGENT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        shell=False,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    (repo / "app.txt").write_text("candidate\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "init")
    return repo


def _config(state_root: Path) -> PluginConfig:
    return PluginConfig(
        profile="autodev",
        state_root=str(state_root),
        harness_command=("node", "/abs/harness.mjs"),
        main_branch="main",
        poll_interval_seconds=5,
        advance_wait_seconds=60,
    )


def _manifest(repo: Path, fingerprint: str, **overrides):
    data = {
        "schema": WORKFLOW_SCHEMA,
        "templateId": WORKFLOW_TEMPLATE_ID,
        "board": "project-board",
        "taskId": "t_abc",
        "repoRoot": str(repo.resolve()),
        "workflowStatus": "product_acceptance",
        "revision": 6,
        "stageAttempt": 1,
        "activeJobId": None,
        "plannerSessionId": "sess_plan",
        "implementerSessionId": "sess_impl",
        "planReworkCount": 0,
        "implementReworkCount": 0,
        "runFailureCounts": {},
        "baseline": {"branch": "main", "head": _git(repo, "rev-parse", "HEAD")},
        "candidateFingerprint": fingerprint,
        "approvedPlan": "/abs/plan.json",
        "lastConsumedJobId": "job_exec",
        "pendingLifecycle": None,
        "resumeStatus": None,
    }
    data.update(overrides)
    return data


class FakeKanban:
    def __init__(self, *, status: str = "running", run_id: str = "9", review: bool = True) -> None:
        self.status = status
        self.run_id = run_id
        self.review = review
        self.calls: list[tuple[str, dict]] = []
        self.block_kind: str | None = None

    def __call__(self, name: str, args: dict, **kwargs) -> str:
        self.calls.append((name, dict(args)))
        if name == "kanban_show":
            payload = {
                "source_status": "review" if self.review else "ready",
            }
            return json.dumps(
                {
                    "task": {
                        "id": args.get("task_id", "t_abc"),
                        "title": "Acceptance fixture card",
                        "status": self.status,
                        "assignee": "autodev",
                        "workspace_kind": "dir",
                        "workspace_path": args.get("workspace_path"),
                        "current_run_id": self.run_id,
                    },
                    "parents": [],
                    "children": [],
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
            )
        if name == "kanban_complete":
            self.status = "done"
            return json.dumps({"ok": True, "task_id": args.get("task_id")})
        if name == "kanban_request_changes":
            self.status = "todo"
            return json.dumps({"ok": True, "task_id": args.get("task_id")})
        if name == "kanban_block":
            self.status = "blocked"
            self.block_kind = args.get("kind")
            return json.dumps({"ok": True, "task_id": args.get("task_id")})
        if name == "kanban_heartbeat":
            return json.dumps({"ok": True})
        return json.dumps({"error": f"unknown tool {name}"})


class FakeCtx:
    def __init__(self, state_root: Path) -> None:
        self._values = {
            "profile": "autodev",
            "state_root": str(state_root),
            "harness_command": ["node", "/abs/harness.mjs"],
            "main_branch": "main",
            "poll_interval_seconds": 5,
            "advance_wait_seconds": 60,
        }

    def get_config(self, key: str, default=None):
        return self._values.get(key, default)


class AcceptanceHelpers:
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-accept-")
        self.root = Path(self._tmp.name)
        self.state_root = self.root / "state"
        self.state_root.mkdir()
        self.repo = _init_repo(self.root)
        (self.repo / "app.txt").write_text("implemented\n", encoding="utf-8")
        self.evidence = self.root / "evidence" / "login.png"
        self.evidence.parent.mkdir()
        self.evidence.write_bytes(b"png-bytes")
        self.store = WorkflowStore(str(self.state_root))
        self.fingerprint = fingerprint_digest(capture_candidate_fingerprint(str(self.repo)))
        self.kanban = FakeKanban()
        self.kanban.calls = []
        shown = json.loads(self.kanban("kanban_show", {"task_id": "t_abc"}))
        shown["task"]["workspace_path"] = str(self.repo.resolve())
        self.kanban = FakeKanban()
        original = self.kanban.__call__

        def _dispatch(name, args, **kwargs):
            if name == "kanban_show":
                payload = json.loads(original(name, args, **kwargs))
                payload["task"]["workspace_path"] = str(self.repo.resolve())
                return json.dumps(payload)
            return original(name, args, **kwargs)

        self.kanban.__call__ = _dispatch  # type: ignore[method-assign]
        self.store.put_manifest(_manifest(self.repo, self.fingerprint))
        clear_guard_failures()

    def tearDown(self) -> None:
        clear_guard_failures()
        self._tmp.cleanup()

    def _controller(self) -> WorkflowController:
        return WorkflowController(
            store=self.store,
            config=_config(self.state_root),
            dispatch_tool=self.kanban,
            agents=AGENTS,
        )

    def _submission(self, **overrides) -> dict:
        data = {
            "verdict": "passed",
            "summary": "Login and dashboard work.",
            "scenarios": [
                {
                    "name": "login",
                    "status": "passed",
                    "evidence": [str(self.evidence)],
                }
            ],
            "findings": [],
            "question": None,
        }
        data.update(overrides)
        return data


class ReviewLaneTests(unittest.TestCase):
    def test_claimed_event_source_status_review_is_review_lane(self) -> None:
        shown = {
            "events": [
                {
                    "kind": "claimed",
                    "run_id": "9",
                    "payload": {"source_status": "review"},
                }
            ]
        }
        self.assertTrue(is_review_lane(shown, "9"))
        self.assertFalse(is_review_lane(shown, "8"))
        self.assertFalse(
            is_review_lane(
                {"events": [{"kind": "claimed", "run_id": "9", "payload": {"source_status": "ready"}}]},
                "9",
            )
        )


class TypedAcceptanceTests(AcceptanceHelpers, unittest.TestCase):
    def test_passed_writes_canonical_artifact_and_completes(self) -> None:
        controller = self._controller()
        acceptance_dir = self.state_root / "boards" / "project-board" / "t_abc" / "acceptance"
        self.assertFalse(acceptance_dir.exists())
        result = controller.submit_acceptance(
            board="project-board",
            task_id="t_abc",
            run_id="9",
            **self._submission(),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["workflowStatus"], "completed")
        artifact = acceptance_dir / "product-acceptance-v1.json"
        self.assertTrue(artifact.is_file())
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "autonomous-development.acceptance.v1")
        self.assertEqual(payload["verdict"], "passed")
        self.assertEqual(payload["candidateFingerprint"], self.fingerprint)
        self.assertEqual(json.dumps(payload, sort_keys=True, ensure_ascii=False), artifact.read_text(encoding="utf-8"))
        registered = self.store.get_artifact("project-board", "t_abc", "product-acceptance", 1)
        self.assertIsNotNone(registered)
        self.assertEqual(registered["sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
        completes = [name for name, _ in self.kanban.calls if name == "kanban_complete"]
        self.assertEqual(len(completes), 1)

    def test_non_review_run_is_rejected(self) -> None:
        self.kanban.review = False
        with self.assertRaises(WorkflowProtocolError):
            self._controller().submit_acceptance(
                board="project-board",
                task_id="t_abc",
                run_id="9",
                **self._submission(),
            )
        self.assertFalse(
            (self.state_root / "boards" / "project-board" / "t_abc" / "acceptance").exists()
        )

    def test_non_acceptance_status_is_rejected(self) -> None:
        current = self.store.get_manifest("project-board", "t_abc")
        blocked = dict(current)
        blocked["workflowStatus"] = "blocked"
        blocked["revision"] = int(current["revision"]) + 1
        self.store.cas_update_manifest(
            "project-board", "t_abc", expected_revision=int(current["revision"]), manifest=blocked
        )
        reviewing = dict(blocked)
        reviewing["workflowStatus"] = "code_reviewing"
        reviewing["revision"] = int(blocked["revision"]) + 1
        self.store.cas_update_manifest(
            "project-board",
            "t_abc",
            expected_revision=int(blocked["revision"]),
            manifest=reviewing,
        )
        with self.assertRaises(WorkflowProtocolError):
            self._controller().submit_acceptance(
                board="project-board",
                task_id="t_abc",
                run_id="9",
                **self._submission(),
            )

    def test_passed_requires_scenarios_and_rejects_blocking_findings(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            self._controller().submit_acceptance(
                board="project-board",
                task_id="t_abc",
                run_id="9",
                **self._submission(scenarios=[]),
            )
        with self.assertRaises(WorkflowProtocolError):
            self._controller().submit_acceptance(
                board="project-board",
                task_id="t_abc",
                run_id="9",
                **self._submission(
                    scenarios=[{"name": "login", "status": "failed", "evidence": [str(self.evidence)]}]
                ),
            )
        with self.assertRaises(WorkflowProtocolError):
            self._controller().submit_acceptance(
                board="project-board",
                task_id="t_abc",
                run_id="9",
                **self._submission(findings=[{"severity": "blocking", "problem": "Broken checkout"}]),
            )

    def test_failed_requests_implement_rework(self) -> None:
        result = self._controller().submit_acceptance(
            board="project-board",
            task_id="t_abc",
            run_id="9",
            **self._submission(
                verdict="failed",
                summary="Checkout still fails.",
                scenarios=[{"name": "checkout", "status": "failed", "evidence": [str(self.evidence)]}],
                findings=[{"severity": "blocking", "problem": "Pay button 500s"}],
            ),
        )
        self.assertEqual(result["workflowStatus"], "implement_rework")
        changes = [name for name, _ in self.kanban.calls if name == "kanban_request_changes"]
        self.assertEqual(len(changes), 1)
        loaded = self.store.get_manifest("project-board", "t_abc")
        self.assertEqual(loaded["implementReworkCount"], 1)
        artifact = self.state_root / "boards" / "project-board" / "t_abc" / "acceptance" / "product-acceptance-v1.json"
        self.assertTrue(artifact.is_file())
        self.assertEqual(json.loads(artifact.read_text(encoding="utf-8"))["verdict"], "failed")

    def test_needs_human_blocks_with_needs_input(self) -> None:
        result = self._controller().submit_acceptance(
            board="project-board",
            task_id="t_abc",
            run_id="9",
            **self._submission(
                verdict="needs_human",
                summary="Empty-state copy is unspecified.",
                scenarios=[],
                question="What copy should the empty dashboard show?",
            ),
        )
        self.assertEqual(result["workflowStatus"], "blocked")
        self.assertEqual(self.kanban.block_kind, "needs_input")
        loaded = self.store.get_manifest("project-board", "t_abc")
        self.assertEqual(loaded["resumeStatus"], "product_acceptance")
        blocks = [args for name, args in self.kanban.calls if name == "kanban_block"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].get("kind"), "needs_input")

    def test_needs_human_unblocks_to_product_acceptance_and_can_resubmit(self) -> None:
        self._controller().submit_acceptance(
            board="project-board",
            task_id="t_abc",
            run_id="9",
            **self._submission(
                verdict="needs_human",
                summary="Empty-state copy is unspecified.",
                scenarios=[],
                question="What copy should the empty dashboard show?",
            ),
        )
        self.assertEqual(self.kanban.status, "blocked")
        still = self._controller().advance(board="project-board", task_id="t_abc", run_id="9")
        self.assertEqual(still["workflowStatus"], "blocked")
        self.assertEqual(still["nextAction"], "noop")
        self.kanban.status = "running"
        resumed = self._controller().advance(board="project-board", task_id="t_abc", run_id="9")
        self.assertEqual(resumed["workflowStatus"], "product_acceptance")
        self.assertEqual(resumed["nextAction"], "await_acceptance")
        loaded = self.store.get_manifest("project-board", "t_abc")
        self.assertIsNone(loaded["resumeStatus"])
        passed = self._controller().submit_acceptance(
            board="project-board",
            task_id="t_abc",
            run_id="9",
            **self._submission(),
        )
        self.assertEqual(passed["workflowStatus"], "completed")

    def test_blocked_uses_typed_block(self) -> None:
        result = self._controller().submit_acceptance(
            board="project-board",
            task_id="t_abc",
            run_id="9",
            **self._submission(
                verdict="blocked",
                summary="Staging environment is unreachable.",
                scenarios=[],
                findings=[{"severity": "blocking", "problem": "VPN required"}],
            ),
        )
        self.assertEqual(result["workflowStatus"], "blocked")
        blocks = [name for name, _ in self.kanban.calls if name == "kanban_block"]
        self.assertEqual(len(blocks), 1)

    def test_fingerprint_drift_rejects_old_verdict(self) -> None:
        (self.repo / "app.txt").write_text("drifted\n", encoding="utf-8")
        with self.assertRaises(WorkflowProtocolError) as caught:
            self._controller().submit_acceptance(
                board="project-board",
                task_id="t_abc",
                run_id="9",
                **self._submission(),
            )
        self.assertIn("fingerprint", str(caught.exception).lower())
        self.assertFalse(any(name == "kanban_complete" for name, _ in self.kanban.calls))
        self.assertIsNone(self.store.latest_artifact("project-board", "t_abc", "product-acceptance"))

    def test_plugin_writes_canonical_json_model_does_not(self) -> None:
        planted = (
            self.state_root / "boards" / "project-board" / "t_abc" / "acceptance" / "product-acceptance-v1.json"
        )
        self.assertFalse(planted.exists())
        submit_typed_acceptance(
            store=self.store,
            config=_config(self.state_root),
            dispatch_tool=self.kanban,
            board="project-board",
            task_id="t_abc",
            run_id="9",
            shown=json.loads(self.kanban("kanban_show", {"task_id": "t_abc"})),
            submission=self._submission(),
        )
        self.assertTrue(planted.is_file())
        self.assertNotIn("verdict", Path(_acceptance.__file__).read_text(encoding="utf-8")[:80])

    def test_missing_evidence_file_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            self._controller().submit_acceptance(
                board="project-board",
                task_id="t_abc",
                run_id="9",
                **self._submission(
                    scenarios=[
                        {
                            "name": "login",
                            "status": "passed",
                            "evidence": [str(self.root / "missing.png")],
                        }
                    ]
                ),
            )


class ToolHandlerAcceptanceTests(AcceptanceHelpers, unittest.TestCase):
    def test_submit_acceptance_handler_uses_typed_path(self) -> None:
        ctx = FakeCtx(self.state_root)
        environ = {
            "HERMES_KANBAN_TASK": "t_abc",
            "HERMES_KANBAN_BOARD": "project-board",
            "HERMES_KANBAN_RUN_ID": "9",
        }
        raw = _tools.submit_acceptance(
            self._submission(),
            ctx=ctx,
            environ=environ,
            dispatch_override=self.kanban,
        )
        payload = json.loads(raw)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload["workflowStatus"], "completed")


class SkillAndPromptTests(unittest.TestCase):
    def test_skill_and_prompt_include_six_behavior_rules(self) -> None:
        self.assertTrue(SKILL_PATH.is_file())
        skill = SKILL_PATH.read_text(encoding="utf-8")
        prompt = _plugin.WORKER_PROMPT
        for text in (skill, prompt):
            self.assertIn("autodev_workflow_status", text)
            self.assertIn("autodev_workflow_advance", text)
            self.assertIn("in_progress", text)
            self.assertIn("acceptance_required", text)
            self.assertIn("autodev_workflow_submit_acceptance", text)
            self.assertIn("needs_human", text)
            self.assertIn("kanban_complete", text)
            self.assertIn("kanban_request_review", text)
            self.assertIn("kanban_request_changes", text)
            self.assertIn("kanban_block", text)

    def test_register_binds_skill_and_kwargs_hook(self) -> None:
        source = Path(_plugin.__file__).read_text(encoding="utf-8")
        self.assertIn("register_skill", source)
        self.assertIn("**kwargs", inspect.getsource(_plugin._on_pre_tool_call))


class BypassGuardTests(AcceptanceHelpers, unittest.TestCase):
    def _env(self) -> dict[str, str]:
        return {
            "HERMES_KANBAN_TASK": "t_abc",
            "HERMES_KANBAN_BOARD": "project-board",
            "HERMES_KANBAN_RUN_ID": "9",
        }

    def test_ordinary_card_without_manifest_is_not_intercepted(self) -> None:
        ctx = FakeCtx(self.state_root)
        result = pre_tool_call(
            ctx=ctx,
            tool_name="kanban_complete",
            args={"summary": "done"},
            task_id="session",
            environ={
                "HERMES_KANBAN_TASK": "t_ordinary",
                "HERMES_KANBAN_BOARD": "project-board",
            },
        )
        self.assertIsNone(result)

    def test_lifecycle_tools_require_matching_pending_lifecycle(self) -> None:
        ctx = FakeCtx(self.state_root)
        blocked = pre_tool_call(
            ctx=ctx,
            tool_name="kanban_complete",
            args={"summary": "Product acceptance passed.", "task_id": "t_abc"},
            task_id="session",
            environ=self._env(),
        )
        self.assertEqual(blocked["action"], "block")
        pending = make_pending_lifecycle(
            target_status="completed",
            run_id="9",
            workflow_revision=7,
        )
        current = self.store.get_manifest("project-board", "t_abc")
        current["pendingLifecycle"] = pending
        current["revision"] = 7
        self.store.cas_update_manifest("project-board", "t_abc", expected_revision=6, manifest=current)
        allowed = pre_tool_call(
            ctx=ctx,
            tool_name="kanban_complete",
            args=dict(pending["args"], task_id="t_abc"),
            task_id="session",
            environ=self._env(),
        )
        self.assertIsNone(allowed)
        mismatched = pre_tool_call(
            ctx=ctx,
            tool_name="kanban_request_review",
            args={"summary": "nope", "task_id": "t_abc"},
            task_id="session",
            environ=self._env(),
        )
        self.assertEqual(mismatched["action"], "block")

    def test_show_comment_and_heartbeat_are_not_blocked(self) -> None:
        ctx = FakeCtx(self.state_root)
        for name in ("kanban_show", "kanban_comment", "kanban_heartbeat"):
            result = pre_tool_call(
                ctx=ctx,
                tool_name=name,
                args={"task_id": "t_abc", "comment": "note", "note": "alive"},
                task_id="session",
                environ=self._env(),
            )
            self.assertIsNone(result, name)

    def test_terminal_equivalent_lifecycle_commands_are_blocked(self) -> None:
        ctx = FakeCtx(self.state_root)
        commands = [
            "hermes kanban complete t_abc",
            "hermes kanban --board project-board request-review t_abc",
            "/usr/local/bin/hermes kanban request-changes t_abc --reason x",
            "hermes -p autodev kanban block t_abc",
        ]
        for command in commands:
            result = pre_tool_call(
                ctx=ctx,
                tool_name="terminal",
                args={"command": command},
                task_id="session",
                environ=self._env(),
            )
            self.assertEqual(result["action"], "block", command)
        allowed = pre_tool_call(
            ctx=ctx,
            tool_name="terminal",
            args={"command": "hermes kanban show t_abc --json"},
            task_id="session",
            environ=self._env(),
        )
        self.assertIsNone(allowed)

    def test_hook_accepts_kwargs_and_exceptions_fail_closed_on_next_controller_call(self) -> None:
        ctx = FakeCtx(self.state_root)
        signature = inspect.signature(pre_tool_call)
        self.assertIn("kwargs", str(signature))
        with patch.object(_hooks, "_lookup_manifest", side_effect=RuntimeError("boom")):
            result = pre_tool_call(
                ctx=ctx,
                tool_name="kanban_complete",
                args={"summary": "x"},
                task_id="session",
                extra_future_field=True,
                environ=self._env(),
            )
        recorded = guard_failure_for("project-board", "t_abc")
        self.assertIsNotNone(recorded)
        self.assertIn("boom", recorded)
        self.assertEqual(result["action"], "block")
        with self.assertRaises(WorkflowProtocolError) as caught:
            self._controller().advance(board="project-board", task_id="t_abc", run_id="9")
        self.assertIn("guard", str(caught.exception).lower())


class RealDiscoveryGuardTests(unittest.TestCase):
    def test_plugin_registers_skill_and_does_not_override_native_tools(self) -> None:
        _ensure_hermes_on_path()
        from hermes_cli.plugins import PluginManager
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override
        from tools.registry import registry

        home = Path(tempfile.mkdtemp(prefix="autodev-accept-reg-"))
        bundled = home / "bundled-plugins"
        plugins_root = home / "plugins"
        installed = plugins_root / PLUGIN_ID
        entries_before = {entry.name: entry for entry in registry._snapshot_entries()}
        policy_before = dict(registry._plugin_override_policy)
        token = None
        manager = None
        try:
            bundled.mkdir()
            plugins_root.mkdir()
            shutil.copytree(
                PLUGIN_ROOT,
                installed,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"),
            )
            (home / "config.yaml").write_text(
                "plugins:\n  enabled:\n    - autonomous-development-workflow\n",
                encoding="utf-8",
            )
            token = set_hermes_home_override(home)
            with patch.dict(os.environ, {"HERMES_HOME": str(home), "HERMES_BUNDLED_PLUGINS": str(bundled), "HERMES_ENABLE_PROJECT_PLUGINS": "0"}, clear=False), patch.object(
                PluginManager, "_scan_entry_points", lambda self: []
            ):
                manager = PluginManager()
                manager.discover_and_load()
            loaded = manager._plugins.get(PLUGIN_ID)
            self.assertIsNotNone(loaded)
            self.assertTrue(any(name.endswith(":autonomous-development-workflow") or "autonomous-development-workflow" in name for name in manager._plugin_skills))
            entries_after = {entry.name: entry for entry in registry._snapshot_entries()}
            for name, previous in entries_before.items():
                self.assertIs(entries_after.get(name), previous, name)
            self.assertNotIn("kanban_complete", set(entries_after) - set(entries_before))
        finally:
            if manager is not None:
                try:
                    manager.unload()
                except Exception:
                    pass
            _restore_registry(entries_before, policy_before)
            if token is not None:
                reset_hermes_home_override(token)
            shutil.rmtree(home, ignore_errors=True)


def _restore_registry(entries_before: dict, policy_before: dict) -> None:
    from tools.registry import registry

    entries_after = {entry.name: entry for entry in registry._snapshot_entries()}
    changed_names = set(entries_before) | set(entries_after)
    with registry._lock:
        for name in changed_names:
            previous = entries_before.get(name)
            if previous is None:
                registry._tools.pop(name, None)
            else:
                registry._tools[name] = previous
        registry._plugin_override_policy.clear()
        registry._plugin_override_policy.update(policy_before)
        if any(entries_after.get(name) is not entries_before.get(name) for name in changed_names):
            registry._generation += 1


if __name__ == "__main__":
    unittest.main()
