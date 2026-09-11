"""Real temporary-HERMES_HOME plugin registration and load.

Loads the development-workflow package into an isolated home (never the live
``$HERMES_HOME``), registers the 10-tool surface plus ``pre_tool_call``, then
invokes the registered ``devflow_inspect`` handler against the empty temp
board.

Bootstrap mirrors ``test_finalize_intent.py`` / ``test_plugin_registration.py``:
drop the plugin directory from ``sys.path``, load via ``spec_from_file_location``,
init a real Kanban DB, and symlink ``hermes-agent`` into the temp home.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

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

from hermes_cli import kanban_db as kb

_MODULE_NAME = "devwf_test_plugin_load_temp_home"

_EXPECTED_TOOLS = (
    "devflow_create_feature",
    "devflow_record_decision",
    "devflow_finalize_stage",
    "devflow_inspect",
    "devflow_start_or_inspect_relay",
    "devflow_ui_lease",
    "devflow_implement_handoff",
    "devflow_review_verdict",
    "devflow_publish_candidate",
    "kanban_finalize_intent",
)

_SCRUB_ENV_VARS = (
    "HERMES_KANBAN_DB",
    "HERMES_KANBAN_BOARD",
    "HERMES_KANBAN_HOME",
    "HERMES_KANBAN_WORKSPACES_ROOT",
    "HERMES_KANBAN_WORKSPACE",
    "HERMES_KANBAN_TASK",
    "HERMES_KANBAN_RUN_ID",
    "HERMES_KANBAN_CLAIM_LOCK",
    "HERMES_DELEGATED_CHILD_CONTEXT",
    "HERMES_KANBAN_STOP_NUDGE",
    "HERMES_DEVFLOW_ARTIFACTS_ROOT",
    "HERMES_HOME",
    "HERMES_CRON_SESSION",
)

_REAL_HERMES_HOME = Path.home() / ".hermes"
_REAL_AGENT_CANDIDATES = (
    Path.home() / ".hermes" / "hermes-agent",
    Path("/Users/kenan/.hermes/hermes-agent"),
)


def _load_plugin_package():
    """Load the plugin as a unique package so this test is independent of siblings."""
    if _MODULE_NAME in sys.modules:
        del sys.modules[_MODULE_NAME]
        prefix = _MODULE_NAME + "."
        for key in list(sys.modules):
            if key.startswith(prefix):
                del sys.modules[key]
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


class CapturingCtx:
    def __init__(self) -> None:
        self.tools: list[dict] = []
        self.hooks: list[tuple] = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))


class TestPluginLoadTempHome(unittest.TestCase):
    def setUp(self) -> None:
        real_agent = next(
            (path for path in _REAL_AGENT_CANDIDATES if path.is_dir()),
            None,
        )
        self.assertIsNotNone(
            real_agent,
            "hermes-agent checkout missing; cannot symlink into temp HERMES_HOME",
        )

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / ".hermes"
        self.home.mkdir()
        self._env_backup = os.environ.copy()
        self.addCleanup(self._restore_env)
        os.environ["HERMES_HOME"] = str(self.home)
        for var in _SCRUB_ENV_VARS:
            if var == "HERMES_HOME":
                continue
            os.environ.pop(var, None)
        self._orig_path_home = Path.home
        Path.home = lambda: self.root  # type: ignore[assignment]
        self.addCleanup(setattr, Path, "home", self._orig_path_home)

        (self.home / "config.yaml").write_text(
            "kanban:\n"
            "  max_in_progress: 1\n"
            "  max_in_progress_per_profile: 1\n"
            "  review_dispatch: true\n",
            encoding="utf-8",
        )
        link = self.home / "hermes-agent"
        if not link.exists():
            link.symlink_to(real_agent)

        self.assertEqual(os.environ["HERMES_HOME"], str(self.home))
        self.assertNotEqual(self.home.resolve(), _REAL_HERMES_HOME.resolve())
        kb.init_db()

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_fresh_load_registers_ten_tools_hook_and_inspect_ok(self) -> None:
        plugin = _load_plugin_package()
        ctx = CapturingCtx()
        plugin.register(ctx)

        names = [entry["name"] for entry in ctx.tools]
        self.assertEqual(len(ctx.tools), 10, names)
        self.assertEqual(len(set(names)), 10, names)
        missing = [name for name in _EXPECTED_TOOLS if name not in names]
        self.assertEqual(missing, [], f"missing tools: {missing}; registered: {names}")

        hook_events = [item[0] for item in ctx.hooks]
        self.assertEqual(
            hook_events.count("pre_tool_call"),
            1,
            f"expected one pre_tool_call hook, got {ctx.hooks!r}",
        )
        self.assertTrue(callable(ctx.hooks[0][1]))

        inspect = next(
            (entry for entry in ctx.tools if entry["name"] == "devflow_inspect"),
            None,
        )
        self.assertIsNotNone(inspect, names)
        handler = inspect["handler"]
        self.assertTrue(callable(handler))
        raw = handler({})
        self.assertIsInstance(raw, str)
        payload = json.loads(raw)
        self.assertIsInstance(payload, dict)
        self.assertTrue(
            payload.get("ok") is True,
            f"devflow_inspect did not return an ok envelope: {payload!r}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
