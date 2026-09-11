"""Worker-facing Devflow tool schemas and thin handlers (design §19.5–§19.8).

Handlers build a ``HermesAdapter``, dispatch to ``operations_worker``, and
always return a structured JSON envelope. Visibility is the dispatcher
worker surface: ``HERMES_KANBAN_TASK`` set and not a delegated child.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from .contracts import ContractError
from .errors import (
    CARD_CONTRACT_INVALID,
    HARNESS_STATE_UNAVAILABLE,
    HarnessError,
    error_result,
    failure,
    ok_result,
)
from .hermes_adapter import HermesAdapter
from .operations_worker import (
    BLOCK_KINDS,
    op_implement_handoff,
    op_review_verdict,
    op_start_or_inspect_relay,
    op_ui_lease,
)


def _is_delegated_child_process() -> bool:
    try:
        from agent.delegation_context import is_delegated_child_process_context

        return bool(is_delegated_child_process_context())
    except Exception:
        return bool(os.environ.get("HERMES_DELEGATED_CHILD_CONTEXT"))


def _dispatcher_task_in_env() -> bool:
    return bool((os.environ.get("HERMES_KANBAN_TASK") or "").strip())


def check_worker_tools_available() -> bool:
    """Show Worker tools only on a dispatcher task worker, not delegated children."""
    try:
        if _is_delegated_child_process():
            return False
        return _dispatcher_task_in_env()
    except Exception:  # pragma: no cover - defensive
        return False


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dispatch(op: Callable[..., dict], **kwargs: Any) -> str:
    adapter = HermesAdapter()
    try:
        return ok_result(op(adapter, **kwargs))
    except HarnessError as err:
        return error_result(err)
    except ContractError as exc:
        return error_result(failure(CARD_CONTRACT_INVALID, str(exc)))
    except Exception as exc:
        return error_result(
            failure(
                HARNESS_STATE_UNAVAILABLE,
                f"unexpected harness failure: {exc}",
                detail=str(exc),
            )
        )


DEVFLOW_START_OR_INSPECT_RELAY_SCHEMA = {
    "name": "devflow_start_or_inspect_relay",
    "description": (
        "Worker-only. Derive Relay commissioning from the current Card/run "
        "and spawn, attach, or consume the matching write-mode (Guard) or "
        "read-only review Relay. Do not pass Skill, mode, or model."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "brief_path": {
                "type": "string",
                "description": (
                    "Absolute path to the Relay brief; must cite the Card id. "
                    "Implement lane requires this."
                ),
            },
            "brief_content": {
                "type": "string",
                "description": (
                    "Inline brief text for the review lane (review workers "
                    "have no write tools). The harness validates the same "
                    "contract and persists it into the run-scoped adapter "
                    "directory before spawning. Either brief_path or "
                    "brief_content, never both."
                ),
            },
            "repo": {
                "type": "string",
                "description": (
                    "Absolute git repository path. Required to initialize "
                    "Guard state on the first write-mode attempt."
                ),
            },
            "wait_seconds": {
                "type": "integer",
                "minimum": 0,
                "maximum": 3000,
                "default": 1800,
                "description": (
                    "Wait up to this many seconds for the current Relay "
                    "before returning attach; the effective slice is "
                    "clamped just below the agent sequential-tool ceiling "
                    "(420s by default). Terminal Relays are consumed in "
                    "the same call. Defaults to 1800; on attach, heartbeat "
                    "once and call again. Use 0 only for an immediate "
                    "diagnostic inspection."
                ),
            },
        },
        "required": [],
    },
}

DEVFLOW_UI_LEASE_SCHEMA = {
    "name": "devflow_ui_lease",
    "description": (
        "Implement-worker-only. Acquire, release, or inspect a named UI "
        "acceptance resource (for example obsidian:<vault>). Acquire requires "
        "ui_acceptance=required and a frozen candidate landing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["acquire", "release", "inspect"],
                "description": "Lease action.",
            },
            "resource_id": {
                "type": "string",
                "description": "Named resource id, for example obsidian:acceptance.",
            },
        },
        "required": ["action", "resource_id"],
    },
}

DEVFLOW_IMPLEMENT_HANDOFF_SCHEMA = {
    "name": "devflow_implement_handoff",
    "description": (
        "Implement-worker-only. After a terminal Relay (and candidate/UI/"
        "manual gates when required), complete a direct Card or request "
        "review for write-plan / execute-plan. Writes the candidate manifest "
        "for code stages. plan_path is required for write-plan."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Handoff summary recorded on the closing run.",
            },
            "plan_path": {
                "type": "string",
                "description": "Required for write-plan: absolute Accepted Plan path.",
            },
        },
        "required": ["summary"],
    },
}

DEVFLOW_REVIEW_VERDICT_SCHEMA = {
    "name": "devflow_review_verdict",
    "description": (
        "Review-worker-only. Emit exactly one native action: pass completes, "
        "revise requests changes, blocked is a genuine typed blocker. "
        "pass/revise consume harness-owned run-scoped review evidence only. "
        "blocked requires block_kind."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["pass", "revise", "blocked"],
                "description": "Review verdict.",
            },
            "block_kind": {
                "type": "string",
                "enum": list(BLOCK_KINDS),
                "description": (
                    "Required for blocked: needs_input, capability, "
                    "dependency, or transient."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Required for blocked; used for revise when findings_ref is absent.",
            },
            "findings_ref": {
                "type": "string",
                "description": "Optional findings reference for revise.",
            },
        },
        "required": ["verdict"],
    },
}


def handle_start_or_inspect_relay(args: dict, **_kw: Any) -> str:
    args = args or {}
    return _dispatch(
        op_start_or_inspect_relay,
        brief_path=str(args.get("brief_path") or "").strip(),
        brief_content=args.get("brief_content"),
        repo=_opt_str(args.get("repo")),
        wait_seconds=args.get("wait_seconds"),
    )


def handle_ui_lease(args: dict, **_kw: Any) -> str:
    args = args or {}
    return _dispatch(
        op_ui_lease,
        action=str(args.get("action") or "").strip(),
        resource_id=str(args.get("resource_id") or "").strip(),
    )


def handle_implement_handoff(args: dict, **_kw: Any) -> str:
    args = args or {}
    return _dispatch(
        op_implement_handoff,
        summary=str(args.get("summary") or "").strip(),
        plan_path=_opt_str(args.get("plan_path")),
    )


def handle_review_verdict(args: dict, **_kw: Any) -> str:
    args = args or {}
    verdict = str(args.get("verdict") or "").strip()
    block_kind = _opt_str(args.get("block_kind"))
    if verdict == "blocked" and not block_kind:
        return error_result(
            failure(
                CARD_CONTRACT_INVALID,
                "blocked requires block_kind "
                f"(one of {list(BLOCK_KINDS)})",
            )
        )
    if block_kind is not None and block_kind not in BLOCK_KINDS:
        return error_result(
            failure(
                CARD_CONTRACT_INVALID,
                f"block_kind must be one of {list(BLOCK_KINDS)} "
                f"(got {block_kind!r})",
            )
        )
    return _dispatch(
        op_review_verdict,
        verdict=verdict,
        block_kind=block_kind,
        reason=_opt_str(args.get("reason")),
        findings_ref=_opt_str(args.get("findings_ref")),
    )


TOOLS: list[dict] = [
    {
        "name": "devflow_start_or_inspect_relay",
        "schema": DEVFLOW_START_OR_INSPECT_RELAY_SCHEMA,
        "handler": handle_start_or_inspect_relay,
        "check_fn": check_worker_tools_available,
        "emoji": "📡",
        "toolset": "kanban",
    },
    {
        "name": "devflow_ui_lease",
        "schema": DEVFLOW_UI_LEASE_SCHEMA,
        "handler": handle_ui_lease,
        "check_fn": check_worker_tools_available,
        "emoji": "🔒",
        "toolset": "kanban",
    },
    {
        "name": "devflow_implement_handoff",
        "schema": DEVFLOW_IMPLEMENT_HANDOFF_SCHEMA,
        "handler": handle_implement_handoff,
        "check_fn": check_worker_tools_available,
        "emoji": "📦",
        "toolset": "kanban",
    },
    {
        "name": "devflow_review_verdict",
        "schema": DEVFLOW_REVIEW_VERDICT_SCHEMA,
        "handler": handle_review_verdict,
        "check_fn": check_worker_tools_available,
        "emoji": "⚖️",
        "toolset": "kanban",
    },
]
