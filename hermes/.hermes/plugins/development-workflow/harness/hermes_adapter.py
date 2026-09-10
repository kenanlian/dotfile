"""Hermes API compatibility boundary (design §24).

The only plugin module besides tests that may import ``hermes_cli.*`` or
``agent.*``. Imports are lazy so ``contracts`` / ``policy`` / ``errors`` stay
import-clean under plain python3.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import HARNESS_INCOMPATIBLE, failure

_PROBE_KANBAN_ATTRS = (
    "create_task",
    "specify_triage_task",
    "write_txn",
    "get_task",
    "list_tasks",
    "parent_ids",
    "child_ids",
    "link_tasks",
    "list_events",
    "list_comments",
    "add_comment",
    "list_runs",
    "get_run",
    "request_review",
    "request_changes",
    "complete_task",
    "block_task",
    "unblock_task",
    "heartbeat_claim",
    "board_exists",
    "get_current_board",
    "claim_task",
    "claim_review_task",
)


def resolve_hermes_home(env: os._Environ[str] | dict[str, str] = os.environ) -> Path:
    """``HERMES_HOME`` if set, otherwise ``~/.hermes``."""
    raw = (env.get("HERMES_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


def _artifacts_root(env: os._Environ[str] | dict[str, str] = os.environ) -> Path:
    raw = (env.get("HERMES_DEVFLOW_ARTIFACTS_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "Secret-Projects" / "development-artifacts"


class HermesAdapter:
    """Lazy facade over the Hermes Kanban / config / delegation APIs."""

    def __init__(self, *, home: Path | None = None) -> None:
        self.hermes_home = Path(home) if home is not None else resolve_hermes_home()
        self.artifacts_root = _artifacts_root()
        self.guard_script_path = (
            self.hermes_home / "scripts" / "development_external_guard.py"
        )
        self._runtime: dict[str, Any] | None = None

    def _load_runtime(self) -> dict[str, Any]:
        if self._runtime is not None:
            return self._runtime
        try:
            from hermes_cli import kanban_db as kb
            from hermes_cli import kanban_db_connect
            from hermes_cli.config import load_config_readonly
            from hermes_cli.profiles import get_active_profile_name
        except Exception as exc:
            raise failure(
                HARNESS_INCOMPATIBLE,
                f"Hermes runtime is unavailable: {exc}",
            ) from exc
        delegation = None
        try:
            from agent.delegation_context import is_delegated_child_process_context

            delegation = is_delegated_child_process_context
        except Exception:
            delegation = None
        self._runtime = {
            "kb": kb,
            "connect": kanban_db_connect,
            "load_config_readonly": load_config_readonly,
            "get_active_profile_name": get_active_profile_name,
            "is_delegated_child_process_context": delegation,
        }
        return self._runtime

    def _kb(self) -> Any:
        return self._load_runtime()["kb"]

    def probe(self) -> dict[str, Any]:
        """Presence-check every Hermes API the harness needs. Never raises."""
        capabilities: dict[str, bool] = {}
        missing: list[str] = []

        def _mark(name: str, ok: bool) -> None:
            capabilities[name] = bool(ok)
            if not ok:
                missing.append(name)

        try:
            from hermes_cli import kanban_db as kb
        except Exception:
            kb = None
        try:
            from hermes_cli import kanban_db_connect
        except Exception:
            kanban_db_connect = None  # type: ignore[assignment]
        try:
            from hermes_cli.config import load_config_readonly
        except Exception:
            load_config_readonly = None  # type: ignore[assignment]
        try:
            from hermes_cli.profiles import get_active_profile_name
        except Exception:
            get_active_profile_name = None  # type: ignore[assignment]
        try:
            from agent.delegation_context import is_delegated_child_process_context
        except Exception:
            is_delegated_child_process_context = None  # type: ignore[assignment]
        try:
            from gateway.session_context import get_session_env
        except Exception:
            get_session_env = None  # type: ignore[assignment]
        try:
            from agent.delegation_context import is_dispatcher_owned_worker_context
        except Exception:
            is_dispatcher_owned_worker_context = None  # type: ignore[assignment]

        for name in _PROBE_KANBAN_ATTRS:
            attr = getattr(kb, name, None) if kb is not None else None
            _mark(name, callable(attr))
        _mark(
            "connect",
            kanban_db_connect is not None
            and callable(getattr(kanban_db_connect, "connect", None)),
        )
        _mark("load_config_readonly", callable(load_config_readonly))
        _mark("get_active_profile_name", callable(get_active_profile_name))
        _mark(
            "is_delegated_child_process_context",
            callable(is_delegated_child_process_context),
        )
        _mark("gateway_session_context", callable(get_session_env))
        _mark(
            "delegation_dispatcher_owned",
            callable(is_dispatcher_owned_worker_context),
        )
        return {
            "ok": not missing,
            "capabilities": capabilities,
            "missing": missing,
        }

    def connect(self, board: str | None = None) -> Any:
        runtime = self._load_runtime()
        return runtime["connect"].connect(board=board)

    def write_txn(self, conn: Any, *, allow_nested: bool = False) -> Any:
        return self._kb().write_txn(conn, allow_nested=allow_nested)

    def close(self, conn: Any) -> None:
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass

    def create_task(self, conn: Any, **kwargs: Any) -> Any:
        return self._kb().create_task(conn, **kwargs)

    def specify_triage_task(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().specify_triage_task(conn, task_id, **kwargs)

    def get_task(self, conn: Any, task_id: str) -> Any:
        return self._kb().get_task(conn, task_id)

    def list_tasks(self, conn: Any, **kwargs: Any) -> Any:
        return self._kb().list_tasks(conn, **kwargs)

    def parent_ids(self, conn: Any, task_id: str) -> Any:
        return self._kb().parent_ids(conn, task_id)

    def child_ids(self, conn: Any, task_id: str) -> Any:
        return self._kb().child_ids(conn, task_id)

    def link_tasks(self, conn: Any, parent_id: str, child_id: str) -> Any:
        return self._kb().link_tasks(conn, parent_id, child_id)

    def list_events(self, conn: Any, task_id: str) -> Any:
        return self._kb().list_events(conn, task_id)

    def list_comments(self, conn: Any, task_id: str) -> Any:
        return self._kb().list_comments(conn, task_id)

    def add_comment(self, conn: Any, task_id: str, author: str, body: str) -> Any:
        return self._kb().add_comment(conn, task_id, author, body)

    def list_runs(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().list_runs(conn, task_id, **kwargs)

    def get_run(self, conn: Any, run_id: int) -> Any:
        return self._kb().get_run(conn, run_id)

    def request_review(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().request_review(conn, task_id, **kwargs)

    def request_changes(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().request_changes(conn, task_id, **kwargs)

    def complete_task(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().complete_task(conn, task_id, **kwargs)

    def block_task(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().block_task(conn, task_id, **kwargs)

    def unblock_task(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().unblock_task(conn, task_id, **kwargs)

    def heartbeat_claim(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().heartbeat_claim(conn, task_id, **kwargs)

    def claim_task(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().claim_task(conn, task_id, **kwargs)

    def claim_review_task(self, conn: Any, task_id: str, **kwargs: Any) -> Any:
        return self._kb().claim_review_task(conn, task_id, **kwargs)

    def board_exists(self, board: str | None = None) -> Any:
        return self._kb().board_exists(board)

    def get_current_board(self) -> Any:
        return self._kb().get_current_board()

    def kanban_config(self) -> dict[str, Any]:
        load = self._load_runtime()["load_config_readonly"]
        cfg = load() or {}
        kanban = cfg.get("kanban", {})
        return kanban if isinstance(kanban, dict) else {}

    def active_profile_name(self) -> str:
        getter = self._load_runtime()["get_active_profile_name"]
        return str(getter() or "")

    def is_delegated_child(self) -> bool:
        checker = self._load_runtime().get("is_delegated_child_process_context")
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                pass
        return bool(os.environ.get("HERMES_DELEGATED_CHILD_CONTEXT"))

    def dispatcher_task_env(self) -> dict[str, str]:
        """The three dispatcher worker identity vars, stripped."""
        out: dict[str, str] = {}
        for key in (
            "HERMES_KANBAN_TASK",
            "HERMES_KANBAN_RUN_ID",
            "HERMES_KANBAN_CLAIM_LOCK",
        ):
            value = (os.environ.get(key) or "").strip()
            if value:
                out[key] = value
        return out

    def claimed_source_status(
        self, conn: Any, task_id: str, run_id: int
    ) -> str | None:
        """``source_status`` from the ``claimed`` event for ``run_id``, or None."""
        wanted = int(run_id)
        for event in self.list_events(conn, task_id):
            if getattr(event, "kind", None) != "claimed":
                continue
            event_run = getattr(event, "run_id", None)
            if event_run is None or int(event_run) != wanted:
                continue
            payload = getattr(event, "payload", None) or {}
            if not isinstance(payload, dict):
                return None
            status = payload.get("source_status")
            return str(status) if status is not None else None
        return None

    def current_run(self, conn: Any, task_id: str) -> Any:
        task = self.get_task(conn, task_id)
        if task is None:
            return None
        run_id = getattr(task, "current_run_id", None)
        if run_id is None:
            return None
        return self.get_run(conn, int(run_id))

    def is_cron_context(self) -> bool:
        """True when this process is a cron-owned session (fail-closed)."""
        try:
            from gateway.session_context import get_session_env
        except Exception as exc:
            raise failure(
                HARNESS_INCOMPATIBLE,
                f"gateway session context is unavailable: {exc}",
            ) from exc
        session_val = get_session_env("HERMES_CRON_SESSION", "")
        return bool(session_val) or bool(os.getenv("HERMES_CRON_SESSION"))

    def is_dispatcher_owned_worker(self) -> bool:
        """True when this process is a dispatcher-owned Kanban worker."""
        try:
            from agent.delegation_context import is_dispatcher_owned_worker_context
        except Exception as exc:
            raise failure(
                HARNESS_INCOMPATIBLE,
                f"delegation dispatcher-owned predicate is unavailable: {exc}",
            ) from exc
        return bool(is_dispatcher_owned_worker_context())

    def completed_run_metadata(self, conn: Any, task_id: str) -> dict | None:
        """Metadata dict of the last completed run for ``task_id``, or None."""
        runs = self.list_runs(
            conn, task_id, state_type="outcome", state_name="completed"
        )
        if not runs:
            return None
        metadata = getattr(runs[-1], "metadata", None)
        return metadata if isinstance(metadata, dict) else None
