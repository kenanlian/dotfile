"""Minimal named-resource UI lease (design §9.5, §17.2).

Machine-local exclusive coordination for Agent-driven shared app resources.
Not a lifecycle source of truth; never committed to git.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import (
    HARNESS_STATE_UNAVAILABLE,
    UI_RESOURCE_BUSY,
    WORKSPACE_INVALID,
    HarnessError,
)
from .evidence import load_json, write_json_atomic

LEASE_SCHEMA = "development-ui-lease.v1"
_RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_RELEASED_FILENAME = "released.jsonl"


class UiLeaseManager:
    """File-backed exclusive leases under ``$HERMES_HOME/runtime/.../ui-leases``."""

    def __init__(self, *, hermes_home: Path) -> None:
        self.hermes_home = Path(hermes_home)
        self.leases_dir = _leases_dir(self.hermes_home)

    def lease_path(self, resource_id: str) -> Path:
        resource = _normalize_resource_id(resource_id)
        return self.leases_dir / f"{resource}.json"

    def inspect(self, resource_id: str) -> dict | None:
        path = self.lease_path(resource_id)
        with _lease_lock(path):
            lease = load_json(path)
            if not isinstance(lease, dict):
                return None
            return {
                "lease": lease,
                "holder_alive": _pid_alive(lease.get("pid")),
            }

    def acquire(
        self,
        resource_id: str,
        *,
        board,
        card_id,
        run_id,
        candidate_commit,
        holder_run_is_current=None,
    ) -> dict:
        resource = _normalize_resource_id(resource_id)
        path = self.leases_dir / f"{resource}.json"
        with _lease_lock(path):
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.close(fd)
            except FileExistsError:
                holder = load_json(path)
                if not isinstance(holder, dict):
                    raise HarnessError(
                        UI_RESOURCE_BUSY,
                        f"UI resource {resource!r} is busy",
                        holder=holder,
                    )
                if _pid_alive(holder.get("pid")):
                    raise HarnessError(
                        UI_RESOURCE_BUSY,
                        f"UI resource {resource!r} is held by a live process",
                        holder=holder,
                    )
                holder_run = holder.get("run_id")
                if holder_run_is_current is not None and holder_run_is_current(
                    holder_run
                ):
                    raise HarnessError(
                        UI_RESOURCE_BUSY,
                        f"UI resource {resource!r} is owned by a current run",
                        holder=holder,
                        reason="holder-run-current",
                    )
            lease = _new_lease(
                resource=resource,
                board=board,
                card_id=card_id,
                run_id=run_id,
                candidate_commit=candidate_commit,
            )
            write_json_atomic(path, lease)
            return lease

    def release(self, resource_id: str, *, run_id, candidate_commit=None) -> dict:
        resource = _normalize_resource_id(resource_id)
        path = self.leases_dir / f"{resource}.json"
        with _lease_lock(path):
            if not path.exists():
                return {
                    "released": True,
                    "resource": resource,
                    "run_id": run_id,
                    "already_gone": True,
                }
            holder = load_json(path)
            if not isinstance(holder, dict) or str(holder.get("run_id")) != str(run_id):
                raise HarnessError(
                    UI_RESOURCE_BUSY,
                    f"UI resource {resource!r} is not owned by this run",
                    holder=holder if isinstance(holder, dict) else None,
                    reason="not-owner",
                )
            file_commit = holder.get("candidate_commit")
            if candidate_commit is not None and file_commit != candidate_commit:
                raise HarnessError(
                    UI_RESOURCE_BUSY,
                    f"UI resource {resource!r} is not owned by this run",
                    holder=holder,
                    reason="not-owner",
                )
            record = {
                "resource": resource,
                "lease_id": holder.get("lease_id"),
                "holder_run_id": run_id,
                "card_id": holder.get("card_id"),
                "candidate_commit": file_commit,
                "acquired_at": holder.get("acquired_at"),
                "released_at": datetime.now(timezone.utc).isoformat(),
            }
            _append_release_record(self.leases_dir, record)
            try:
                os.remove(str(path))
            except OSError:
                pass
            if path.exists():
                raise HarnessError(
                    HARNESS_STATE_UNAVAILABLE,
                    "lease file still present after release",
                    resource=resource,
                    run_id=run_id,
                )
            return {
                "released": True,
                "resource": resource,
                "run_id": run_id,
                "already_gone": False,
                "lease_id": record["lease_id"],
            }


def load_release_history(hermes_home) -> list[dict]:
    path = _leases_dir(hermes_home) / _RELEASED_FILENAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    records: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def active_leases(hermes_home) -> list[dict]:
    root = _leases_dir(hermes_home)
    if not root.is_dir():
        return []
    found: list[dict] = []
    for path in sorted(root.glob("*.json")):
        data = load_json(path)
        if isinstance(data, dict) and data.get("schema") == LEASE_SCHEMA:
            found.append(data)
    return found


def lease_records(hermes_home) -> list[dict]:
    return active_leases(hermes_home) + load_release_history(hermes_home)


def _leases_dir(hermes_home) -> Path:
    return Path(hermes_home) / "runtime" / "development-workflow" / "ui-leases"


def _append_release_record(leases_dir: Path, record: dict) -> None:
    path = leases_dir / _RELEASED_FILENAME
    with _lease_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)


def _normalize_resource_id(resource_id: str) -> str:
    if not isinstance(resource_id, str) or not resource_id.strip():
        raise HarnessError(
            WORKSPACE_INVALID,
            f"UI resource id is invalid: {resource_id!r}",
            resource=resource_id,
        )
    normalized = resource_id.strip().lower()
    if not _RESOURCE_ID_RE.fullmatch(normalized):
        raise HarnessError(
            WORKSPACE_INVALID,
            f"UI resource id is invalid: {resource_id!r}",
            resource=resource_id,
        )
    return normalized


def _new_lease(
    *,
    resource: str,
    board,
    card_id,
    run_id,
    candidate_commit,
) -> dict[str, Any]:
    pid = os.getpid()
    return {
        "schema": LEASE_SCHEMA,
        "lease_id": uuid.uuid4().hex,
        "resource": resource,
        "board": board,
        "card_id": card_id,
        "run_id": run_id,
        "pid": pid,
        "process_start": _ps_lstart(pid),
        "candidate_commit": candidate_commit,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _ps_lstart(pid: int) -> str | None:
    proc = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = proc.stdout.strip()
    return output if proc.returncode == 0 and output else None


@contextlib.contextmanager
def _lease_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
