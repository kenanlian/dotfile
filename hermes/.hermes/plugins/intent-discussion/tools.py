"""Tool handlers for intent-discussion."""

from __future__ import annotations

import json

from .requirement import RequirementError, write_requirement


def requirement_write(args: dict, **kwargs) -> str:
    # Hermes tool-result contract: handlers must return str, not dict.
    try:
        return json.dumps(write_requirement(**args), ensure_ascii=False)
    except RequirementError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
