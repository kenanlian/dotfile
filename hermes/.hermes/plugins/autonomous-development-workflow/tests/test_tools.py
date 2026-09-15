"""Plugin Workflow tools via real Hermes registry dispatch."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugin_imports import import_plugin

_service = import_plugin("controller.service")
_store = import_plugin("controller.store")
_types = import_plugin("controller.types")

FORBIDDEN_ADVANCE_KEYS = _service.FORBIDDEN_ADVANCE_KEYS
WORKFLOW_SCHEMA = _types.WORKFLOW_SCHEMA
WORKFLOW_TEMPLATE_ID = _types.WORKFLOW_TEMPLATE_ID
WorkflowStore = _store.WorkflowStore

PLUGIN_ID = "autonomous-development-workflow"
PLUGIN_TOOLSET = "autonomous_development_workflow"
HERMES_AGENT_ROOT = Path("/Users/kenan/.hermes/hermes-agent")
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _ensure_hermes_on_path() -> None:
    root = str(HERMES_AGENT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


_ensure_hermes_on_path()


def _manifest(**overrides):
    data = {
        "schema": WORKFLOW_SCHEMA,
        "templateId": WORKFLOW_TEMPLATE_ID,
        "board": "project-board",
        "taskId": "t_abc",
        "repoRoot": "/abs/repo",
        "workflowStatus": "planning",
        "revision": 1,
        "stageAttempt": 1,
        "activeJobId": None,
        "plannerSessionId": None,
        "implementerSessionId": None,
        "planReworkCount": 0,
        "implementReworkCount": 0,
        "runFailureCounts": {},
        "baseline": {"branch": "main", "head": "a" * 40},
        "candidateFingerprint": None,
        "approvedPlan": None,
        "lastConsumedJobId": None,
        "pendingLifecycle": None,
        "resumeStatus": None,
    }
    data.update(overrides)
    return data


class FakeKanban:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.status = "running"

    def __call__(self, name: str, args: dict, **kwargs) -> str:
        self.calls.append((name, dict(args)))
        if name == "kanban_show":
            return json.dumps(
                {
                    "task": {
                        "id": "t_abc",
                        "status": self.status,
                        "assignee": "autodev",
                        "workspace_kind": "dir",
                        "workspace_path": "/abs/repo",
                        "current_run_id": "7",
                    },
                    "parents": [],
                    "runs": [{"id": "7", "status": "running"}],
                }
            )
        return json.dumps({"ok": True})


class WorkflowToolTests(unittest.TestCase):
    def test_sibling_task_and_forged_targets_are_rejected(self) -> None:
        from hermes_cli.plugins import PluginManager
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override
        from tools.registry import registry

        home = Path(tempfile.mkdtemp(prefix="autodev-tools-"))
        state_root = home / "state"
        state_root.mkdir()
        store = WorkflowStore(str(state_root))
        store.put_manifest(_manifest())
        plugins_root = home / "plugins"
        bundled = home / "bundled-plugins"
        installed = plugins_root / PLUGIN_ID
        entries_before = {entry.name: entry for entry in registry._snapshot_entries()}
        policy_before = dict(registry._plugin_override_policy)
        token = None
        manager = None
        kanban = FakeKanban()
        env = {
            "HERMES_HOME": str(home),
            "HERMES_BUNDLED_PLUGINS": str(bundled),
            "HERMES_ENABLE_PROJECT_PLUGINS": "0",
            "HERMES_KANBAN_TASK": "t_abc",
            "HERMES_KANBAN_BOARD": "project-board",
            "HERMES_KANBAN_RUN_ID": "7",
        }
        try:
            bundled.mkdir()
            plugins_root.mkdir()
            shutil.copytree(
                PLUGIN_ROOT,
                installed,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"),
            )
            (home / "config.yaml").write_text(
                "plugins:\n  enabled:\n    - autonomous-development-workflow\n"
                "  entries:\n    autonomous-development-workflow:\n"
                "      settings:\n"
                f"        state_root: {state_root}\n"
                "        harness_command:\n          - node\n          - /abs/harness.mjs\n",
                encoding="utf-8",
            )
            token = set_hermes_home_override(home)
            from hermes_cli.plugins import PluginContext

            def _dispatch(self, tool_name, args, **kwargs):
                return kanban(tool_name, args, **kwargs)

            with patch.dict(os.environ, env, clear=False), patch.object(
                PluginManager, "_scan_entry_points", lambda self: []
            ), patch.object(PluginContext, "dispatch_tool", _dispatch):
                manager = PluginManager()
                manager.discover_and_load()
                self.assertIsNone(manager._cli_ref)
                loaded = manager._plugins.get(PLUGIN_ID)
                self.assertIsNotNone(loaded)
                sibling = registry.dispatch(
                    "autodev_workflow_advance",
                    {"task_id": "t_sibling"},
                    scope=manager.scope_key,
                )
                sibling_payload = json.loads(sibling) if isinstance(sibling, str) else sibling
                self.assertIn("error", sibling_payload)
                forged = registry.dispatch(
                    "autodev_workflow_advance",
                    {"stage": "implement", "target_status": "completed"},
                    scope=manager.scope_key,
                )
                forged_payload = json.loads(forged) if isinstance(forged, str) else forged
                self.assertIn("error", forged_payload)
                status = registry.dispatch(
                    "autodev_workflow_status",
                    {},
                    scope=manager.scope_key,
                )
                status_payload = json.loads(status) if isinstance(status, str) else status
                self.assertTrue(status_payload.get("ok"), status_payload)
                self.assertEqual(status_payload["workflowStatus"], "planning")
                self.assertTrue(any(name == "kanban_show" for name, _ in kanban.calls))
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

    def test_forbidden_advance_keys_are_stable(self) -> None:
        self.assertIn("stage", FORBIDDEN_ADVANCE_KEYS)
        self.assertIn("target_status", FORBIDDEN_ADVANCE_KEYS)
        self.assertIn("sessionId", FORBIDDEN_ADVANCE_KEYS)


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
