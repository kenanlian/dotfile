"""RED/GREEN registration contract for the out-of-tree workflow plugin.

Loads the plugin through Hermes' real directory discovery under a temporary
HERMES_HOME. The plugin itself must not import Hermes private modules.
"""

from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_ID = "autonomous-development-workflow"
PLUGIN_VERSION = "0.1.0"
PLUGIN_TOOLSET = "autonomous_development_workflow"
EXPECTED_TOOLS = (
    "autodev_workflow_status",
    "autodev_workflow_advance",
    "autodev_workflow_submit_acceptance",
)
EXPECTED_HOOKS = ("pre_tool_call", "pre_llm_call")
CLI_NAME = "autodev"
HERMES_AGENT_ROOT = Path("/Users/kenan/.hermes/hermes-agent")
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _ensure_hermes_on_path() -> None:
    root = str(HERMES_AGENT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


_ensure_hermes_on_path()


class PluginRegistrationTests(unittest.TestCase):
    def test_plugin_yaml_declares_identity_and_tools(self) -> None:
        from hermes_cli.plugins_manifest import parse_manifest_file

        manifest_path = PLUGIN_ROOT / "plugin.yaml"
        self.assertTrue(manifest_path.is_file(), f"missing {manifest_path}")
        manifest = parse_manifest_file(manifest_path, PLUGIN_ROOT, "user", "")
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.name, PLUGIN_ID)
        self.assertEqual(manifest.version, PLUGIN_VERSION)
        self.assertEqual(tuple(manifest.provides_tools), EXPECTED_TOOLS)

    def test_real_discovery_registers_tools_cli_prompt_without_side_effects(self) -> None:
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override
        from hermes_cli.plugins import PluginManager
        from tools.registry import registry

        self.assertTrue((PLUGIN_ROOT / "plugin.yaml").is_file(), f"missing {PLUGIN_ROOT / 'plugin.yaml'}")
        self.assertTrue((PLUGIN_ROOT / "__init__.py").is_file(), f"missing {PLUGIN_ROOT / '__init__.py'}")

        entries_before = {entry.name: entry for entry in registry._snapshot_entries()}
        policy_before = dict(registry._plugin_override_policy)
        modules_before = {name for name in sys.modules if _is_plugin_module(name)}
        threads_before = _thread_identities()

        home = Path(tempfile.mkdtemp(prefix="autodev-plugin-reg-"))
        bundled = home / "bundled-plugins"
        plugins_root = home / "plugins"
        installed = plugins_root / PLUGIN_ID
        token = None
        manager = None
        env_patch = {
            "HERMES_HOME": str(home),
            "HERMES_BUNDLED_PLUGINS": str(bundled),
            "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        }
        side_effects: list[str] = []

        def _record(kind: str):
            def _raiser(*_args, **_kwargs):
                side_effects.append(kind)
                raise AssertionError(f"register(ctx) must not {kind}")

            return _raiser

        try:
            bundled.mkdir(parents=True)
            plugins_root.mkdir(parents=True)
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
            with patch.dict(os.environ, env_patch, clear=False), patch.object(
                socket, "create_connection", _record("open a network connection")
            ), patch.object(
                socket.socket, "connect", _record("open a network connection")
            ), patch.object(
                socket.socket, "connect_ex", _record("open a network connection")
            ), patch.object(
                sqlite3, "connect", _record("create a database record")
            ), patch.object(
                subprocess, "Popen", _record("start a subprocess")
            ), patch.object(
                subprocess, "run", _record("start a subprocess")
            ), patch.object(
                PluginManager, "_scan_entry_points", lambda self: []
            ):
                manager = PluginManager()
                manager.discover_and_load()

            loaded = manager._plugins.get(PLUGIN_ID)
            self.assertIsNotNone(loaded, "Hermes discovery did not load the workflow plugin")
            self.assertTrue(loaded.enabled, loaded.error)
            self.assertIsNone(loaded.error)

            manifest = loaded.manifest
            self.assertEqual(manifest.name, PLUGIN_ID)
            self.assertEqual(manifest.version, PLUGIN_VERSION)
            self.assertEqual(tuple(manifest.provides_tools), EXPECTED_TOOLS)
            self.assertEqual(set(loaded.tools_registered), set(EXPECTED_TOOLS))
            self.assertEqual(set(loaded.hooks_registered), set(EXPECTED_HOOKS))
            self.assertIn(CLI_NAME, manager._cli_commands)
            self.assertTrue(
                manager._plugin_skills or manager._system_prompt_sections,
                "plugin must register a bundled Skill or a fixed system prompt section",
            )

            entries_after = {entry.name: entry for entry in registry._snapshot_entries()}
            for name, previous in entries_before.items():
                current = entries_after.get(name)
                self.assertIs(
                    current,
                    previous,
                    f"plugin overrode built-in tool {name!r}",
                )
            new_names = set(entries_after) - set(entries_before)
            self.assertEqual(new_names, set(EXPECTED_TOOLS))
            for name in EXPECTED_TOOLS:
                entry = registry.get_entry(name, scope=manager.scope_key)
                self.assertIsNotNone(entry)
                self.assertEqual(entry.toolset, PLUGIN_TOOLSET)

            self.assertEqual(side_effects, [])
            self.assertEqual(_thread_identities() - threads_before, set())
            db_files = [
                path
                for path in home.rglob("*")
                if path.is_file() and path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
            ]
            self.assertEqual(db_files, [], f"register(ctx) created database files: {db_files}")
        finally:
            if manager is not None:
                try:
                    manager.unload()
                except Exception:
                    pass
            _restore_registry(entries_before, policy_before)
            for name in list(sys.modules):
                if name not in modules_before and _is_plugin_module(name):
                    sys.modules.pop(name, None)
            if token is not None:
                reset_hermes_home_override(token)
            shutil.rmtree(home, ignore_errors=True)


def _is_plugin_module(name: str) -> bool:
    return name == "hermes_plugins" or name.startswith("hermes_plugins.")


def _thread_identities() -> set[int]:
    return {thread.ident for thread in threading.enumerate() if thread.ident is not None}


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
