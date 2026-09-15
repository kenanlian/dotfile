"""Import plugin code without putting the plugin root on ``sys.path``.

Unittest discover adds this tests directory to ``sys.path``. Inserting the
plugin root there would make top-level names such as ``tools`` and ``config``
shadow Hermes packages (``tools.registry``) and other plugins. Future tests
should load plugin modules through :func:`import_plugin` instead of
``sys.path`` mutation.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PACKAGE = "autodev_workflow_plugin"


def import_plugin(dotted: str):
    """Return ``PLUGIN_ROOT`` submodule *dotted*, e.g. ``controller.protocol``."""
    _ensure_plugin_package()
    return importlib.import_module(f"{PLUGIN_PACKAGE}.{dotted}")


def _ensure_plugin_package() -> None:
    existing = sys.modules.get(PLUGIN_PACKAGE)
    if existing is not None and list(getattr(existing, "__path__", [])) == [str(PLUGIN_ROOT)]:
        return
    package = types.ModuleType(PLUGIN_PACKAGE)
    package.__file__ = str(PLUGIN_ROOT / "__init__.py")
    package.__path__ = [str(PLUGIN_ROOT)]  # type: ignore[attr-defined]
    package.__package__ = PLUGIN_PACKAGE
    sys.modules[PLUGIN_PACKAGE] = package
