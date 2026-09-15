"""Autonomous development workflow plugin — registration only."""

from __future__ import annotations

from pathlib import Path

from . import cli, hooks, schemas, tools

PLUGIN_TOOLSET = "autonomous_development_workflow"
WORKER_PROMPT_SECTION_ID = "autonomous-development-workflow.worker-rules"
SKILL_NAME = "autonomous-development-workflow"
SKILL_PATH = (
    Path(__file__).resolve().parent / "skills" / "autonomous-development-workflow" / "SKILL.md"
)
WORKER_PROMPT = (
    "For cards bound to autonomous-development.v1: call autodev_workflow_status first, "
    "then repeatedly call autodev_workflow_advance. While in_progress, keep advancing and "
    "do not emit a completion summary. Use real browser/Obsidian/CLI/app paths only after "
    "acceptance_required. Submit product acceptance only through "
    "autodev_workflow_submit_acceptance; never write product-acceptance JSON yourself. "
    "If you cannot reliably verify real product behavior, submit needs_human with one "
    "explicit question. Do not call native kanban_complete, kanban_request_review, "
    "kanban_request_changes, or kanban_block, and do not shell equivalent hermes kanban "
    "lifecycle commands."
)


def _on_pre_tool_call(**kwargs):
    return hooks.pre_tool_call(**kwargs)


def _on_pre_llm_call(**kwargs) -> None:
    del kwargs
    return None


def _setup_autodev_cli(subparser) -> None:
    cli.setup_autodev_cli(subparser)


def register(ctx) -> None:
    """Wire documented PluginContext surfaces. Must not start work or I/O."""
    ctx.register_tool(
        name="autodev_workflow_status",
        toolset=PLUGIN_TOOLSET,
        schema=schemas.STATUS,
        handler=lambda args, **kwargs: tools.workflow_status(args, ctx=ctx, **kwargs),
    )
    ctx.register_tool(
        name="autodev_workflow_advance",
        toolset=PLUGIN_TOOLSET,
        schema=schemas.ADVANCE,
        handler=lambda args, **kwargs: tools.workflow_advance(args, ctx=ctx, **kwargs),
    )
    ctx.register_tool(
        name="autodev_workflow_submit_acceptance",
        toolset=PLUGIN_TOOLSET,
        schema=schemas.SUBMIT_ACCEPTANCE,
        handler=lambda args, **kwargs: tools.submit_acceptance(args, ctx=ctx, **kwargs),
    )
    ctx.register_cli_command(
        name="autodev",
        help="Manage external autonomous development workflows",
        setup_fn=_setup_autodev_cli,
        handler_fn=lambda args: cli.handle_autodev(args, config_loader=ctx.get_config),
        description="Enqueue, inspect, doctor, reconcile, and abandon autonomous development cards.",
    )
    ctx.register_hook("pre_tool_call", lambda **kwargs: _on_pre_tool_call(ctx=ctx, **kwargs))
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_system_prompt_section(
        WORKER_PROMPT_SECTION_ID,
        WORKER_PROMPT,
        position="after_memory",
    )
    if SKILL_PATH.is_file():
        ctx.register_skill(
            SKILL_NAME,
            SKILL_PATH,
            description="Worker rules for Manifest-bound autonomous development cards.",
        )
