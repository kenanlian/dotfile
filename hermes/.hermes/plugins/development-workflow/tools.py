"""Agent-facing tool for the development-workflow plugin.

Registers one narrow tool, ``kanban_finalize_intent``, which finalizes a
converged development Card: it validates a complete ``development-task.v1``
replacement body, then calls Hermes Core's
``hermes_cli.kanban_db.specify_triage_task()`` exactly once and verifies the
result by reading the Card back.

Design contract (see the development-workflow layering plan):

* Reuses the Core primitive; never writes SQLite directly and never mutates
  status, claims, or runs on its own.
* Origin/orchestrator-only: delegated-child contexts and dispatcher task
  workers are refused.
* Only ``triage`` Cards may be finalized; ``assignee`` must be empty or the
  literal ``default`` and is always set to ``default``.
* Success is claimed only after a read-back that verifies the exact body,
  the assignee, the ``specified`` event, and the parent-gated ``todo`` or
  promoted ``ready`` status.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

try:  # PyYAML ships with Hermes (plugin manifests need it); degrade loudly if absent.
    import yaml
except ImportError:  # pragma: no cover - defensive
    yaml = None  # type: ignore[assignment]

#: Literal machine profile identity for the development workflow.
DEFAULT_ASSIGNEE = "default"


def _tool_error(message: str, **extra: Any) -> str:
    """JSON error envelope (same shape as tools.registry.tool_error).

    Defined locally so plugin import never depends on the top-level ``tools``
    package resolving cleanly in every working directory.
    """
    result: Dict[str, Any] = {"error": str(message)}
    if extra:
        result.update(extra)
    return json.dumps(result, ensure_ascii=False)


def _tool_result(data=None, **kwargs: Any) -> str:
    """JSON result envelope (same shape as tools.registry.tool_result)."""
    if data is not None:
        return json.dumps(data, ensure_ascii=False)
    return json.dumps(kwargs, ensure_ascii=False)

# ---------------------------------------------------------------------------
# development-task.v1 contract constants
# ---------------------------------------------------------------------------

SCHEMA_ID = "development-task.v1"

VALID_INTENTS = ("draft", "converged")
VALID_EXECUTION_ROUTES = ("pending", "direct", "plan-driven")
VALID_UI_ACCEPTANCE = ("pending", "required", "not-required")
VALID_CODING_AGENTS = ("pi", "cursor", "codex", "opencode")

#: Frontmatter keys allowed by development-task.v1, exactly as settled.
ALLOWED_FRONTMATTER_KEYS = (
    "schema",
    "intent",
    "execution_route",
    "ui_acceptance",
    "manual_acceptance",
    "coding_agent",
)
REQUIRED_FRONTMATTER_KEYS = (
    "schema",
    "intent",
    "execution_route",
    "ui_acceptance",
    "coding_agent",
)

#: Fixed body sections, in order.
REQUIRED_SECTIONS = (
    "Goal",
    "Observable acceptance",
    "Included scope",
    "Non-goals",
    "Settled decisions",
    "Open decisions",
    "Repository grounding",
    "Authority boundaries",
)

#: Statuses recompute_ready treats as "parent complete".
_PARENT_COMPLETE_STATUSES = ("done", "archived")

_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$")


class ContractError(ValueError):
    """Raised when a body does not parse as development-task.v1."""


# ---------------------------------------------------------------------------
# Strict YAML frontmatter parsing (duplicate keys rejected)
# ---------------------------------------------------------------------------

if yaml is not None:

    class _StrictSafeLoader(yaml.SafeLoader):
        """SafeLoader variant that rejects duplicate mapping keys."""

    def _construct_unique_mapping(loader, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    f"duplicate frontmatter key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _StrictSafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
    )


def _split_frontmatter(body: str) -> Tuple[Dict[str, Any], str]:
    """Split a body into (frontmatter mapping, markdown remainder).

    Raises ContractError with a precise message on any parse failure.
    """
    if yaml is None:  # pragma: no cover - defensive
        raise ContractError("PyYAML is unavailable; cannot parse frontmatter")
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractError(
            "body must start with a '---' YAML frontmatter block"
        )
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break
    if close_idx is None:
        raise ContractError("frontmatter is not closed with a second '---' line")
    raw = "\n".join(lines[1:close_idx])
    try:
        data = yaml.load(raw, Loader=_StrictSafeLoader)
    except yaml.YAMLError as exc:
        raise ContractError(f"frontmatter YAML is invalid: {exc}") from exc
    if data is None:
        raise ContractError("frontmatter is empty")
    if not isinstance(data, dict):
        raise ContractError(
            f"frontmatter must be a YAML mapping (got {type(data).__name__})"
        )
    for key in data:
        if not isinstance(key, str):
            raise ContractError(
                f"frontmatter keys must be strings (got {key!r})"
            )
    return data, "\n".join(lines[close_idx + 1 :])


def _split_sections(markdown: str) -> Dict[str, str]:
    """Parse the fixed level-1 sections from the post-frontmatter markdown.

    Enforces: no stray content before the first heading, exactly the required
    headings, in order, each exactly once. Returns heading name -> content.
    """
    found: List[str] = []
    sections: Dict[str, str] = {}
    current: Optional[str] = None
    buffers: Dict[str, List[str]] = {}
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current = match.group(1).strip()
            found.append(current)
            buffers[current] = []
            continue
        if current is None:
            if line.strip():
                raise ContractError(
                    "body contains content before the first '# Goal' section"
                )
            continue  # tolerate blank lines between frontmatter and sections
        buffers[current].append(line)
    if not found:
        raise ContractError("body has no level-1 '#' sections")
    if found != list(REQUIRED_SECTIONS):
        expected = ", ".join(f"'# {name}'" for name in REQUIRED_SECTIONS)
        actual = ", ".join(f"'# {name}'" for name in found)
        raise ContractError(
            "body sections must be exactly the eight fixed sections in order; "
            f"expected [{expected}]; found [{actual}]"
        )
    for name in REQUIRED_SECTIONS:
        sections[name] = "\n".join(buffers[name]).strip()
    return sections


def parse_development_task_body(body: str) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Parse a full development-task.v1 body into (frontmatter, sections)."""
    frontmatter, markdown = _split_frontmatter(body)
    sections = _split_sections(markdown)
    return frontmatter, sections


