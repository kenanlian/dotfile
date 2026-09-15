"""Tool handlers. Registration must stay side-effect free; handlers stay inert until called."""

from __future__ import annotations

import json


def _not_implemented(name: str, **kwargs) -> str:
    del kwargs
    return json.dumps({"ok": False, "error": f"{name} is not implemented"})


def workflow_status(args: dict, **kwargs) -> str:
    del args
    return _not_implemented("autodev_workflow_status", **kwargs)


def workflow_advance(args: dict, **kwargs) -> str:
    del args
    return _not_implemented("autodev_workflow_advance", **kwargs)


def submit_acceptance(args: dict, **kwargs) -> str:
    del args
    return _not_implemented("autodev_workflow_submit_acceptance", **kwargs)
