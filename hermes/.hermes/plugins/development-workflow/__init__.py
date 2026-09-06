"""development-workflow plugin — intent finalization for the development orchestrator.

Registers one narrow tool, ``kanban_finalize_intent``, into the core
``kanban`` toolset so it appears exactly on the orchestrator surface that
already enables Kanban tooling (the Origin default-profile session).
Dispatcher task workers and delegate_task children are refused by both the
schema-level check and the handler itself.
"""

from __future__ import annotations

import logging

from . import tools

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Register the kanban_finalize_intent tool (called by the plugin loader)."""
    ctx.register_tool(
        name="kanban_finalize_intent",
        toolset="kanban",
        schema=tools.KANBAN_FINALIZE_INTENT_SCHEMA,
        handler=tools.handle_finalize_intent,
        check_fn=tools.check_finalize_intent_available,
        emoji="🚦",
    )