def validate_converged(frontmatter: Dict[str, Any], sections: Dict[str, str]) -> List[str]:
    """Return the list of contract violations blocking finalization.

    A converged Card must have: the exact schema id, ``intent: converged``,
    a resolved execution route (never ``pending``), a resolved UI acceptance
    (never ``pending``), a supported coding agent, a non-empty Goal, a
    non-empty Observable acceptance, and ``Open decisions`` exactly ``None``.
    """
    violations: List[str] = []

    for key in sorted(set(frontmatter) - set(ALLOWED_FRONTMATTER_KEYS)):
        violations.append(
            f"unknown frontmatter key {key!r}; allowed keys: "
            + ", ".join(ALLOWED_FRONTMATTER_KEYS)
        )
    for key in REQUIRED_FRONTMATTER_KEYS:
        if key not in frontmatter:
            violations.append(f"missing required frontmatter key {key!r}")

    schema = frontmatter.get("schema")
    if "schema" in frontmatter and schema != SCHEMA_ID:
        violations.append(
            f"frontmatter schema must be {SCHEMA_ID!r} (got {schema!r})"
        )

    intent = frontmatter.get("intent")
    if "intent" in frontmatter and intent not in VALID_INTENTS:
        violations.append(
            f"intent must be one of {list(VALID_INTENTS)} (got {intent!r})"
        )
    elif intent != "converged":
        violations.append(
            "intent must be 'converged' before finalization "
            f"(got {intent!r}); converge the Card with the user first"
        )

    route = frontmatter.get("execution_route")
    if "execution_route" in frontmatter and route not in VALID_EXECUTION_ROUTES:
        violations.append(
            "execution_route must be one of "
            f"{list(VALID_EXECUTION_ROUTES)} (got {route!r})"
        )
    elif route == "pending":
        violations.append(
            "execution_route must be resolved to 'direct' or 'plan-driven' "
            "before finalization (got 'pending')"
        )

    ui = frontmatter.get("ui_acceptance")
    if "ui_acceptance" in frontmatter and ui not in VALID_UI_ACCEPTANCE:
        violations.append(
            "ui_acceptance must be one of "
            f"{list(VALID_UI_ACCEPTANCE)} (got {ui!r})"
        )
    elif ui == "pending":
        violations.append(
            "ui_acceptance must be classified as 'required' or 'not-required' "
            "before finalization (got 'pending')"
        )

    agent = frontmatter.get("coding_agent")
    if "coding_agent" in frontmatter and agent not in VALID_CODING_AGENTS:
        violations.append(
            "coding_agent must be one of "
            f"{list(VALID_CODING_AGENTS)} (got {agent!r})"
        )

    manual = frontmatter.get("manual_acceptance")
    if "manual_acceptance" in frontmatter and not isinstance(manual, list):
        violations.append(
            "manual_acceptance, when present, must be a list (got "
            f"{type(manual).__name__})"
        )

    if not sections.get("Goal"):
        violations.append("'# Goal' section is empty; a dispatchable Card needs a goal")
    if not sections.get("Observable acceptance"):
        violations.append(
            "'# Observable acceptance' section is empty; a dispatchable Card "
            "needs observable acceptance criteria"
        )
    open_decisions = sections.get("Open decisions")
    if open_decisions is None:
        violations.append("'# Open decisions' section is missing")
    elif open_decisions != "None":
        violations.append(
            "'# Open decisions' must be exactly 'None' before dispatch (got: "
            f"{open_decisions!r})"
        )

    return violations


