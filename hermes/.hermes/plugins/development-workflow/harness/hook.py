"""pre_tool_call safety net for managed development-stage Cards (design §20).

Restricts only literal ``development-stage.v2`` Cards. Origin current-session
direct execution and ordinary (non-development) Kanban work stay unrestricted.
Fail-closed for protected mutations; fast ``None`` for unrelated tools with
zero adapter I/O. Never imports ``hermes_cli`` (adapter only) and never raises.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .context import (
    allowed_actions_for,
    apply_non_owning_quarantine,
    classify_session,
    managed_card,
)
from .contracts import STAGE_SCHEMA_ID, card_schema_id, parse_decision_comment
from .errors import HARNESS_STATE_UNAVAILABLE, RUN_OWNERSHIP_LOST
from .hermes_adapter import HermesAdapter

HOOK_NAME = "pre_tool_call"
DEVFLOW_WRAPPER_HINT = (
    "Use devflow_implement_handoff / devflow_review_verdict for managed "
    "development-stage cards instead of native kanban_complete / "
    "kanban_request_review / kanban_request_changes."
)
_SCRIPT_BYPASS_HINT = (
    "Do not invoke the External Guard or Relay launcher directly; "
    "use devflow_start_or_inspect_relay."
)
_REVIEW_HINT = (
    "Review workers on managed development-stage cards are read-only evidence "
    "validation. Do not mutate the workspace, browser, computer, messaging, "
    "or generic tools; use devflow_inspect / devflow_start_or_inspect_relay / "
    "devflow_review_verdict."
)

_GUARD_SCRIPT_MARKER = "development_external_guard.py"
_RELAY_SCRIPT_MARKER = "pi-delegate/scripts/relay.mjs"

# Read-only tools always allowed, including for quarantined managed roles.
_READ_ONLY = frozenset(
    {
        "read_file",
        "search_files",
        "web_search",
        "web_extract",
        "vision_analyze",
        "video_analyze",
        "browser_snapshot",
        "browser_back",
        "browser_get_images",
        "skills_list",
        "skill_view",
        "session_search",
        "x_search",
        "ha_list_entities",
        "ha_get_state",
        "ha_list_services",
        "kanban_show",
        "kanban_list",
        "kanban_attachments",
        "devflow_inspect",
    }
)
_READ_ONLY_KANBAN = frozenset(
    {"kanban_show", "kanban_list", "kanban_attachments"}
)
_LIFECYCLE_TOOLS = frozenset(
    {"kanban_complete", "kanban_request_review", "kanban_request_changes"}
)
_DEFAULTING_TASK_ID_TOOLS = frozenset(
    {
        "kanban_complete",
        "kanban_block",
        "kanban_request_review",
        "kanban_request_changes",
        "kanban_heartbeat",
        "kanban_attach",
        "kanban_attach_url",
    }
)
_NATIVE_KANBAN = _READ_ONLY_KANBAN | _LIFECYCLE_TOOLS | frozenset(
    {
        "kanban_heartbeat",
        "kanban_unblock",
        "kanban_block",
        "kanban_comment",
        "kanban_attach",
        "kanban_attach_url",
        "kanban_create",
        "kanban_link",
    }
)
# Exact mutator names (browser_* is prefix-matched separately; terminal is
# matched case-insensitively). send_message is kept even if unregistered.
_MUTATORS_EXACT = frozenset(
    {
        "terminal",
        "execute_code",
        "write_file",
        "patch",
        "memory",
        "skill_manage",
        "todo_list",
        "cronjob_manage",
        "delegate_task",
        "process_manage",
        "computer_use",
        "send_message",
        "image_generate",
        "text_to_speech",
        "video_generate",
        "xai_video_edit",
        "xai_video_extend",
        "desktop_project",
        "annotate_preview",
        "apply_layout",
        "react_to_message",
        "setup_mcp",
        "discord",
        "discord_admin",
        "feishu_drive_add_comment",
        "feishu_drive_reply_comment",
        "yb_send_dm",
        "yb_send_sticker",
        "ha_call_service",
    }
)
_REVIEW_ALLOW = _READ_ONLY | frozenset(
    {
        "devflow_start_or_inspect_relay",
        "devflow_review_verdict",
        "kanban_block",
        "kanban_heartbeat",
        "kanban_comment",
        "kanban_attach",
        "kanban_attach_url",
    }
)
_REVIEW_DESCRIBABLE_TOOLS = frozenset(
    {
        "devflow_inspect",
        "devflow_start_or_inspect_relay",
        "devflow_review_verdict",
    }
)
_NON_OWNING_ALLOW = _READ_ONLY | _READ_ONLY_KANBAN | frozenset({"devflow_inspect"})


def _block(message: str) -> dict[str, str]:
    return {"action": "block", "message": str(message)}


def _unavailable(detail: str) -> dict[str, str]:
    return _block(f"{HARNESS_STATE_UNAVAILABLE}: {detail}")


def _env_task_id() -> str | None:
    value = (os.environ.get("HERMES_KANBAN_TASK") or "").strip()
    return value or None


def _is_always_allow(tool_name: str) -> bool:
    return tool_name in _READ_ONLY


def _is_readonly_kanban(tool_name: str) -> bool:
    return tool_name in _READ_ONLY_KANBAN


def _is_browser_mutator(tool_name: str) -> bool:
    """Mutating browser_* family: prefix match, minus the read-only allowlist."""
    return tool_name.startswith("browser_") and tool_name not in _READ_ONLY


def _is_mcp_name(tool_name: str) -> bool:
    return tool_name.startswith("mcp_") or tool_name.startswith("mcp-")


def _in_consideration(tool_name: str) -> bool:
    if tool_name in _NATIVE_KANBAN or tool_name in _MUTATORS_EXACT:
        return True
    if tool_name.lower() == "terminal":
        return True
    if _is_browser_mutator(tool_name):
        return True
    return False


def _stringify_args(args: dict) -> str:
    try:
        return json.dumps(args, default=str, ensure_ascii=False)
    except Exception:
        try:
            return json.dumps(list(args.values()), default=str, ensure_ascii=False)
        except Exception:
            return " ".join(str(value) for value in args.values())


def _arg_str(args: dict, key: str) -> str:
    value = args.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _resolve_task_id(tool_name: str, args: dict) -> str | None:
    explicit = _arg_str(args, "task_id")
    if explicit:
        return explicit
    if tool_name in _DEFAULTING_TASK_ID_TOOLS:
        return _env_task_id()
    return None


def _is_script_bypass(args: dict) -> bool:
    blob = _stringify_args(args)
    return _GUARD_SCRIPT_MARKER in blob or _RELAY_SCRIPT_MARKER in blob


def _body_assembles_v2(body: Any) -> bool:
    if not isinstance(body, str):
        return False
    schema = card_schema_id(body)
    if schema == STAGE_SCHEMA_ID:
        return True
    if schema is None and STAGE_SCHEMA_ID in body:
        return True
    return False


def _non_owning_message() -> str:
    actions = allowed_actions_for("non-owning-worker")
    return (
        f"role=non-owning-worker {RUN_OWNERSHIP_LOST}: this session no "
        "longer owns the current Kanban run. "
        f"allowed_actions={actions}. Stop this session; do not operate "
        "Relay, Git, UI, or Kanban."
    )


def _would_fail_close(tool_name: str, args: dict) -> bool:
    """Whether an internal failure must block rather than fast-allow."""
    if _is_always_allow(tool_name) or _is_readonly_kanban(tool_name):
        return False
    if tool_name in _LIFECYCLE_TOOLS and _resolve_task_id(tool_name, args):
        return True
    if tool_name == "kanban_link" and (
        _arg_str(args, "parent_id") or _arg_str(args, "child_id")
    ):
        return True
    if tool_name == "kanban_create" and _body_assembles_v2(args.get("body")):
        return True
    if _env_task_id():
        return True
    return False


def pre_tool_call(
    tool_name: str = "", args: dict | None = None, **kwargs: Any
) -> dict | None:
    """Veto explicit bypass paths on managed development Cards (§20)."""
    try:
        if not isinstance(args, dict):
            return None
        name = str(tool_name or "")
        if _is_always_allow(name):
            return None
        # Unknown names and mcp_*/mcp-* are not in the consideration set.
        # Origin (no worker env) fast-allows them with zero adapter I/O;
        # a worker env falls through so managed review/non-owning can
        # deny-by-default (_is_mcp_name documents the prefix rule).
        if not _in_consideration(name) and not _env_task_id():
            return None
        return _evaluate_protected(name, args)
    except Exception as exc:
        name = str(tool_name or "")
        raw_args = args if isinstance(args, dict) else {}
        if _is_always_allow(name) or _is_readonly_kanban(name):
            return None
        if _would_fail_close(name, raw_args):
            return _unavailable(f"hook failed: {exc}")
        return None


def _evaluate_protected(tool_name: str, args: dict) -> dict | None:
    adapter: HermesAdapter | None = None
    session = None
    card_cache: dict[str, bool] = {}

    def get_adapter() -> HermesAdapter:
        nonlocal adapter
        if adapter is None:
            adapter = HermesAdapter()
        return adapter

    def get_session():
        nonlocal session
        if session is None:
            session = classify_session(get_adapter())
        return session

    def _is_managed(task_id: str) -> bool:
        key = str(task_id or "").strip()
        if not key:
            return False
        if key in card_cache:
            return card_cache[key]
        conn = None
        try:
            conn = get_adapter().connect()
            task = get_adapter().get_task(conn, key)
            result = task is not None and managed_card(task) is not None
        finally:
            if conn is not None:
                get_adapter().close(conn)
        card_cache[key] = result
        return result

    if _is_script_bypass(args):
        env_tid = _env_task_id()
        if env_tid and _is_managed(env_tid) and get_session().is_worker():
            return _block(_SCRIPT_BYPASS_HINT)

    if tool_name in _LIFECYCLE_TOOLS:
        target = _resolve_task_id(tool_name, args)
        if not target:
            return None
        if _is_managed(target):
            return _block(DEVFLOW_WRAPPER_HINT)
        return None

    if tool_name == "kanban_create":
        if _body_assembles_v2(args.get("body")):
            return _block(
                "Do not assemble development-stage feature Cards with native "
                "kanban_create; use devflow_create_feature."
            )
        return None

    if tool_name == "kanban_link":
        parent_id = _arg_str(args, "parent_id")
        child_id = _arg_str(args, "child_id")
        if (parent_id and _is_managed(parent_id)) or (
            child_id and _is_managed(child_id)
        ):
            return _block(
                "Do not link managed development-stage Cards with native "
                "kanban_link; feature pairs are created by devflow_create_feature."
            )
        return None

    env_tid = _env_task_id()
    if not env_tid or not _is_managed(env_tid):
        return None

    ctx = get_session()
    if ctx.role == "non-owning-worker":
        apply_non_owning_quarantine()
        if tool_name in _NON_OWNING_ALLOW:
            return None
        return _block(_non_owning_message())

    if ctx.role == "review-worker":
        return _review_policy(tool_name, args)

    if ctx.role == "implement-worker":
        return _implement_policy(tool_name, args)

    if ctx.role == "origin":
        return None

    return None


def _review_policy(tool_name: str, args: dict) -> dict | None:
    if tool_name == "tool_describe":
        raw = args.get("names")
        names = [raw] if isinstance(raw, str) else raw
        normalized = {
            str(name).strip()
            for name in names or []
            if isinstance(name, str) and str(name).strip()
        }
        if normalized and normalized <= _REVIEW_DESCRIBABLE_TOOLS:
            return None
        return _block(
            "Review workers may describe only devflow_inspect, "
            "devflow_start_or_inspect_relay, and devflow_review_verdict."
        )
    if tool_name == "tool_search":
        return _block(
            "Review workers use the fixed devflow control surface; describe "
            "the exact allowed devflow tool instead of searching the broader catalog."
        )
    if tool_name == "kanban_block":
        if _arg_str(args, "reason"):
            return None
        return _block(
            "kanban_block is allowed for the current owning review worker "
            "only with a non-blank reason."
        )
    if tool_name == "kanban_comment":
        body = args.get("body")
        comment = body if isinstance(body, str) else ""
        if parse_decision_comment(comment) is not None:
            return _block(
                "Do not forge Origin decision comments via kanban_comment; "
                "Origin records them through devflow_record_decision."
            )
        return None
    if tool_name in _REVIEW_ALLOW:
        return None
    return _block(_REVIEW_HINT)


def _implement_policy(tool_name: str, args: dict) -> dict | None:
    if tool_name == "kanban_block":
        if _arg_str(args, "reason"):
            return None
        return _block(
            "kanban_block is allowed only for the current owning worker with a "
            "non-blank reason. Origin uses devflow_record_decision / "
            "kanban_unblock paths."
        )
    if tool_name == "kanban_heartbeat":
        return None
    if tool_name == "kanban_comment":
        body = args.get("body")
        comment = body if isinstance(body, str) else ""
        if parse_decision_comment(comment) is not None:
            return _block(
                "Do not forge Origin decision comments via kanban_comment; "
                "Origin records them through devflow_record_decision."
            )
        return None
    if tool_name == "kanban_unblock":
        return _block(
            "kanban_unblock is origin-only; workers cannot unblock a Card."
        )
    return None
