"""Session role classification from runtime + Kanban facts (design §10).

Never mutates Kanban. Non-owning classification is a pure read of the
current Card/run/claim identity; the caller applies process quarantine.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import (
    CODING_AGENTS,
    STAGE_SCHEMA_ID,
    ContractError,
    StageCard,
    card_schema_id,
    parse_stage_body,
    validate_stage_card,
)
from .errors import (
    ADAPTER_CAPABILITY_MISSING,
    CARD_CONTRACT_INVALID,
    RUN_NOT_OWNED,
    WORKSPACE_INVALID,
    failure,
)

ROLES = (
    "origin",
    "implement-worker",
    "review-worker",
    "non-owning-worker",
    "unmanaged",
)

_ALLOWED_ACTIONS: dict[str, list[str]] = {
    "origin": [
        "devflow_inspect",
        "devflow_create_feature",
        "devflow_record_decision",
        "devflow_finalize_stage",
        "read",
        "exit",
    ],
    "implement-worker": [
        "devflow_inspect",
        "devflow_start_or_inspect_relay",
        "devflow_ui_lease",
        "devflow_implement_handoff",
        "read",
        "kanban_block",
        "kanban_heartbeat",
        "exit",
    ],
    "review-worker": [
        "devflow_inspect",
        "devflow_start_or_inspect_relay",
        "devflow_review_verdict",
        "read",
        "kanban_block",
        "kanban_heartbeat",
        "exit",
    ],
    "non-owning-worker": [
        "devflow_inspect",
        "read",
        "exit",
    ],
    "unmanaged": [
        "read",
        "exit",
    ],
}

_ACTIVE_RUN_STATUSES = frozenset({"running"})
_TERMINAL_CARD_STATUSES = frozenset({"done", "archived"})


@dataclass
class SessionContext:
    """Classified session identity for the current process."""

    role: str
    env_task_id: str | None = None
    env_run_id: int | None = None
    env_claim_lock: str | None = None
    board: str | None = None
    card: Any = None
    current_run: Any = None
    source_status: str | None = None
    reasons: list[str] = field(default_factory=list)

    def current_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {"role": self.role}
        task_id = self.env_task_id
        if task_id is None and self.card is not None:
            task_id = getattr(self.card, "id", None)
        if task_id is not None:
            state["task_id"] = task_id
        if self.env_run_id is not None:
            state["session_run_id"] = self.env_run_id
        current_run_id = None
        if self.card is not None:
            current_run_id = getattr(self.card, "current_run_id", None)
        if current_run_id is None and self.current_run is not None:
            current_run_id = getattr(self.current_run, "id", None)
        if current_run_id is not None:
            state["current_run_id"] = current_run_id
        if self.board is not None:
            state["board"] = self.board
        return state

    def is_worker(self) -> bool:
        return self.role in {
            "implement-worker",
            "review-worker",
            "non-owning-worker",
        }

    def is_owning(self) -> bool:
        return self.role in {"implement-worker", "review-worker"}


def apply_non_owning_quarantine() -> None:
    """Disable the Kanban stop nudge in this process only (FR-03 / §10.4)."""
    os.environ["HERMES_KANBAN_STOP_NUDGE"] = "0"


def allowed_actions_for(role: str) -> list[str]:
    return list(_ALLOWED_ACTIONS.get(role, ["read", "exit"]))


def _parse_run_id(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _resolved_board(adapter: Any, board: str | None) -> str | None:
    if board:
        return board
    try:
        resolved = adapter.get_current_board()
    except Exception:
        return None
    return str(resolved) if resolved else None


def classify_session(adapter: Any, *, board: str | None = None) -> SessionContext:
    """Classify this process as origin / worker / non-owning / unmanaged.

    Read-only: never writes Kanban. Missing or mismatched ownership becomes
    ``non-owning-worker`` with a precise reason.
    """
    env = adapter.dispatcher_task_env()
    env_task_id = env.get("HERMES_KANBAN_TASK") or None
    env_run_id = _parse_run_id(env.get("HERMES_KANBAN_RUN_ID"))
    env_claim_lock = env.get("HERMES_KANBAN_CLAIM_LOCK") or None
    delegated = bool(adapter.is_delegated_child())
    resolved_board = _resolved_board(adapter, board)

    def _ctx(
        role: str,
        *,
        reasons: list[str] | None = None,
        card: Any = None,
        current_run: Any = None,
        source_status: str | None = None,
    ) -> SessionContext:
        return SessionContext(
            role=role,
            env_task_id=env_task_id,
            env_run_id=env_run_id,
            env_claim_lock=env_claim_lock,
            board=resolved_board,
            card=card,
            current_run=current_run,
            source_status=source_status,
            reasons=list(reasons or []),
        )

    if not env_task_id:
        if delegated:
            return _ctx("unmanaged", reasons=["delegated child without dispatcher task env"])
        cron_owned = False
        try:
            cron_owned = bool(adapter.is_cron_context())
        except Exception:
            cron_owned = True
        if cron_owned:
            return _ctx(
                "unmanaged",
                reasons=["cron-owned context is not an interactive Origin session"],
            )
        try:
            profile = adapter.active_profile_name()
        except Exception:
            profile = ""
        if profile == "default":
            return _ctx("origin")
        return _ctx(
            "unmanaged",
            reasons=[f"active profile is {profile!r}, not 'default'"],
        )

    if delegated:
        return _ctx(
            "unmanaged",
            reasons=["delegated child cannot own a dispatcher worker run"],
        )

    dispatcher_owned = False
    try:
        dispatcher_owned = bool(adapter.is_dispatcher_owned_worker())
    except Exception:
        dispatcher_owned = False
    if not dispatcher_owned:
        return _ctx(
            "non-owning-worker",
            reasons=["context is not dispatcher-owned (cron or delegated)"],
        )

    raw_run = (os.environ.get("HERMES_KANBAN_RUN_ID") or "").strip()
    raw_lock = (os.environ.get("HERMES_KANBAN_CLAIM_LOCK") or "").strip()
    if not raw_run or env_run_id is None:
        return _ctx(
            "non-owning-worker",
            reasons=["HERMES_KANBAN_RUN_ID is missing or not an int"],
        )
    if not raw_lock:
        return _ctx(
            "non-owning-worker",
            reasons=["HERMES_KANBAN_CLAIM_LOCK is missing"],
        )

    conn = None
    try:
        conn = adapter.connect(board=board)
        card = adapter.get_task(conn, env_task_id)
        if card is None:
            return _ctx(
                "non-owning-worker",
                reasons=[f"task {env_task_id} not found"],
            )
        status = getattr(card, "status", None)
        if status in _TERMINAL_CARD_STATUSES:
            return _ctx(
                "non-owning-worker",
                card=card,
                reasons=[f"task {env_task_id} is '{status}'"],
            )
        card_run_id = getattr(card, "current_run_id", None)
        if card_run_id is None or int(card_run_id) != int(env_run_id):
            return _ctx(
                "non-owning-worker",
                card=card,
                reasons=[
                    f"session run {env_run_id} is not current run {card_run_id}"
                ],
            )
        card_lock = getattr(card, "claim_lock", None)
        if card_lock != env_claim_lock:
            return _ctx(
                "non-owning-worker",
                card=card,
                reasons=["claim lock does not match the Card claim_lock"],
            )
        if status != "running":
            return _ctx(
                "non-owning-worker",
                card=card,
                reasons=[f"task status is '{status}', not running"],
            )
        current_run = adapter.current_run(conn, env_task_id)
        if current_run is None:
            return _ctx(
                "non-owning-worker",
                card=card,
                reasons=[f"current run {card_run_id} not found"],
            )
        run_status = getattr(current_run, "status", None)
        if run_status not in _ACTIVE_RUN_STATUSES:
            return _ctx(
                "non-owning-worker",
                card=card,
                current_run=current_run,
                reasons=[
                    f"run {card_run_id} status is '{run_status}', not running"
                ],
            )
        source_status = adapter.claimed_source_status(
            conn, env_task_id, int(env_run_id)
        )
        if source_status == "review":
            return _ctx(
                "review-worker",
                card=card,
                current_run=current_run,
                source_status=source_status,
            )
        return _ctx(
            "implement-worker",
            card=card,
            current_run=current_run,
            source_status=source_status,
        )
    except Exception as exc:
        return _ctx(
            "non-owning-worker",
            reasons=[f"kanban unavailable: {exc}"],
        )
    finally:
        if conn is not None:
            adapter.close(conn)


def managed_card(task: Any) -> StageCard | None:
    """Parsed v2 StageCard when the body schema is literally development-stage.v2.

    Returns None for every other body, including legacy development-task.v1 and
    eight-section lookalikes with a different schema. Never raises.
    """
    body = getattr(task, "body", None)
    if not isinstance(body, str):
        return None
    if card_schema_id(body) != STAGE_SCHEMA_ID:
        return None
    try:
        return parse_stage_body(body)
    except (ContractError, Exception):
        return None


def require_worker_card(adapter: Any, ctx: SessionContext) -> StageCard:
    """Return the converged managed card for an owning worker, or raise."""
    task_id = ctx.env_task_id
    if not task_id and ctx.card is not None:
        task_id = getattr(ctx.card, "id", None)
    if not task_id:
        raise failure(
            CARD_CONTRACT_INVALID,
            "not a managed development-stage.v2 card: no current Card",
            current_state=ctx.current_state(),
        )
    conn = None
    try:
        conn = adapter.connect(board=ctx.board)
        task = adapter.get_task(conn, str(task_id))
    except Exception as exc:
        raise failure(
            CARD_CONTRACT_INVALID,
            f"cannot re-read task {task_id}: {exc}",
            current_state=ctx.current_state(),
        ) from exc
    finally:
        if conn is not None:
            adapter.close(conn)
    if task is None:
        raise failure(
            CARD_CONTRACT_INVALID,
            f"not a managed {STAGE_SCHEMA_ID} card: task {task_id} not found",
            current_state=ctx.current_state(),
        )
    body = getattr(task, "body", None) or ""
    if card_schema_id(body) != STAGE_SCHEMA_ID:
        raise failure(
            CARD_CONTRACT_INVALID,
            f"not a managed {STAGE_SCHEMA_ID} card",
            current_state=ctx.current_state(),
        )
    try:
        card = parse_stage_body(body)
    except ContractError as exc:
        raise failure(
            CARD_CONTRACT_INVALID,
            f"managed card failed to parse: {exc}",
            current_state=ctx.current_state(),
            violations=[str(exc)],
        ) from exc
    violations = validate_stage_card(card, require="converged")
    if violations:
        raise failure(
            CARD_CONTRACT_INVALID,
            "managed card is not a valid converged development-stage.v2 body",
            current_state=ctx.current_state(),
            violations=violations,
        )
    if getattr(task, "assignee", None) != "default":
        raise failure(
            RUN_NOT_OWNED,
            "task assignee is not the literal 'default'",
            current_state=ctx.current_state(),
            assignee=getattr(task, "assignee", None),
        )
    if card.coding_agent not in CODING_AGENTS:
        raise failure(
            ADAPTER_CAPABILITY_MISSING,
            f"coding_agent {card.coding_agent!r} is not a supported adapter",
            current_state=ctx.current_state(),
            coding_agent=card.coding_agent,
        )
    kind = getattr(task, "workspace_kind", None)
    if kind != "dir":
        raise failure(
            WORKSPACE_INVALID,
            f"workspace_kind must be 'dir' (got {kind!r})",
            current_state=ctx.current_state(),
            workspace_kind=kind,
        )
    raw_path = getattr(task, "workspace_path", None)
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise failure(
            WORKSPACE_INVALID,
            "workspace_path is missing",
            current_state=ctx.current_state(),
        )
    path = Path(raw_path)
    if not path.is_absolute() or not path.is_dir():
        raise failure(
            WORKSPACE_INVALID,
            "workspace_path must be an absolute existing directory "
            f"(got {raw_path!r})",
            current_state=ctx.current_state(),
            workspace_path=raw_path,
        )
    return card


def _run_ended_before(run: Any, current: Any) -> bool:
    ended = getattr(run, "ended_at", None)
    started = getattr(current, "started_at", None)
    if ended is None or started is None:
        return False
    try:
        ended_at = int(ended)
        started_at = int(started)
    except (TypeError, ValueError):
        return False
    if ended_at < started_at:
        return True
    if ended_at > started_at:
        return False
    run_id = getattr(run, "id", None)
    current_id = getattr(current, "id", None)
    if run_id is None or current_id is None:
        return True
    try:
        return int(run_id) < int(current_id)
    except (TypeError, ValueError):
        return False


def _latest_guard_landing_commit(
    adapter: Any, board: str | None, card_id: str
) -> tuple[str | None, str | None]:
    """Return ``(commit, reason)``. ``reason`` is set when commit is unavailable."""
    root = getattr(adapter, "artifacts_root", None)
    if root is None:
        return None, "adapter has no artifacts_root"
    board_name = board or "default"
    path = Path(root) / str(board_name) / "tasks" / str(card_id) / "external-execution.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None, f"guard state missing at {path}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "guard state is not valid JSON"
    if not isinstance(data, dict):
        return None, "guard state is not a mapping"
    landings = data.get("landings")
    if not isinstance(landings, list) or not landings:
        return None, "guard state has no landings"
    last = landings[-1]
    if not isinstance(last, dict):
        return None, "latest guard landing is not a mapping"
    commit = last.get("commit")
    if not isinstance(commit, str) or not commit:
        return None, "latest guard landing has no commit"
    return commit, None


def review_authority(adapter: Any, ctx: SessionContext) -> tuple[bool, list[str]]:
    """Whether this review-worker has a live review_requested handoff (blocker 2)."""
    if ctx.role != "review-worker":
        return False, ["precondition role must be 'review-worker'"]
    reasons: list[str] = []
    if ctx.source_status != "review":
        reasons.append("claimed source_status is not 'review'")

    task_id = ctx.env_task_id
    if not task_id and ctx.card is not None:
        task_id = getattr(ctx.card, "id", None)
    current = ctx.current_run
    conn = None
    try:
        conn = adapter.connect(board=ctx.board)
        runs = adapter.list_runs(conn, str(task_id)) if task_id else []
        task = adapter.get_task(conn, str(task_id)) if task_id else ctx.card
    except Exception as exc:
        reasons.append(f"kanban unavailable: {exc}")
        return False, reasons
    finally:
        if conn is not None:
            adapter.close(conn)

    handoff = None
    if current is None:
        reasons.append("current run is missing")
    else:
        for run in runs or []:
            if getattr(run, "outcome", None) != "review_requested":
                continue
            if _run_ended_before(run, current):
                handoff = run
        if handoff is None:
            reasons.append(
                "no review_requested handoff ended before the current run started"
            )

    if handoff is not None:
        metadata = getattr(handoff, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
        card = managed_card(task if task is not None else ctx.card)
        if "accepted_plan_sha256" in metadata:
            card_sha = None
            accepted = getattr(card, "accepted_plan", None) if card is not None else None
            if isinstance(accepted, dict):
                card_sha = accepted.get("sha256")
            if metadata.get("accepted_plan_sha256") != card_sha:
                reasons.append(
                    "handoff accepted_plan_sha256 does not match the card "
                    "accepted_plan.sha256"
                )
        candidate = metadata.get("candidate")
        if isinstance(candidate, dict) and "commit" in candidate:
            claimed = candidate.get("commit")
            board = ctx.board
            card_id = str(task_id) if task_id else ""
            landing, missing = _latest_guard_landing_commit(adapter, board, card_id)
            if landing is None:
                reasons.append(
                    missing or "guard landing commit is unavailable"
                )
            elif landing != claimed:
                reasons.append(
                    "handoff metadata candidate.commit does not match the "
                    "latest guard landing commit"
                )
    return (not reasons, reasons)