# ---------------------------------------------------------------------------
# Context guards (Origin/orchestrator surface only)
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


def check_finalize_intent_available() -> bool:
    """Schema-level gate: hide the tool outside the Origin/orchestrator surface.

    Mirrors the core ``kanban`` orchestrator-mode gate: delegated children and
    dispatcher-scoped task workers never see this tool.
    """
    try:
        if _is_delegated_child_process():
            return False
        if _dispatcher_task_in_env():
            return False
        return True
    except Exception:  # pragma: no cover - defensive
        return False


def _orchestrator_author() -> Optional[str]:
    """Best-effort profile name for the audit comment (profile-safe)."""
    try:
        from hermes_cli.profiles import get_active_profile_name

        return get_active_profile_name() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tool schema + handler
# ---------------------------------------------------------------------------

KANBAN_FINALIZE_INTENT_SCHEMA = {
    "name": "kanban_finalize_intent",
    "description": (
        "Finalize a converged development Card: atomically replace its body "
        "(and optionally its title) with a validated development-task.v1 "
        "contract and promote it from 'triage' via the native Kanban path. "
        "The body must carry frontmatter with schema=development-task.v1, "
        "intent=converged, execution_route=direct|plan-driven, ui_acceptance="
        "required|not-required, and coding_agent=pi|cursor|codex|opencode, "
        "plus the eight fixed sections with a non-empty Goal, a non-empty "
        "Observable acceptance, and Open decisions exactly 'None'. The Card "
        "must be in 'triage' with assignee empty or 'default' (the assignee "
        "is always set to the literal 'default'). After the single atomic "
        "write, the exact body, assignee, the 'specified' event, and the "
        "parent-gated todo/ready state are verified by reading the Card "
        "back. Origin orchestrator sessions only — delegated children and "
        "task workers are refused."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": (
                    "Target Card id. Required: this tool never inherits a "
                    "worker task id from the environment."
                ),
            },
            "body": {
                "type": "string",
                "description": (
                    "Complete replacement Card body: development-task.v1 "
                    "frontmatter followed by the eight fixed sections."
                ),
            },
            "title": {
                "type": "string",
                "description": (
                    "Optional non-blank replacement title for the Card."
                ),
            },
            "board": {
                "type": "string",
                "description": (
                    "Optional explicit board slug; defaults to the active "
                    "board resolution (HERMES_KANBAN_BOARD/HERMES_KANBAN_DB "
                    "env, kanban/current, then 'default')."
                ),
            },
        },
        "required": ["task_id", "body"],
    },
}


def _finalize_refusal(message: str, *, stage: str = "guard", **extra: Any) -> str:
    payload: Dict[str, Any] = {"ok": False, "stage": stage}
    payload.update(extra)
    return _tool_error(message, **payload)


