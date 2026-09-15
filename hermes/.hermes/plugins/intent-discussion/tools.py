"""Tool handlers for intent-discussion."""

from __future__ import annotations

from .requirement import RequirementError, write_requirement


def requirement_write(args: dict, **kwargs) -> dict:
    try:
        return write_requirement(**args)
    except RequirementError as exc:
        return {"error": str(exc)}
