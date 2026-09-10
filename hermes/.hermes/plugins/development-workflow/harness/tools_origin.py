"""Origin-facing Devflow tool schemas and thin handlers (design §19.1–§19.4).

Handlers build a ``HermesAdapter``, dispatch to ``operations_origin``, and
always return a structured JSON envelope. Visibility gates live in this
module so Origin tools stay off the delegated-child and dispatcher-worker
surfaces without importing the legacy ``tools.py``.
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
from .operations_origin import (
    op_create_feature,
    op_finalize_stage,
    op_inspect,
    op_record_decision,
)


# ---------------------------------------------------------------------------
# Surface detection (mirrors legacy tools.py; do not import that module)
# ---------------------------------------------------------------------------


def _is_delegated_child_process() -> bool:
    """True in a delegate_task child process (contextvar or env marker)."""
    try:
        from agent.delegation_context import is_delegated_child_process_context

        return bool(is_delegated_child_process_context())
    except Exception:
        return bool(os.environ.get("HERMES_DELEGATED_CHILD_CONTEXT"))


def _dispatcher_task_in_env() -> bool:
    """True when this process was spawned scoped to a dispatcher Kanban task."""
    return bool((os.environ.get("HERMES_KANBAN_TASK") or "").strip())


def check_origin_tools_available() -> bool:
    """Hide mutating Origin tools from delegated children and task workers."""
    try:
        if _is_delegated_child_process():
            return False
        if _dispatcher_task_in_env():
            return False
        return True
    except Exception:  # pragma: no cover - defensive
        return False


def check_inspect_available() -> bool:
    """Inspect is visible to Origin and workers; not to delegated children."""
    try:
        if _is_delegated_child_process():
            return False
        return True
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
        return error_result(
            failure(CARD_CONTRACT_INVALID, str(exc))
        )
    except Exception as exc:
        return error_result(
            failure(
                HARNESS_STATE_UNAVAILABLE,
                f"unexpected harness failure: {exc}",
                detail=str(exc),
            )
        )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

DEVFLOW_CREATE_FEATURE_SCHEMA = {
    "name": "devflow_create_feature",
    "description": (
        "Origin-only. Create draft development-stage.v2 feature Card(s) in "
        "triage. route=direct creates one direct Card; route=two-stage "
        "atomically creates a write-plan Card and a child execute-plan Card "
        "sharing feature_id. feature_id must be kebab-case. repo is the "
        "absolute git work tree workers operate in (workspace_kind=dir). "
        "Validates board, kanban.max_in_progress=1, "
        "kanban.max_in_progress_per_profile=1, and (two-stage) "
        "review_dispatch. Pins skills to development-orchestrator plus the "
        "adapter skill. Does not dispatch; converge via "
        "devflow_record_decision then devflow_finalize_stage. coding_agent "
        "defaults to pi."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "route": {
                "type": "string",
                "enum": ["direct", "two-stage"],
                "description": "Execution route chosen with the user.",
            },
            "feature_id": {
                "type": "string",
                "description": "Stable kebab-case feature identity for this board.",
            },
            "title": {
                "type": "string",
                "description": "Human Card title.",
            },
            "goal": {
                "type": "string",
                "description": "Initial Goal section content for the draft Card(s).",
            },
            "repo": {
                "type": "string",
                "description": (
                    "Absolute path of the feature repository the workers "
                    "operate in."
                ),
            },
            "included_scope": {
                "type": "string",
                "description": "Optional Included scope draft text (default TBD).",
            },
            "open_items": {
                "type": "string",
                "description": "Optional Open decisions draft text (default TBD).",
            },
            "coding_agent": {
                "type": "string",
                "enum": ["pi", "cursor", "codex", "opencode"],
                "description": "Coding agent for the feature (default pi).",
            },
            "board": {
                "type": "string",
                "description": "Optional board slug; defaults to the current board.",
            },
        },
        "required": ["route", "feature_id", "title", "goal", "repo"],
    },
}

DEVFLOW_RECORD_DECISION_SCHEMA = {
    "name": "devflow_record_decision",
    "description": (
        "Origin-only. Append a schema-typed decision comment on a "
        "development-stage.v2 Card. kind=intent-decision only while the Card "
        "is in triage; kind=amendment and kind=round-authorization only after "
        "finalization (amendment requires affects_accepted_plan; "
        "round-authorization requires round >= 1 and candidate_commit); "
        "kind=manual-verdict requires verdict PASS|FAIL and candidate_commit "
        "(40-hex). decided_by is always origin. Does not edit the Card body."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Target Card id.",
            },
            "kind": {
                "type": "string",
                "enum": [
                    "intent-decision",
                    "amendment",
                    "manual-verdict",
                    "round-authorization",
                ],
                "description": "Decision kind.",
            },
            "decision": {
                "type": "string",
                "description": "Accepted decision text.",
            },
            "affects_accepted_plan": {
                "type": "boolean",
                "description": "Required for amendment: whether Accepted Plan is invalidated.",
            },
            "candidate_commit": {
                "type": "string",
                "description": (
                    "Required for manual-verdict and round-authorization: "
                    "40-char lowercase hex commit."
                ),
            },
            "verdict": {
                "type": "string",
                "enum": ["PASS", "FAIL"],
                "description": "Required for manual-verdict: PASS or FAIL.",
            },
            "round": {
                "type": "integer",
                "description": (
                    "Required for round-authorization: review round number >= 1."
                ),
            },
            "board": {
                "type": "string",
                "description": "Optional board slug; defaults to the current board.",
            },
        },
        "required": ["task_id", "kind", "decision"],
    },
}

DEVFLOW_FINALIZE_STAGE_SCHEMA = {
    "name": "devflow_finalize_stage",
    "description": (
        "Origin-only. Replace a triage development-stage.v2 Card with a "
        "converged body and promote it via native specify_triage_task. "
        "feature_id, stage, and coding_agent are immutable from the draft. "
        "Open decisions must be exactly None. execute-plan requires a live "
        "Accepted Plan identity that exactly matches the same-feature "
        "write-plan PASS handoff metadata. Read-back verifies exact body, "
        "assignee=default, specified event, and parent-gated todo/ready "
        "status. Only triage Cards; assignee must be empty or default."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Target triage Card id.",
            },
            "body": {
                "type": "string",
                "description": (
                    "Complete replacement development-stage.v2 body "
                    "(frontmatter plus the eight fixed sections)."
                ),
            },
            "title": {
                "type": "string",
                "description": "Optional non-blank replacement title.",
            },
            "board": {
                "type": "string",
                "description": "Optional board slug; defaults to the current board.",
            },
        },
        "required": ["task_id", "body"],
    },
}

DEVFLOW_INSPECT_SCHEMA = {
    "name": "devflow_inspect",
    "description": (
        "Read-only reconstruction of feature state from Kanban, Guard, and "
        "plan files. Locator precedence: task_id; else feature_id (exactly "
        "one Card per stage); else the worker HERMES_KANBAN_TASK; else a "
        "bounded board feature list. Never writes. Visible to Origin and "
        "workers, not delegated children."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board": {
                "type": "string",
                "description": "Optional board slug; defaults to the current board.",
            },
            "task_id": {
                "type": "string",
                "description": "Inspect this Card id.",
            },
            "feature_id": {
                "type": "string",
                "description": "Inspect every non-archived stage Card for this feature.",
            },
        },
        "required": [],
    },
}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_create_feature(args: dict, **_kw: Any) -> str:
    args = args or {}
    return _dispatch(
        op_create_feature,
        route=str(args.get("route") or "").strip(),
        feature_id=str(args.get("feature_id") or "").strip(),
        title=str(args.get("title") or "").strip(),
        goal=str(args.get("goal") or "").strip(),
        repo=str(args.get("repo") or "").strip(),
        included_scope=_opt_str(args.get("included_scope")),
        open_items=_opt_str(args.get("open_items")),
        coding_agent=str(args.get("coding_agent") or "pi").strip() or "pi",
        board=_opt_str(args.get("board")),
    )


def _opt_round(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def handle_record_decision(args: dict, **_kw: Any) -> str:
    args = args or {}
    flag = args.get("affects_accepted_plan")
    if flag is not None:
        flag = bool(flag)
    return _dispatch(
        op_record_decision,
        task_id=str(args.get("task_id") or "").strip(),
        kind=str(args.get("kind") or "").strip(),
        decision=str(args.get("decision") or "").strip(),
        affects_accepted_plan=flag,
        candidate_commit=_opt_str(args.get("candidate_commit")),
        verdict=_opt_str(args.get("verdict")),
        round=_opt_round(args.get("round")),
        board=_opt_str(args.get("board")),
    )


def handle_finalize_stage(args: dict, **_kw: Any) -> str:
    args = args or {}
    body = args.get("body")
    if not isinstance(body, str):
        body = "" if body is None else str(body)
    return _dispatch(
        op_finalize_stage,
        task_id=str(args.get("task_id") or "").strip(),
        body=body,
        title=_opt_str(args.get("title")),
        board=_opt_str(args.get("board")),
    )


def handle_inspect(args: dict, **_kw: Any) -> str:
    args = args or {}
    return _dispatch(
        op_inspect,
        board=_opt_str(args.get("board")),
        task_id=_opt_str(args.get("task_id")),
        feature_id=_opt_str(args.get("feature_id")),
    )


TOOLS: list[dict] = [
    {
        "name": "devflow_create_feature",
        "schema": DEVFLOW_CREATE_FEATURE_SCHEMA,
        "handler": handle_create_feature,
        "check_fn": check_origin_tools_available,
        "emoji": "🌱",
        "toolset": "kanban",
    },
    {
        "name": "devflow_record_decision",
        "schema": DEVFLOW_RECORD_DECISION_SCHEMA,
        "handler": handle_record_decision,
        "check_fn": check_origin_tools_available,
        "emoji": "📌",
        "toolset": "kanban",
    },
    {
        "name": "devflow_finalize_stage",
        "schema": DEVFLOW_FINALIZE_STAGE_SCHEMA,
        "handler": handle_finalize_stage,
        "check_fn": check_origin_tools_available,
        "emoji": "🚦",
        "toolset": "kanban",
    },
    {
        "name": "devflow_inspect",
        "schema": DEVFLOW_INSPECT_SCHEMA,
        "handler": handle_inspect,
        "check_fn": check_inspect_available,
        "emoji": "🔎",
        "toolset": "kanban",
    },
]
