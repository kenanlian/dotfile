"""Origin-side Development Workflow operations (design §12, §19.1–§19.4).

``op_create_feature``, ``op_record_decision``, ``op_finalize_stage`` are
Origin-only mutating wrappers around native Kanban primitives.
``op_inspect`` is read-only for every classified role.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, NoReturn

from .context import allowed_actions_for, classify_session
from .contracts import (
    CODING_AGENTS,
    ContractError,
    DECISION_KINDS,
    STAGE_SCHEMA_ID,
    STAGES,
    StageCard,
    card_schema_id,
    encode_decision_comment,
    parse_decision_comment,
    parse_stage_body,
    validate_decision,
    validate_stage_card,
)
from .errors import (
    ADAPTER_CAPABILITY_MISSING,
    CARD_CONTRACT_INVALID,
    DRAFT_NOT_DISPATCHABLE,
    FEATURE_STAGE_CONFLICT,
    HARNESS_INCOMPATIBLE,
    HARNESS_STATE_UNAVAILABLE,
    HarnessError,
    ORIGIN_ROLE_REQUIRED,
    PLAN_IDENTITY_MISSING,
    PLAN_SHA_MISMATCH,
    WORKSPACE_INVALID,
    failure,
)
from .policy import check_adapter_capability, pinned_worker_skills

DEFAULT_ASSIGNEE = "default"
_PARENT_COMPLETE_STATUSES = frozenset({"done", "archived"})
_ROUTES = ("direct", "two-stage")
_FEATURE_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_NEXT_DIRECT = (
    "Record accepted intent with devflow_record_decision, then submit a "
    "converged development-stage.v2 body via devflow_finalize_stage."
)
_NEXT_TWO_STAGE = (
    "Finalize write-plan first; keep execute-plan in triage until the native "
    "write-plan handoff supplies Accepted Plan path, sha256, and card id."
)

_RECOVERY = {
    ("origin", "triage"): (
        "converge via devflow_record_decision then devflow_finalize_stage"
    ),
    ("origin", "ready"): "wait for Dispatcher to claim, or inspect if stuck",
    ("origin", "todo"): "parent-gated; wait for parents to complete",
    ("origin", "blocked"): (
        "inspect blockers and unblock after a recorded Origin decision"
    ),
    ("origin", "review"): "wait for the Review Worker; do not start a Relay",
    ("origin", "running"): "wait for the owning Worker; inspect only",
    ("implement-worker", None): (
        "rebuild from Kanban, Guard, and Git; attach a live Relay, never guess a new session"
    ),
    ("review-worker", None): (
        "start a fresh read-only review relay for the current candidate"
    ),
    ("non-owning-worker", None): (
        "read-only inspect then exit; do not mutate Kanban, Git, Guard, or UI"
    ),
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fail(ctx: Any, code: str, message: str, **details: Any) -> NoReturn:
    kwargs: dict[str, Any] = dict(details)
    if ctx is not None:
        kwargs["current_state"] = ctx.current_state()
        kwargs["allowed_actions"] = allowed_actions_for(ctx.role)
    raise failure(code, message, **kwargs)


def _require_origin(ctx: Any) -> None:
    if ctx.role != "origin":
        _fail(
            ctx,
            ORIGIN_ROLE_REQUIRED,
            f"this action requires an Origin session (role is {ctx.role!r})",
            remediation=(
                "run this from the default-profile Origin orchestrator session"
            ),
        )


def _require_probe(adapter: Any, ctx: Any) -> None:
    probe = adapter.probe()
    if probe.get("ok") is False:
        missing = probe.get("missing") or []
        _fail(
            ctx,
            HARNESS_INCOMPATIBLE,
            "Hermes adapter is missing required capabilities",
            missing=missing,
        )


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _resolve_board(adapter: Any, board: str | None, ctx: Any) -> str:
    resolved = (board or "").strip() or None
    if not resolved:
        try:
            current = adapter.get_current_board()
        except Exception as exc:
            _fail(ctx, WORKSPACE_INVALID, f"cannot resolve current board: {exc}")
        resolved = str(current).strip() if current else None
    if not resolved:
        _fail(ctx, WORKSPACE_INVALID, "no board specified and no current board")
    try:
        exists = adapter.board_exists(resolved)
    except Exception as exc:
        _fail(
            ctx,
            WORKSPACE_INVALID,
            f"board lookup failed for {resolved!r}: {exc}",
            board=resolved,
        )
    if not exists:
        _fail(
            ctx,
            WORKSPACE_INVALID,
            f"board {resolved!r} does not exist",
            board=resolved,
        )
    return resolved


def _resolve_feature_repo(ctx: Any, repo: str) -> str:
    """Validate ``repo`` as an absolute existing git work tree; return resolved path."""
    if _blank(repo):
        _fail(
            ctx,
            WORKSPACE_INVALID,
            "repo is required and must be an absolute git work tree",
        )
    raw = repo.strip()
    path = Path(raw)
    if not path.is_absolute():
        _fail(
            ctx,
            WORKSPACE_INVALID,
            "repo must be an absolute path",
            repo=raw,
        )
    resolved = path.resolve()
    if not resolved.is_dir():
        _fail(
            ctx,
            WORKSPACE_INVALID,
            "repo is not an existing directory",
            repo=str(resolved),
        )
    try:
        completed = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _fail(
            ctx,
            WORKSPACE_INVALID,
            f"git work-tree probe failed: {exc}",
            repo=str(resolved),
        )
    stdout = (completed.stdout or "").strip().lower()
    if completed.returncode != 0 or stdout != "true":
        _fail(
            ctx,
            WORKSPACE_INVALID,
            "repo is not a git work tree",
            repo=str(resolved),
        )
    return str(resolved)


def _pinned_skills(ctx: Any, coding_agent: str) -> list[str]:
    try:
        return list(pinned_worker_skills(coding_agent))
    except HarnessError as err:
        _fail(ctx, err.code, err.message, **err.details)


def _connect(adapter: Any, board: str | None, ctx: Any) -> Any:
    try:
        return adapter.connect(board=board)
    except ValueError as exc:
        _fail(
            ctx,
            WORKSPACE_INVALID,
            f"invalid board {board!r}: {exc}",
            board=board,
        )
    except Exception as exc:
        _fail(ctx, HARNESS_STATE_UNAVAILABLE, f"kanban connect failed: {exc}")


def _check_kanban_preconditions(adapter: Any, ctx: Any, *, route: str) -> None:
    kanban = adapter.kanban_config() or {}
    if not isinstance(kanban, dict):
        kanban = {}
    offending: dict[str, Any] = {}
    mip = kanban.get("max_in_progress")
    if mip != 1:
        offending["max_in_progress"] = mip
    mipp = kanban.get("max_in_progress_per_profile")
    if mipp != 1:
        offending["max_in_progress_per_profile"] = mipp
    if route == "two-stage" and not kanban.get("review_dispatch"):
        offending["review_dispatch"] = kanban.get("review_dispatch")
    if offending:
        keys = ", ".join(offending)
        _fail(
            ctx,
            HARNESS_INCOMPATIBLE,
            f"kanban config is incompatible with feature creation ({keys})",
            **offending,
        )


def _draft_body(
    *,
    feature_id: str,
    stage: str,
    goal: str,
    coding_agent: str,
    included_scope: str | None,
    open_items: str | None,
) -> str:
    """Build a draft ``development-stage.v2`` body (design §12.2 / §12.3)."""
    scope = (
        included_scope.strip()
        if isinstance(included_scope, str) and included_scope.strip()
        else "TBD"
    )
    open_decisions = (
        open_items.strip()
        if isinstance(open_items, str) and open_items.strip()
        else "TBD"
    )
    return (
        "---\n"
        f"schema: {STAGE_SCHEMA_ID}\n"
        f"feature_id: {feature_id}\n"
        f"stage: {stage}\n"
        "intent: draft\n"
        "ui_acceptance: pending\n"
        "manual_acceptance: []\n"
        f"coding_agent: {coding_agent}\n"
        "accepted_plan: null\n"
        "---\n"
        "\n"
        f"# Goal\n\n{goal.strip()}\n\n"
        "# Observable acceptance\n\nTBD\n\n"
        f"# Included scope\n\n{scope}\n\n"
        "# Non-goals\n\nNone\n\n"
        "# Settled decisions\n\nNone\n\n"
        f"# Open decisions\n\n{open_decisions}\n\n"
        "# Repository grounding\n\nNone\n\n"
        "# Authority boundaries\n\nTBD\n"
    )


def _validated_draft_body(
    ctx: Any,
    *,
    feature_id: str,
    stage: str,
    goal: str,
    coding_agent: str,
    included_scope: str | None,
    open_items: str | None,
) -> str:
    body = _draft_body(
        feature_id=feature_id,
        stage=stage,
        goal=goal,
        coding_agent=coding_agent,
        included_scope=included_scope,
        open_items=open_items,
    )
    try:
        card = parse_stage_body(body)
    except ContractError as exc:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"generated draft body does not parse: {exc}",
        )
    violations = validate_stage_card(card, require="draft")
    if violations:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            "generated draft body failed contract validation: "
            + "; ".join(violations),
            violations=violations,
        )
    return body


def _parse_dev_card(task: Any) -> StageCard | None:
    body = getattr(task, "body", None) or ""
    try:
        return parse_stage_body(body)
    except ContractError:
        return None


def _scan_dev_cards(adapter: Any, conn: Any) -> list[tuple[Any, StageCard]]:
    found: list[tuple[Any, StageCard]] = []
    for task in adapter.list_tasks(conn, include_archived=False) or []:
        card = _parse_dev_card(task)
        if card is None:
            continue
        found.append((task, card))
    return found


def _conflicting_ids(
    adapter: Any,
    conn: Any,
    *,
    feature_id: str,
    stage: str,
    exclude_task_id: str | None = None,
) -> list[str]:
    ids: list[str] = []
    for task, card in _scan_dev_cards(adapter, conn):
        if exclude_task_id and task.id == exclude_task_id:
            continue
        if card.feature_id == feature_id and card.stage == stage:
            ids.append(task.id)
    return ids


def _assert_feature_stage_free(
    adapter: Any,
    conn: Any,
    ctx: Any,
    *,
    feature_id: str,
    stages: tuple[str, ...],
    exclude_task_id: str | None = None,
) -> None:
    for stage in stages:
        existing = _conflicting_ids(
            adapter,
            conn,
            feature_id=feature_id,
            stage=stage,
            exclude_task_id=exclude_task_id,
        )
        if existing:
            _fail(
                ctx,
                FEATURE_STAGE_CONFLICT,
                f"feature {feature_id!r} already has a non-archived "
                f"{stage!r} Card",
                feature_id=feature_id,
                stage=stage,
                existing_task_ids=existing,
            )


def _card_title(title: str, *, stage: str, route: str) -> str:
    if route == "direct":
        return title
    return f"{title} ({stage})"


def _author(adapter: Any) -> str:
    try:
        name = adapter.active_profile_name()
    except Exception:
        name = ""
    return str(name or "").strip() or "origin"


def _task_snapshot(task: Any, stage: str) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "stage": stage,
        "status": task.status,
        "title": task.title,
        "assignee": getattr(task, "assignee", None),
        "workspace_kind": getattr(task, "workspace_kind", None),
        "workspace_path": getattr(task, "workspace_path", None),
        "skills": list(getattr(task, "skills", None) or []),
    }


def _verify_created_card(
    adapter: Any,
    conn: Any,
    task_id: str,
    *,
    feature_id: str,
    stage: str,
    workspace_path: str,
    skills: list[str],
) -> tuple[Any, StageCard | None, list[str]]:
    problems: list[str] = []
    task = adapter.get_task(conn, task_id)
    if task is None:
        return None, None, [f"card {task_id} missing after create"]
    if task.status != "triage":
        problems.append(
            f"card {task_id} status is {task.status!r}, expected 'triage'"
        )
    if (getattr(task, "assignee", None) or "") != DEFAULT_ASSIGNEE:
        problems.append(
            f"card {task_id} assignee is {task.assignee!r}, "
            f"expected {DEFAULT_ASSIGNEE!r}"
        )
    if getattr(task, "workspace_kind", None) != "dir":
        problems.append(
            f"card {task_id} workspace_kind is {task.workspace_kind!r}, "
            "expected 'dir'"
        )
    if getattr(task, "workspace_path", None) != workspace_path:
        problems.append(
            f"card {task_id} workspace_path is {task.workspace_path!r}, "
            f"expected {workspace_path!r}"
        )
    actual_skills = list(getattr(task, "skills", None) or [])
    if sorted(actual_skills) != sorted(skills):
        problems.append(
            f"card {task_id} skills are {actual_skills!r}, expected {skills!r}"
        )
    body = getattr(task, "body", None) or ""
    if card_schema_id(body) != STAGE_SCHEMA_ID:
        problems.append(
            f"card {task_id} schema is not {STAGE_SCHEMA_ID}"
        )
    try:
        card = parse_stage_body(body)
    except ContractError as exc:
        problems.append(f"card {task_id} is not {STAGE_SCHEMA_ID}: {exc}")
        return task, None, problems
    if card.feature_id != feature_id:
        problems.append(
            f"card {task_id} feature_id is {card.feature_id!r}, "
            f"expected {feature_id!r}"
        )
    if card.stage != stage:
        problems.append(
            f"card {task_id} stage is {card.stage!r}, expected {stage!r}"
        )
    return task, card, problems


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted_plan_live(accepted_plan: Any) -> dict[str, Any] | None:
    if not isinstance(accepted_plan, dict):
        return None
    path_raw = accepted_plan.get("path")
    expected = accepted_plan.get("sha256")
    info: dict[str, Any] = {
        "path": path_raw,
        "exists": False,
        "sha_match": False,
    }
    if not isinstance(path_raw, str) or not path_raw:
        return info
    path = Path(path_raw)
    if not path.is_file():
        return info
    info["exists"] = True
    try:
        data = path.read_bytes()
    except OSError:
        return info
    info["empty"] = len(data) == 0
    actual = hashlib.sha256(data).hexdigest()
    info["sha256"] = actual
    info["sha_match"] = actual == expected
    return info


def _unmet_requirements(card: StageCard) -> list[str]:
    unmet: list[str] = []
    if card.intent == "draft":
        if card.sections.get("Open decisions") != "None":
            unmet.append("Open decisions not None")
        if card.stage == "execute-plan" and not card.accepted_plan:
            unmet.append("accepted_plan identity missing")
        if card.ui_acceptance == "pending":
            unmet.append("ui_acceptance still pending")
    else:
        unmet.extend(validate_stage_card(card, require="converged"))
    return unmet


def _recovery_advice(role: str, status: str | None) -> str:
    if (role, status) in _RECOVERY:
        return _RECOVERY[(role, status)]
    if (role, None) in _RECOVERY:
        return _RECOVERY[(role, None)]
    return "inspect persistent Kanban, Guard, and Git facts before acting"


def _load_mapping_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": str(exc)}
    stripped = text.strip()
    if not stripped:
        return {}
    data: Any = None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        try:
            import yaml

            data = yaml.safe_load(stripped)
        except Exception:
            return {"error": "unreadable guard state"}
    if not isinstance(data, dict):
        return {"error": "guard state is not a mapping"}
    return data


def _guard_summary(adapter: Any, board: str, card_id: str) -> dict[str, Any] | None:
    root = Path(adapter.artifacts_root)
    path = root / board / "tasks" / card_id / "external-execution.json"
    data = _load_mapping_file(path)
    if data is None:
        return None
    if "error" in data and set(data) == {"error"}:
        return data
    attempts = data.get("attempts") if isinstance(data.get("attempts"), list) else []
    landings = data.get("landings") if isinstance(data.get("landings"), list) else []
    last = attempts[-1] if attempts else None
    last_summary = None
    if isinstance(last, dict):
        last_summary = {
            "state": last.get("state"),
            "operation": last.get("operation"),
            "session_id": last.get("session_id"),
        }
    landing_rows = []
    for item in landings:
        if not isinstance(item, dict):
            continue
        landing_rows.append(
            {
                "attempt_number": item.get("attempt_number"),
                "commit": item.get("commit"),
            }
        )
    return {
        "schema": data.get("schema"),
        "attempts": len(attempts),
        "last_attempt": last_summary,
        "landings": landing_rows,
        "path": str(path),
    }


def _decision_comments(adapter: Any, conn: Any, task_id: str) -> list[dict[str, Any]]:
    comments = []
    for comment in adapter.list_comments(conn, task_id) or []:
        parsed = parse_decision_comment(getattr(comment, "body", None) or "")
        if parsed is None:
            continue
        comments.append(
            {
                "comment_id": getattr(comment, "id", None),
                "author": getattr(comment, "author", None),
                "created_at": getattr(comment, "created_at", None),
                "decision": parsed,
            }
        )
    return comments


def _pair_summary(
    adapter: Any,
    conn: Any,
    task_id: str,
    feature_id: Any,
) -> list[dict[str, Any]]:
    pair: list[dict[str, Any]] = []
    seen = {task_id}

    def _add(other_id: str, relation: str) -> None:
        if not other_id or other_id in seen:
            return
        other = adapter.get_task(conn, other_id)
        if other is None:
            return
        card = _parse_dev_card(other)
        if card is None:
            return
        if feature_id and card.feature_id != feature_id:
            return
        seen.add(other_id)
        pair.append(
            {
                "task_id": other.id,
                "relation": relation,
                "stage": card.stage,
                "status": other.status,
                "title": other.title,
            }
        )

    for parent_id in adapter.parent_ids(conn, task_id) or []:
        _add(parent_id, "parent")
    for child_id in adapter.child_ids(conn, task_id) or []:
        _add(child_id, "child")
    if feature_id:
        for task, card in _scan_dev_cards(adapter, conn):
            if task.id in seen:
                continue
            if card.feature_id == feature_id:
                relation = "same-feature"
                _add(task.id, relation)
    return pair


def _summarize_card(
    adapter: Any,
    conn: Any,
    task: Any,
    board: str,
    ctx: Any,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "task_id": task.id,
        "title": task.title,
        "status": task.status,
        "assignee": task.assignee,
        "board": board,
    }
    try:
        card = parse_stage_body(task.body or "")
    except ContractError as exc:
        summary["contract_invalid"] = str(exc)
        summary["unmet_requirements"] = [f"body does not parse as {STAGE_SCHEMA_ID}"]
        summary["guard"] = _guard_summary(adapter, board, task.id)
        summary["decisions"] = _decision_comments(adapter, conn, task.id)
        summary["recovery_advice"] = _recovery_advice(ctx.role, task.status)
        return summary

    summary["feature_id"] = card.feature_id
    summary["stage"] = card.stage
    summary["intent"] = card.intent
    summary["ui_acceptance"] = card.ui_acceptance
    summary["coding_agent"] = card.coding_agent
    summary["accepted_plan"] = card.accepted_plan
    summary["accepted_plan_live"] = _accepted_plan_live(card.accepted_plan)
    summary["pair"] = _pair_summary(adapter, conn, task.id, card.feature_id)
    summary["guard"] = _guard_summary(adapter, board, task.id)
    summary["decisions"] = _decision_comments(adapter, conn, task.id)
    summary["unmet_requirements"] = _unmet_requirements(card)
    summary["recovery_advice"] = _recovery_advice(ctx.role, task.status)
    return summary


def _accepted_plan_identity(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "card_id": plan.get("card_id"),
        "path": plan.get("path"),
        "sha256": plan.get("sha256"),
    }


def _preserve_draft_identity(
    ctx: Any,
    *,
    task_id: str,
    draft: StageCard,
    replacement: StageCard,
) -> None:
    changed: list[str] = []
    if replacement.feature_id != draft.feature_id:
        changed.append("feature_id")
    if replacement.stage != draft.stage:
        changed.append("stage")
    if replacement.coding_agent != draft.coding_agent:
        changed.append("coding_agent")
    if not changed:
        return
    _fail(
        ctx,
        CARD_CONTRACT_INVALID,
        "a draft may not be repurposed into another feature/stage/adapter: "
        + ", ".join(changed),
        task_id=task_id,
        changed_fields=changed,
        existing={
            "feature_id": draft.feature_id,
            "stage": draft.stage,
            "coding_agent": draft.coding_agent,
        },
        replacement={
            "feature_id": replacement.feature_id,
            "stage": replacement.stage,
            "coding_agent": replacement.coding_agent,
        },
    )


def _verify_execute_plan_identity(
    adapter: Any,
    conn: Any,
    ctx: Any,
    *,
    task_id: str,
    card: StageCard,
) -> None:
    plan = card.accepted_plan
    if not isinstance(plan, dict):
        _fail(
            ctx,
            PLAN_IDENTITY_MISSING,
            "execute-plan converged Cards require an accepted_plan identity",
            task_id=task_id,
        )
    path_raw = plan.get("path")
    expected_sha = plan.get("sha256")
    plan_card_id = plan.get("card_id")
    expected_handoff = _accepted_plan_identity(plan)

    parents = list(adapter.parent_ids(conn, task_id) or [])
    if plan_card_id not in parents:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            "accepted_plan.card_id is not a parent of this Card",
            task_id=task_id,
            accepted_plan_card_id=plan_card_id,
            parent_ids=parents,
        )
    parent_task = adapter.get_task(conn, plan_card_id)
    if parent_task is None:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"accepted_plan.card_id {plan_card_id!r} does not exist",
            task_id=task_id,
        )
    try:
        parent_card = parse_stage_body(parent_task.body or "")
    except ContractError as exc:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"accepted_plan parent is not a {STAGE_SCHEMA_ID} write-plan Card: {exc}",
            task_id=task_id,
            accepted_plan_card_id=plan_card_id,
        )
    if parent_card.stage != "write-plan" or parent_card.feature_id != card.feature_id:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            "accepted_plan parent must be a same-feature write-plan Card",
            task_id=task_id,
            accepted_plan_card_id=plan_card_id,
            parent_stage=parent_card.stage,
            parent_feature_id=parent_card.feature_id,
            feature_id=card.feature_id,
        )
    if parent_task.status not in _PARENT_COMPLETE_STATUSES:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            "accepted_plan write-plan parent must be done or archived "
            f"(got {parent_task.status!r})",
            task_id=task_id,
            accepted_plan_card_id=plan_card_id,
            parent_status=parent_task.status,
        )

    path = Path(path_raw) if isinstance(path_raw, str) else None
    if path is None or not path.is_file() or path.stat().st_size == 0:
        _fail(
            ctx,
            PLAN_IDENTITY_MISSING,
            "accepted_plan path is missing, not a file, or empty",
            task_id=task_id,
            path=path_raw,
        )
    try:
        actual_sha = _file_sha256(path)
    except OSError as exc:
        _fail(
            ctx,
            PLAN_IDENTITY_MISSING,
            f"accepted_plan path could not be read: {exc}",
            task_id=task_id,
            path=path_raw,
        )
    if actual_sha != expected_sha:
        _fail(
            ctx,
            PLAN_SHA_MISMATCH,
            "accepted_plan.sha256 does not match the plan file",
            task_id=task_id,
            path=path_raw,
            expected=expected_sha,
            actual=actual_sha,
        )

    metadata = adapter.completed_run_metadata(conn, plan_card_id)
    actual_handoff = (
        metadata.get("accepted_plan") if isinstance(metadata, dict) else None
    )
    if actual_handoff != expected_handoff:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            "accepted_plan does not match the write-plan PASS handoff",
            task_id=task_id,
            expected=expected_handoff,
            actual=actual_handoff,
        )


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


def _subscribe_creator(conn: Any, adapter: Any, task_ids: tuple[str, ...]) -> None:
    """Subscribe the creating chat to each card's block/completion notifications.

    ``kanban_create`` does this via ``_maybe_auto_subscribe`` (tool layer);
    harness-created cards bypass that layer and would otherwise never notify —
    observed on t_d55cb17d, whose capability blocks reached no Feishu chat.
    Failures are swallowed inside the adapter: bookkeeping must never fail
    card creation.
    """
    subscribe = getattr(adapter, "subscribe_creator_session", None)
    if not callable(subscribe):
        return
    for task_id in task_ids:
        subscribe(conn, task_id)


def op_create_feature(
    adapter: Any,
    *,
    route: str,
    feature_id: str,
    title: str,
    goal: str,
    repo: str,
    included_scope: str | None = None,
    open_items: str | None = None,
    coding_agent: str = "pi",
    board: str | None = None,
) -> dict:
    """Create draft feature Card(s) in triage (design §12.2, §12.3, §19.2)."""
    ctx = classify_session(adapter, board=board)
    _require_origin(ctx)
    _require_probe(adapter, ctx)

    if route not in _ROUTES:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"route must be one of {list(_ROUTES)} (got {route!r})",
            route=route,
        )
    if _blank(feature_id) or not _FEATURE_ID_RE.fullmatch(feature_id.strip()):
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            "feature_id must be kebab-case "
            r"^[a-z0-9]+(-[a-z0-9]+)*$ "
            f"(got {feature_id!r})",
            feature_id=feature_id,
        )
    feature_id = feature_id.strip()
    if _blank(title):
        _fail(ctx, CARD_CONTRACT_INVALID, "title must be a non-blank string")
    if _blank(goal):
        _fail(ctx, CARD_CONTRACT_INVALID, "goal must be a non-blank string")
    title = title.strip()
    goal = goal.strip()
    if coding_agent not in CODING_AGENTS:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"coding_agent must be one of {list(CODING_AGENTS)} "
            f"(got {coding_agent!r})",
            coding_agent=coding_agent,
        )
    pinned = _pinned_skills(ctx, coding_agent)
    repo_path = _resolve_feature_repo(ctx, repo)

    resolved = _resolve_board(adapter, board, ctx)
    _check_kanban_preconditions(adapter, ctx, route=route)

    stages = ("direct",) if route == "direct" else ("write-plan", "execute-plan")
    bodies = {
        stage: _validated_draft_body(
            ctx,
            feature_id=feature_id,
            stage=stage,
            goal=goal,
            coding_agent=coding_agent,
            included_scope=included_scope,
            open_items=open_items,
        )
        for stage in stages
    }
    author = _author(adapter)
    create_kwargs = {
        "triage": True,
        "assignee": DEFAULT_ASSIGNEE,
        "created_by": author,
        "board": resolved,
        "workspace_kind": "dir",
        "workspace_path": repo_path,
        "skills": pinned,
    }
    conn = _connect(adapter, resolved, ctx)
    _created_ids: tuple[str, ...] = ()
    try:
        with adapter.write_txn(conn):
            _assert_feature_stage_free(
                adapter, conn, ctx, feature_id=feature_id, stages=stages
            )
            if route == "direct":
                task_id = adapter.create_task(
                    conn,
                    title=_card_title(title, stage="direct", route=route),
                    body=bodies["direct"],
                    parents=(),
                    **create_kwargs,
                )
                _created_ids = (task_id,)
                task, _card, problems = _verify_created_card(
                    adapter,
                    conn,
                    task_id,
                    feature_id=feature_id,
                    stage="direct",
                    workspace_path=repo_path,
                    skills=pinned,
                )
                if problems:
                    _fail(
                        ctx,
                        HARNESS_STATE_UNAVAILABLE,
                        "direct card verification failed: "
                        + "; ".join(problems),
                        task_id=task_id,
                        feature_id=feature_id,
                    )
                return {
                    "ok": True,
                    "board": resolved,
                    "route": route,
                    "feature_id": feature_id,
                    "repo": repo_path,
                    "workspace_kind": "dir",
                    "skills": list(pinned),
                    "cards": [_task_snapshot(task, "direct")],
                    "next": _NEXT_DIRECT,
                }

            wp_id = adapter.create_task(
                conn,
                title=_card_title(title, stage="write-plan", route=route),
                body=bodies["write-plan"],
                parents=(),
                **create_kwargs,
            )
            exec_id = adapter.create_task(
                conn,
                title=_card_title(title, stage="execute-plan", route=route),
                body=bodies["execute-plan"],
                parents=(wp_id,),
                **create_kwargs,
            )
            wp_task, _wp_card, wp_problems = _verify_created_card(
                adapter,
                conn,
                wp_id,
                feature_id=feature_id,
                stage="write-plan",
                workspace_path=repo_path,
                skills=pinned,
            )
            ex_task, _ex_card, ex_problems = _verify_created_card(
                adapter,
                conn,
                exec_id,
                feature_id=feature_id,
                stage="execute-plan",
                workspace_path=repo_path,
                skills=pinned,
            )
            problems = list(wp_problems) + list(ex_problems)
            if wp_task is None or ex_task is None:
                problems.append("one or both two-stage cards missing after create")
            else:
                parents = list(adapter.parent_ids(conn, exec_id) or [])
                if parents != [wp_id]:
                    problems.append(
                        f"execute-plan parent_ids {parents!r} != [{wp_id!r}]"
                    )
            _created_ids = (wp_id, exec_id)
            if problems:
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    "two-stage pair verification failed: "
                    + "; ".join(problems),
                    write_plan_id=wp_id,
                    execute_plan_id=exec_id,
                    feature_id=feature_id,
                )
            return {
                "ok": True,
                "board": resolved,
                "route": route,
                "feature_id": feature_id,
                "repo": repo_path,
                "workspace_kind": "dir",
                "skills": list(pinned),
                "cards": [
                    _task_snapshot(wp_task, "write-plan"),
                    _task_snapshot(ex_task, "execute-plan"),
                ],
                "next": _NEXT_TWO_STAGE,
            }
    finally:
        # Post-commit: add_notify_sub opens its own write_txn, which must not
        # nest inside the create transaction. Swallows failures by design.
        if _created_ids:
            _subscribe_creator(conn, adapter, _created_ids)
        adapter.close(conn)


def op_record_decision(
    adapter: Any,
    *,
    task_id: str,
    kind: str,
    decision: str,
    affects_accepted_plan: bool | None = None,
    candidate_commit: str | None = None,
    verdict: str | None = None,
    round: int | None = None,
    board: str | None = None,
) -> dict:
    """Append a structured Origin decision comment (design §12.4, §19.3)."""
    ctx = classify_session(adapter, board=board)
    _require_origin(ctx)
    _require_probe(adapter, ctx)

    if _blank(task_id):
        _fail(ctx, CARD_CONTRACT_INVALID, "task_id is required")
    task_id = task_id.strip()
    if kind not in DECISION_KINDS:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"kind must be one of {list(DECISION_KINDS)} (got {kind!r})",
            kind=kind,
        )
    if _blank(decision):
        _fail(ctx, CARD_CONTRACT_INVALID, "decision must be a non-blank string")
    decision = decision.strip()

    resolved = _resolve_board(adapter, board, ctx)
    conn = _connect(adapter, resolved, ctx)
    try:
        task = adapter.get_task(conn, task_id)
        if task is None:
            _fail(
                ctx,
                HARNESS_STATE_UNAVAILABLE,
                f"task {task_id} not found",
                task_id=task_id,
            )
        try:
            card = parse_stage_body(task.body or "")
        except ContractError as exc:
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                f"task {task_id} is not a {STAGE_SCHEMA_ID} Card: {exc}",
                task_id=task_id,
            )
        if kind == "intent-decision" and task.status != "triage":
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                "intent decisions belong to draft convergence",
                task_id=task_id,
                status=task.status,
                kind=kind,
            )
        if kind == "amendment" and task.status == "triage":
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                "amendments apply after finalization",
                task_id=task_id,
                status=task.status,
                kind=kind,
            )
        if kind == "round-authorization" and task.status == "triage":
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                "round authorizations apply after finalization",
                task_id=task_id,
                status=task.status,
                kind=kind,
            )
        body = encode_decision_comment(
            kind,
            card_id=task_id,
            feature_id=str(card.feature_id or ""),
            stage=str(card.stage or ""),
            decision=decision,
            decided_by="origin",
            affects_accepted_plan=affects_accepted_plan,
            candidate_commit=candidate_commit,
            verdict=verdict,
            round=round,
        )
        parsed = parse_decision_comment(body)
        if parsed is None:
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                "encoded decision comment did not round-trip",
                task_id=task_id,
            )
        violations = validate_decision(parsed)
        if violations:
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                "decision comment contract violations: " + "; ".join(violations),
                task_id=task_id,
                violations=violations,
            )
        comment_id = adapter.add_comment(
            conn, task_id, _author(adapter), body
        )
        return {
            "ok": True,
            "task_id": task_id,
            "comment_id": comment_id,
            "decision": parsed,
        }
    finally:
        adapter.close(conn)


def op_finalize_stage(
    adapter: Any,
    *,
    task_id: str,
    body: str,
    title: str | None = None,
    board: str | None = None,
) -> dict:
    """Finalize a triage stage Card via ``specify_triage_task`` (design §19.4)."""
    ctx = classify_session(adapter, board=board)
    _require_origin(ctx)
    _require_probe(adapter, ctx)

    if _blank(task_id):
        _fail(ctx, CARD_CONTRACT_INVALID, "task_id is required")
    task_id = task_id.strip()
    if not isinstance(body, str) or not body.strip():
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            "body is required and must be the complete replacement "
            f"{STAGE_SCHEMA_ID} body",
            task_id=task_id,
        )
    if title is not None:
        if _blank(title):
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                "title, when provided, must be a non-blank string",
                task_id=task_id,
            )
        title = title.strip()

    resolved = _resolve_board(adapter, board, ctx)
    conn = _connect(adapter, resolved, ctx)
    try:
        task = adapter.get_task(conn, task_id)
        if task is None:
            _fail(
                ctx,
                HARNESS_STATE_UNAVAILABLE,
                f"task {task_id} not found",
                task_id=task_id,
            )
        if task.status != "triage":
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                f"task {task_id} is {task.status!r}; only triage Cards may be "
                "finalized",
                task_id=task_id,
                status=task.status,
            )
        existing_assignee = (task.assignee or "").strip().lower() or None
        if existing_assignee not in (None, DEFAULT_ASSIGNEE):
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                f"task {task_id} is assigned to {existing_assignee!r}; this "
                f"finalizer only owns Cards with assignee {DEFAULT_ASSIGNEE!r}",
                task_id=task_id,
                assignee=existing_assignee,
            )

        try:
            draft_card = parse_stage_body(task.body or "")
        except ContractError as exc:
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                f"current card is not a {STAGE_SCHEMA_ID} body: {exc}",
                task_id=task_id,
            )
        try:
            card = parse_stage_body(body)
        except ContractError as exc:
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                f"{STAGE_SCHEMA_ID} body does not parse: {exc}",
                task_id=task_id,
            )
        _preserve_draft_identity(
            ctx, task_id=task_id, draft=draft_card, replacement=card
        )
        violations = validate_stage_card(card, require="converged")
        if violations:
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                f"{STAGE_SCHEMA_ID} contract violations block finalization: "
                + "; ".join(violations),
                task_id=task_id,
                violations=violations,
            )

        if card.stage == "execute-plan":
            _verify_execute_plan_identity(
                adapter, conn, ctx, task_id=task_id, card=card
            )

        issues = check_adapter_capability(
            str(card.coding_agent),
            hermes_home=adapter.hermes_home,
            auto_handoff_required=(card.stage == "execute-plan"),
        )
        if issues:
            _fail(
                ctx,
                ADAPTER_CAPABILITY_MISSING,
                "coding agent adapter is missing required capabilities: "
                + "; ".join(issues),
                task_id=task_id,
                coding_agent=card.coding_agent,
                issues=issues,
            )

        _assert_feature_stage_free(
            adapter,
            conn,
            ctx,
            feature_id=str(card.feature_id),
            stages=(str(card.stage),),
            exclude_task_id=task_id,
        )

        try:
            specified = adapter.specify_triage_task(
                conn,
                task_id,
                title=title,
                body=body,
                assignee=DEFAULT_ASSIGNEE,
                author=_author(adapter),
            )
        except ValueError as exc:
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                f"specify_triage_task rejected the update: {exc}",
                task_id=task_id,
            )
        if specified is not True:
            _fail(
                ctx,
                DRAFT_NOT_DISPATCHABLE,
                f"task {task_id} was not specified (no longer triage at write time)",
                task_id=task_id,
            )

        fresh = adapter.get_task(conn, task_id)
        if fresh is None:
            _fail(
                ctx,
                HARNESS_STATE_UNAVAILABLE,
                f"task {task_id} vanished after finalization",
                task_id=task_id,
            )
        body_ok = (fresh.body or "") == body
        assignee_ok = (fresh.assignee or "") == DEFAULT_ASSIGNEE

        open_parents: list[str] = []
        for parent_id in adapter.parent_ids(conn, task_id) or []:
            parent = adapter.get_task(conn, parent_id)
            if parent is None or parent.status not in _PARENT_COMPLETE_STATUSES:
                open_parents.append(parent_id)
        expected_status = "todo" if open_parents else "ready"
        status_ok = fresh.status == expected_status

        specified_event_ok = any(
            getattr(event, "kind", None) == "specified"
            for event in (adapter.list_events(conn, task_id) or [])
        )

        verified = {
            "body": body_ok,
            "assignee": assignee_ok,
            "status": status_ok,
            "specified_event": specified_event_ok,
        }
        if not (body_ok and assignee_ok and status_ok and specified_event_ok):
            failed = [name for name, ok in verified.items() if not ok]
            _fail(
                ctx,
                HARNESS_STATE_UNAVAILABLE,
                "read-back verification failed for: " + ", ".join(failed),
                task_id=task_id,
                status=fresh.status,
                expected_status=expected_status,
                verified=verified,
            )

        return {
            "ok": True,
            "task_id": task_id,
            "board": resolved,
            "status": fresh.status,
            "verified": verified,
            "parent_gated": bool(open_parents),
            "open_parents": open_parents,
        }
    finally:
        adapter.close(conn)


def op_inspect(
    adapter: Any,
    *,
    board: str | None = None,
    task_id: str | None = None,
    feature_id: str | None = None,
) -> dict:
    """Reconstruct feature state from persistent facts (design §19.1, §22)."""
    ctx = classify_session(adapter, board=board)
    probe = adapter.probe()
    probe_ok = probe.get("ok") is True
    task_id = task_id.strip() if isinstance(task_id, str) and task_id.strip() else None
    feature_id = (
        feature_id.strip()
        if isinstance(feature_id, str) and feature_id.strip()
        else None
    )

    resolved = _resolve_board(adapter, board, ctx)
    base: dict[str, Any] = {
        "ok": True,
        "role": ctx.role,
        "board": resolved,
        "allowed_actions": allowed_actions_for(ctx.role),
        "probe_ok": probe_ok,
    }
    if not probe_ok:
        base["probe_missing"] = probe.get("missing") or []

    conn = None
    try:
        try:
            conn = adapter.connect(board=resolved)
        except Exception as exc:
            if not probe_ok:
                base["ok"] = True
                base["connect_error"] = str(exc)
                base["recovery_advice"] = _recovery_advice(ctx.role, None)
                return base
            _fail(
                ctx,
                HARNESS_STATE_UNAVAILABLE,
                f"kanban connect failed: {exc}",
            )

        if task_id:
            task = adapter.get_task(conn, task_id)
            if task is None:
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    f"task {task_id} not found",
                    task_id=task_id,
                    board=resolved,
                )
            card = _summarize_card(adapter, conn, task, resolved, ctx)
            base["task_id"] = task.id
            base["feature_id"] = card.get("feature_id")
            base["card"] = card
            base["recovery_advice"] = card.get("recovery_advice")
            return base

        if feature_id:
            matches: list[tuple[Any, StageCard]] = [
                (task, card)
                for task, card in _scan_dev_cards(adapter, conn)
                if card.feature_id == feature_id
            ]
            if not matches:
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    f"no non-archived {STAGE_SCHEMA_ID} Card for feature "
                    f"{feature_id!r}",
                    feature_id=feature_id,
                    board=resolved,
                )
            by_stage: dict[str, list[tuple[Any, StageCard]]] = {}
            for task, card in matches:
                by_stage.setdefault(str(card.stage), []).append((task, card))
            duplicates = {
                stage: [
                    {
                        "task_id": task.id,
                        "stage": stage,
                        "status": task.status,
                    }
                    for task, _card in rows
                ]
                for stage, rows in by_stage.items()
                if len(rows) > 1
            }
            if duplicates:
                candidates = [
                    item for rows in duplicates.values() for item in rows
                ]
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    f"feature {feature_id!r} has multiple Cards for the same "
                    "stage; refusing to guess",
                    feature_id=feature_id,
                    board=resolved,
                    candidates=candidates,
                )
            cards = [
                _summarize_card(adapter, conn, task, resolved, ctx)
                for task, _card in matches
            ]
            cards.sort(key=lambda item: STAGES.index(item["stage"]) if item.get("stage") in STAGES else 99)
            base["feature_id"] = feature_id
            base["cards"] = cards
            if cards:
                base["recovery_advice"] = cards[0].get("recovery_advice")
            return base

        if ctx.is_worker():
            env_task_id = ctx.env_task_id
            if not env_task_id:
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    "worker inspect needs HERMES_KANBAN_TASK or an explicit "
                    "task_id/feature_id",
                )
            task = adapter.get_task(conn, env_task_id)
            if task is None:
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    f"task {env_task_id} not found",
                    task_id=env_task_id,
                    board=resolved,
                )
            card = _summarize_card(adapter, conn, task, resolved, ctx)
            base["task_id"] = task.id
            base["feature_id"] = card.get("feature_id")
            base["card"] = card
            base["recovery_advice"] = card.get("recovery_advice")
            return base

        features: dict[str, dict[str, Any]] = {}
        for task, card in _scan_dev_cards(adapter, conn):
            fid = str(card.feature_id)
            entry = features.setdefault(
                fid,
                {"feature_id": fid, "stages": [], "cards": []},
            )
            stage = str(card.stage)
            if stage not in entry["stages"]:
                entry["stages"].append(stage)
            entry["cards"].append(
                {
                    "task_id": task.id,
                    "stage": stage,
                    "status": task.status,
                }
            )
        base["features"] = list(features.values())
        base["recovery_advice"] = _recovery_advice(ctx.role, None)
        return base
    finally:
        if conn is not None:
            adapter.close(conn)
