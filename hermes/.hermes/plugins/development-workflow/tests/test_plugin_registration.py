"""Plugin registration wiring for the development-workflow harness surface.

Bootstrap mirrors ``test_finalize_intent.py``: drop the plugin directory from
``sys.path`` and load the package via ``spec_from_file_location``.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path

import yaml

PLUGIN_DIR = Path(__file__).resolve().parent.parent

for _entry in list(sys.path):
    try:
        if Path(_entry).resolve() == PLUGIN_DIR:
            sys.path.remove(_entry)
    except OSError:
        continue

try:
    import hermes_cli.kanban_db  # noqa: F401
except ImportError:
    _runtime_candidates = [
        Path.home() / ".hermes" / "hermes-agent",
        Path("/Users/kenan/.hermes/hermes-agent"),
    ]
    for _candidate in _runtime_candidates:
        if (_candidate / "hermes_cli" / "kanban_db.py").exists():
            sys.path.insert(0, str(_candidate))
            break
    import hermes_cli.kanban_db  # noqa: F401

_MODULE_NAME = "devwf_test_development_workflow"


def _load_plugin_package():
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    init_file = PLUGIN_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, init_file, submodule_search_locations=[str(PLUGIN_DIR)]
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load plugin package from {init_file}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _MODULE_NAME
    module.__path__ = [str(PLUGIN_DIR)]
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_plugin = _load_plugin_package()
tools_origin = importlib.import_module(_MODULE_NAME + ".harness.tools_origin")
tools_worker = importlib.import_module(_MODULE_NAME + ".harness.tools_worker")

_NAME_RE = re.compile(r"^devflow_[a-z_]+$|^kanban_finalize_intent$")
_VISIBILITY_ENV = (
    "HERMES_KANBAN_TASK",
    "HERMES_KANBAN_RUN_ID",
    "HERMES_KANBAN_CLAIM_LOCK",
    "HERMES_DELEGATED_CHILD_CONTEXT",
)


class FakeCtx:
    def __init__(self) -> None:
        self.tools: list[dict] = []
        self.hooks: list[tuple] = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))


class TestPluginRegistration(unittest.TestCase):
    def test_register_wires_nine_tools_and_hook(self) -> None:
        ctx = FakeCtx()
        _plugin.register(ctx)
        self.assertEqual(len(ctx.tools), 9)
        names = [entry["name"] for entry in ctx.tools]
        self.assertEqual(len(set(names)), 9)
        for entry in ctx.tools:
            self.assertEqual(entry.get("toolset"), "kanban")
            self.assertRegex(entry["name"], _NAME_RE)
            schema = entry.get("schema")
            self.assertIsInstance(schema, dict)
            self.assertIn("name", schema)
            self.assertIn("description", schema)
            self.assertIn("parameters", schema)
            self.assertTrue(callable(entry.get("handler")))
            self.assertTrue(callable(entry.get("check_fn")))
        hook_events = [item[0] for item in ctx.hooks]
        self.assertEqual(hook_events.count("pre_tool_call"), 1)
        self.assertTrue(callable(ctx.hooks[0][1]))

        manifest = yaml.safe_load(
            (PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(str(manifest.get("version")), "0.2.0")
        self.assertEqual(manifest.get("kind"), "standalone")
        provided = list(manifest.get("provides_tools") or [])
        self.assertTrue(set(names).issubset(set(provided)))
        self.assertIn("pre_tool_call", manifest.get("provides_hooks") or [])

    def test_check_fn_visibility(self) -> None:
        origin_tools = [
            entry
            for entry in tools_origin.TOOLS
            if entry["name"] != "devflow_inspect"
        ]
        inspect = next(
            entry for entry in tools_origin.TOOLS if entry["name"] == "devflow_inspect"
        )
        worker_tools = list(tools_worker.TOOLS)
        backup = {key: os.environ.get(key) for key in _VISIBILITY_ENV}

        def restore() -> None:
            for key, value in backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)

        def _scrub() -> None:
            for key in _VISIBILITY_ENV:
                os.environ.pop(key, None)

        try:
            _scrub()
            for entry in origin_tools:
                self.assertTrue(entry["check_fn"](), entry["name"])
            self.assertTrue(inspect["check_fn"]())
            for entry in worker_tools:
                self.assertFalse(entry["check_fn"](), entry["name"])

            os.environ["HERMES_KANBAN_TASK"] = "t_worker"
            for entry in origin_tools:
                self.assertFalse(entry["check_fn"](), entry["name"])
            self.assertTrue(inspect["check_fn"]())
            for entry in worker_tools:
                self.assertTrue(entry["check_fn"](), entry["name"])

            os.environ["HERMES_DELEGATED_CHILD_CONTEXT"] = "1"
            for entry in (*origin_tools, inspect, *worker_tools):
                self.assertFalse(entry["check_fn"](), entry["name"])
        finally:
            _scrub()


if __name__ == "__main__":
    unittest.main(verbosity=2)
