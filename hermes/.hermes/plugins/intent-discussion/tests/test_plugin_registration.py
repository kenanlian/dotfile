"""Registration contract for the intent-discussion plugin.

Imports the plugin package the same way as the other intent-discussion tests,
then calls register() with a mock ctx and asserts tool/skill wiring.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PKG = "intent_discussion"


def _ensure_plugin_package() -> None:
    existing = sys.modules.get(PKG)
    if existing is not None and getattr(existing, "__path__", None):
        return
    pkg = types.ModuleType(PKG)
    pkg.__file__ = str(PLUGIN_ROOT / "__init__.py")
    pkg.__path__ = [str(PLUGIN_ROOT)]
    pkg.__package__ = PKG
    sys.modules[PKG] = pkg


def _load_plugin():
    _ensure_plugin_package()
    plugin = sys.modules[PKG]
    if not hasattr(plugin, "register"):
        spec = importlib.util.spec_from_file_location(
            PKG,
            PLUGIN_ROOT / "__init__.py",
            submodule_search_locations=[str(PLUGIN_ROOT)],
        )
        assert spec.loader is not None
        spec.loader.exec_module(plugin)
    return plugin


_ensure_plugin_package()
plugin = _load_plugin()
schemas = importlib.import_module(f"{PKG}.schemas")


class PluginRegistrationTests(unittest.TestCase):
    def test_register_records_tool_and_skill(self) -> None:
        mock_ctx = Mock()

        plugin.register(mock_ctx)

        mock_ctx.register_tool.assert_called_once()
        kwargs = mock_ctx.register_tool.call_args.kwargs
        self.assertEqual(kwargs["name"], "intent_requirement_write")
        self.assertEqual(kwargs["toolset"], "intent_discussion")
        self.assertIs(kwargs["schema"], schemas.REQUIREMENT_WRITE)

        mock_ctx.register_skill.assert_called_once()
        self.assertEqual(mock_ctx.register_skill.call_args.args[0], "intent-discussion")


if __name__ == "__main__":
    unittest.main()
