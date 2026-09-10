"""development-workflow plugin — v2 harness plus legacy intent finalizer.

Registers ``kanban_finalize_intent`` (development-task.v1, temporary
compat) and the eight Devflow tools, plus a ``pre_tool_call`` safety net.
The legacy finalizer always registers even if the harness surface fails to
import.
"""

from __future__ import annotations

import logging

from . import tools

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Register Devflow tools, the pre_tool_call hook, and the legacy finalizer."""
    origin_tools = worker_tools = hook_mod = None
    try:
        from .harness import hook as hook_mod
        from .harness.tools_origin import TOOLS as origin_tools
        from .harness.tools_worker import TOOLS as worker_tools
    except Exception:
        logger.exception(
            "development-workflow harness failed to import; "
            "kanban_finalize_intent remains available"
        )

    if origin_tools is not None and worker_tools is not None:
        for entry in (*origin_tools, *worker_tools):
            ctx.register_tool(
                name=entry["name"],
                toolset=entry["toolset"],
                schema=entry["schema"],
                handler=entry["handler"],
                check_fn=entry["check_fn"],
                emoji=entry.get("emoji", ""),
            )
        if hook_mod is not None:
            register_hook = getattr(ctx, "register_hook", None)
            if callable(register_hook):
                register_hook("pre_tool_call", hook_mod.pre_tool_call)

    ctx.register_tool(
        name="kanban_finalize_intent",
        toolset="kanban",
        schema=tools.KANBAN_FINALIZE_INTENT_SCHEMA,
        handler=tools.handle_finalize_intent,
        check_fn=tools.check_finalize_intent_available,
        emoji="🚦",
    )
