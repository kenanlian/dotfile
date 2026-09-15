"""Intent discussion plugin — registration only."""
from __future__ import annotations

from pathlib import Path

PLUGIN_TOOLSET = "intent_discussion"
SKILL_NAME = "intent-discussion"
SKILL_PATH = Path(__file__).resolve().parent / "skills" / "intent-discussion" / "SKILL.md"

def register(ctx) -> None:
    from . import schemas, tools
    ctx.register_tool(
        name="intent_requirement_write",
        toolset=PLUGIN_TOOLSET,
        schema=schemas.REQUIREMENT_WRITE,
        handler=lambda args, **kwargs: tools.requirement_write(args, **kwargs),
    )
    if SKILL_PATH.is_file():
        ctx.register_skill(SKILL_NAME, SKILL_PATH)
