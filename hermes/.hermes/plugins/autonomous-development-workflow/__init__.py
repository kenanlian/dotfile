"""Autonomous development workflow plugin — registration only."""

from __future__ import annotations

from . import schemas, tools

PLUGIN_TOOLSET = "autonomous_development_workflow"
WORKER_PROMPT_SECTION_ID = "autonomous-development-workflow.worker-rules"
WORKER_PROMPT = (
    "For cards bound to autonomous-development.v1, call autodev_workflow_status "
    "then autodev_workflow_advance. Keep advancing while in_progress. Submit "
    "product acceptance only through autodev_workflow_submit_acceptance. Do not "
    "call native kanban_complete, kanban_request_review, kanban_request_changes, "
    "or kanban_block directly."
)


def _on_pre_tool_call(**kwargs) -> None:
    del kwargs
    return None


def _on_pre_llm_call(**kwargs) -> None:
    del kwargs
    return None


def _setup_autodev_cli(subparser) -> None:
    subparser.set_defaults(func=_autodev_cli)


def _autodev_cli(args) -> None:
    del args
    print("autodev CLI is not implemented")


def register(ctx) -> None:
    """Wire documented PluginContext surfaces. Must not start work or I/O."""
    ctx.register_tool(
        name="autodev_workflow_status",
        toolset=PLUGIN_TOOLSET,
        schema=schemas.STATUS,
        handler=tools.workflow_status,
    )
    ctx.register_tool(
        name="autodev_workflow_advance",
        toolset=PLUGIN_TOOLSET,
        schema=schemas.ADVANCE,
        handler=tools.workflow_advance,
    )
    ctx.register_tool(
        name="autodev_workflow_submit_acceptance",
        toolset=PLUGIN_TOOLSET,
        schema=schemas.SUBMIT_ACCEPTANCE,
        handler=tools.submit_acceptance,
    )
    ctx.register_cli_command(
        name="autodev",
        help="Manage external autonomous development workflows",
        setup_fn=_setup_autodev_cli,
        handler_fn=_autodev_cli,
        description="Enqueue, inspect, doctor, reconcile, and abandon autonomous development cards.",
    )
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_system_prompt_section(
        WORKER_PROMPT_SECTION_ID,
        WORKER_PROMPT,
        position="after_memory",
    )