def handle_finalize_intent(args: dict, **kw) -> str:
    """Handler for the kanban_finalize_intent tool."""
    # -- Origin/orchestrator-only guards, before any DB touch ---------------
    if _is_delegated_child_process():
        return _finalize_refusal(
            "kanban_finalize_intent refused: delegate_task child agents are "
            "not intent owners. Return findings to the Origin session; the "
            "Origin default-profile orchestrator must finalize intent.",
            stage="guard",
        )
    if _dispatcher_task_in_env():
        return _finalize_refusal(
            "kanban_finalize_intent refused: dispatcher task workers are not "
            "intent owners; finalize intent from the Origin default-profile "
            "orchestrator session.",
            stage="guard",
        )

    # -- Input shape ---------------------------------------------------------
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return _finalize_refusal(
            "task_id is required (this orchestrator tool never defaults to "
            "an environment task id)",
            stage="input",
        )
    body = args.get("body")
    if not isinstance(body, str) or not body.strip():
        return _finalize_refusal(
            "body is required and must be the complete replacement "
            "development-task.v1 body",
            stage="input",
            task_id=task_id,
        )
    title = args.get("title")
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            return _finalize_refusal(
                "title, when provided, must be a non-blank string",
                stage="input",
                task_id=task_id,
            )
        title = title.strip()
    board = args.get("board")
    if board is not None:
        board = str(board).strip() or None

    # -- Contract validation, before any mutation ----------------------------
    try:
        frontmatter, sections = parse_development_task_body(body)
    except ContractError as exc:
        return _finalize_refusal(
            f"development-task.v1 body does not parse: {exc}",
            stage="contract",
            task_id=task_id,
        )
    violations = validate_converged(frontmatter, sections)
    if violations:
        return _finalize_refusal(
            "development-task.v1 contract violations block finalization: "
            + "; ".join(violations),
            stage="contract",
            task_id=task_id,
            violations=violations,
        )

    # -- Connect with Core's own board resolution precedence -----------------
    from hermes_cli import kanban_db as kb

    try:
        conn = kb.connect(board=board)
    except ValueError as exc:
        return _finalize_refusal(
            f"invalid board {board!r}: {exc}", stage="input", task_id=task_id
        )
    try:
        # -- Precondition: the target Card must be an owned triage Card ------
        task = kb.get_task(conn, task_id)
        if task is None:
            return _finalize_refusal(
                f"task {task_id} not found", stage="precondition", task_id=task_id
            )
        if task.status != "triage":
            return _finalize_refusal(
                f"task {task_id} is '{task.status}'; kanban_finalize_intent "
                "only finalizes 'triage' Cards",
                stage="precondition",
                task_id=task_id,
                status=task.status,
            )
        existing_assignee = (task.assignee or "").strip().lower() or None
        if existing_assignee not in (None, DEFAULT_ASSIGNEE):
            return _finalize_refusal(
                f"task {task_id} is assigned to {existing_assignee!r}; this "
                f"finalizer only owns Cards with assignee {DEFAULT_ASSIGNEE!r}",
                stage="precondition",
                task_id=task_id,
                assignee=existing_assignee,
            )

        # -- The single atomic Core write ------------------------------------
        try:
            specified = kb.specify_triage_task(
                conn,
                task_id,
                title=title,
                body=body,
                assignee=DEFAULT_ASSIGNEE,
                author=_orchestrator_author(),
            )
        except ValueError as exc:
            return _finalize_refusal(
                f"specify_triage_task rejected the update: {exc}",
                stage="precondition",
                task_id=task_id,
            )
        if specified is not True:
            return _finalize_refusal(
                f"task {task_id} was not specified (missing or no longer in "
                "'triage' at write time)",
                stage="precondition",
                task_id=task_id,
            )

        # -- Read-back verification ------------------------------------------
        fresh = kb.get_task(conn, task_id)
        if fresh is None:
            return _finalize_refusal(
                f"task {task_id} vanished after finalization",
                stage="verification",
                task_id=task_id,
            )
        body_ok = (fresh.body or "") == body
        assignee_ok = (fresh.assignee or "") == DEFAULT_ASSIGNEE

        open_parents = []
        for parent_id in kb.parent_ids(conn, task_id):
            parent = kb.get_task(conn, parent_id)
            if parent is None or parent.status not in _PARENT_COMPLETE_STATUSES:
                open_parents.append(parent_id)
        expected_status = "todo" if open_parents else "ready"
        status_ok = fresh.status == expected_status

        specified_event_ok = any(
            event.kind == "specified"
            for event in kb.list_events(conn, task_id)
        )

        if not (body_ok and assignee_ok and status_ok and specified_event_ok):
            failed = [
                name
                for name, ok in (
                    ("body", body_ok),
                    ("assignee", assignee_ok),
                    ("status", status_ok),
                    ("specified_event", specified_event_ok),
                )
                if not ok
            ]
            return _finalize_refusal(
                "read-back verification failed for: " + ", ".join(failed),
                stage="verification",
                task_id=task_id,
                status=fresh.status,
                expected_status=expected_status,
                verified={
                    "body": body_ok,
                    "assignee": assignee_ok,
                    "status": status_ok,
                    "specified_event": specified_event_ok,
                },
            )

        try:
            if board:
                resolved_board = board
            elif (os.environ.get("HERMES_KANBAN_DB") or "").strip():
                # DB path pinned directly: the slug chain (kanban/current,
                # HERMES_KANBAN_BOARD) is not authoritative for this write.
                resolved_board = None
            else:
                resolved_board = kb.get_current_board()
        except Exception:
            resolved_board = None
        return _tool_result(
            {
                "ok": True,
                "task_id": task_id,
                "board": resolved_board,
                "title": fresh.title,
                "status": fresh.status,
                "parent_gated": bool(open_parents),
                "open_parents": open_parents,
                "assignee": fresh.assignee,
                "verified": {
                    "body": body_ok,
                    "assignee": assignee_ok,
                    "status": status_ok,
                    "specified_event": specified_event_ok,
                },
                "message": (
                    "Card finalized via specify_triage_task and verified by "
                    f"read-back; landed in '{fresh.status}'"
                    + (" (parent-gated; promotes to ready when parents complete)"
                       if open_parents else "")
                ),
            }
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass
