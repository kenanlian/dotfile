"""Plugin settings parsed from an injected plain mapping. No Hermes imports."""

from __future__ import annotations

from typing import Any, Mapping

from .controller.protocol import require_absolute_path
from .controller.types import (
    ALLOWED_ADAPTERS,
    STAGE_AGENT_STAGES,
    THINKING_LEVELS,
    PluginConfig,
    WorkflowProtocolError,
)


def load_plugin_config(raw: Mapping[str, Any] | None) -> PluginConfig:
    """Parse config previously read via ctx.get_config() (or a test double)."""
    if not isinstance(raw, Mapping):
        raise WorkflowProtocolError("plugin config must be a mapping")
    harness_command = _require_argv(raw.get("harness_command"))
    poll = _require_positive_int(raw.get("poll_interval_seconds", 5), "poll_interval_seconds")
    wait = _require_positive_int(raw.get("advance_wait_seconds", 60), "advance_wait_seconds")
    return PluginConfig(
        profile=_optional_nonempty(raw.get("profile"), "profile") or "autodev",
        state_root=require_absolute_path(raw.get("state_root"), "state_root"),
        harness_command=harness_command,
        main_branch=_optional_nonempty(raw.get("main_branch"), "main_branch") or "main",
        poll_interval_seconds=poll,
        advance_wait_seconds=wait,
        stage_agents=_parse_stage_agents(raw.get("stage_agents")),
    )


def _parse_stage_agents(value: Any) -> dict[str, dict[str, str]]:
    """Parse optional per-Stage agent selection (adapter/model/thinking).

    Keys are exact Harness Stages (not profiles) so `implement` and
    `direct_implement` can select different adapters.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise WorkflowProtocolError("stage_agents must be a mapping of stage to adapter selection")
    unknown = set(value) - set(STAGE_AGENT_STAGES)
    if unknown:
        raise WorkflowProtocolError(
            f"stage_agents keys must be stages, got unknown keys {sorted(unknown)}; "
            f"allowed: {sorted(STAGE_AGENT_STAGES)}"
        )
    parsed: dict[str, dict[str, str]] = {}
    for stage, spec in value.items():
        if not isinstance(spec, Mapping):
            raise WorkflowProtocolError(f"stage_agents[{stage}] must be an object")
        extra = set(spec) - {"adapter", "model", "thinking"}
        if extra:
            raise WorkflowProtocolError(f"stage_agents[{stage}] has unknown fields {sorted(extra)}")
        adapter = spec.get("adapter")
        if adapter not in ALLOWED_ADAPTERS:
            raise WorkflowProtocolError(
                f"stage_agents[{stage}].adapter must be one of {sorted(ALLOWED_ADAPTERS)}"
            )
        model = spec.get("model")
        if not isinstance(model, str) or not model.strip():
            raise WorkflowProtocolError(f"stage_agents[{stage}].model must be a non-empty string")
        thinking = spec.get("thinking")
        if thinking not in THINKING_LEVELS:
            raise WorkflowProtocolError(
                f"stage_agents[{stage}].thinking must be one of {sorted(THINKING_LEVELS)}"
            )
        parsed[str(stage)] = {"adapter": str(adapter), "model": model, "thinking": str(thinking)}
    return parsed


def _optional_nonempty(value: Any, what: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorkflowProtocolError(f"{what} must be a string")
    text = value.strip()
    return text or None


def _require_positive_int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkflowProtocolError(f"{what} must be a positive integer")
    return value


def _require_argv(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, list) or not value:
        raise WorkflowProtocolError("harness_command must be a non-empty argv list, not a shell string")
    argv: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise WorkflowProtocolError(
                f"harness_command[{index}] must be a non-empty string"
            )
        argv.append(item)
    return tuple(argv)
