#!/usr/bin/env python3
"""Development monitor gate: development-monitor.v2 plus historical resume.v1 check.

One Kanban card owns exactly one recurring monitor: one Cron job, one generated
wrapper, and one card-level monitor-state.json.  Relay attempts stay immutable
under the card directory (attempts/<generation>-<operation>/).  Stage changes,
retries, and recoveries only mutate the single monitor state.  Event ids and
fingerprints are fenced by generation, so terminal files from an older attempt
can neither wake nor suppress the active one.

New work uses ``--state <path>``.  Historical ``development-resume.v1`` files
remain readable through ``--resume <path> --check`` only; they are never
rewritten and never generate wrappers.

Both contracts are indented JSON, a strict YAML subset Python 3.9 can parse
without YAML tags, aliases, or implicit typing.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import py_compile
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple


SCHEMA_VERSION = 1
MONITOR_SCHEMA_VERSION = 2
MONITOR_SCHEMA_ID = "development-monitor.v2"
MONITOR_STATE_BASENAME = "monitor-state.json"
RESUME_BASENAME = "resume.yaml"
RESULT_SCHEMA = "delegate-relay.result.v1"
PROVIDERS = {"cursor", "codex", "opencode", "pi"}
MODES = {"lightweight", "initiative"}
MONITOR_PHASES = {"relay_running", "closed"}
MONITOR_STATES = {"idle", "relay_running", "closed"}
ZERO_AGENT_MONITOR_STATES = {"idle", "closed"}
KNOWN_OPERATIONS = ("direct", "write-plan", "execute-plan", "rework", "recovery")
ATTEMPT_FIELDS = (
    "provider", "session_id", "pid", "process_identity", "out_dir",
    "started_at", "stall_threshold_min", "max_duration_min",
)
MONITOR_STATE_REQUIRED = (
    "schema_version", "schema_id", "card_id", "project", "repo",
    "origin", "product", "monitor", "attempt",
)
MONITOR_BLOCK_REQUIRED = (
    "state", "operation", "generation", "cron_job_id", "wrapper_path",
    "state_path", "pending_event",
)
RESULT_STATUSES = {
    "completed", "failed", "timeout", "aborted", "unavailable",
    "cursor_agent_unavailable", "codex_unavailable", "opencode_unavailable",
}
ACTIONABLE_STATES = {
    "COMPLETED", "FAILED", "ABORTED", "EXITED_WITHOUT_RESULT",
    "MALFORMED_RESULT", "STALLED", "TIMEOUT", "AWAITING_INPUT",
}
NORMALIZED_STATES = ACTIONABLE_STATES | {
    "RUNNING", "IDLE", "BAD_STATE", "ACCEPTANCE_STARTED", "CLOSED",
}
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
SAFE_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
GENERATION_FENCE = re.compile(r"^g(\d+)$")
SCRIPT_ROOT = Path("/Users/kenan/.hermes/scripts")
MONITOR_ROOT = SCRIPT_ROOT / "generated-development-monitors"
FEISHU_SCRIPT = SCRIPT_ROOT / "feishu.py"
KNOWN_ACTIVITY_FILES = ("events.jsonl", "result.json", "final.txt", "stderr.txt")
RETRY_DELAYS_MIN = (10, 30, 60)


class ResumeContractError(ValueError):
    """A monitor state or resume record is missing or violates its contract."""


MonitorStateError = ResumeContractError


class WrapperError(RuntimeError):
    """A per-task wrapper cannot be created safely."""


@dataclass(frozen=True)
class ProcessInfo:
    alive: bool
    identity_valid: bool = True
    exit_code: Optional[int] = None
    command: Optional[str] = None


@dataclass(frozen=True)
class RelayObservation:
    state: str
    detail: str
    task_id: Optional[str]
    process_alive: bool
    process_identity_valid: bool
    result_status: Optional[str]
    last_activity_epoch: Optional[float]
    observed_at_epoch: float
    fingerprint: str
    card_id: Optional[str] = None
    monitor_state: Optional[str] = None
    operation: Optional[str] = None
    generation: Optional[int] = None


def _require_dict(value: Any, location: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ResumeContractError(f"{location} must be an object")
    return value


def _require_keys(value: Dict[str, Any], keys: Tuple[str, ...], location: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise ResumeContractError(f"{location} missing required field(s): {', '.join(missing)}")


def _string(value: Any, location: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ResumeContractError(f"{location} must be a non-empty string")
    return value


def _nullable_string(value: Any, location: str) -> None:
    if value is not None:
        _string(value, location)


def _positive_int(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResumeContractError(f"{location} must be a positive integer")
    return value


def _nonnegative_int(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResumeContractError(f"{location} must be a non-negative integer")
    return value


def _absolute_path(value: Any, location: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    path = _string(value, location)
    if not os.path.isabs(path):
        raise ResumeContractError(f"{location} must be an absolute path")
    if "\x00" in path or "\n" in path or "\r" in path:
        raise ResumeContractError(f"{location} contains a control character")


def _parse_datetime(value: Any, location: str) -> datetime:
    text = _string(value, location)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResumeContractError(f"{location} must be ISO-8601: {exc}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResumeContractError(f"{location} must include a timezone")
    return parsed


def safe_task_id(task_id: str) -> str:
    """Return an injective ASCII filename stem for a validated historical task id."""
    if not isinstance(task_id, str) or not SAFE_TOKEN.fullmatch(task_id):
        raise ResumeContractError(
            "task_id must use only letters, digits, dot, underscore, colon, and hyphen"
        )
    encoded = "".join(ch if ch.isascii() and ch.isalnum() else f"_{ord(ch):02x}" for ch in task_id)
    if len(encoded) > 220:
        raise ResumeContractError("task_id is too long for a safe wrapper filename")
    return encoded


def safe_card_id(card_id: str) -> str:
    """Return the wrapper filename stem for a validated Kanban card id."""
    if not isinstance(card_id, str) or not SAFE_BASENAME.fullmatch(card_id):
        raise ResumeContractError(
            "card_id must use only letters, digits, dot, underscore, and hyphen"
        )
    if len(card_id) > 200:
        raise ResumeContractError("card_id is too long for a safe wrapper filename")
    if card_id != os.path.basename(card_id):
        raise ResumeContractError("card_id must be a bare basename")
    return card_id


def _validate_pending_event(value: Any, location: str = "monitor.pending_event") -> None:
    if value is None:
        return
    event = _require_dict(value, location)
    _string(event.get("id"), f"{location}.id")
    if "generation" in event and event["generation"] is not None:
        _nonnegative_int(event["generation"], f"{location}.generation")
    for name in ("next_retry_at", "acknowledged_at", "manual_notified_at"):
        if name in event and event[name] is not None:
            _parse_datetime(event[name], f"{location}.{name}")
    if "retry_index" in event:
        index = event["retry_index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index > len(RETRY_DELAYS_MIN):
            raise ResumeContractError(f"{location}.retry_index is invalid")


def _validate_origin(value: Any) -> None:
    origin = _require_dict(value, "origin")
    _require_keys(origin, ("platform", "chat_id", "label"), "origin")
    if origin["platform"] != "feishu":
        raise ResumeContractError("origin.platform must be feishu")
    chat_id = _string(origin["chat_id"], "origin.chat_id")
    if not re.fullmatch(r"oc_[A-Za-z0-9_-]+", chat_id):
        raise ResumeContractError("origin.chat_id must be an oc_ Feishu chat id")
    _string(origin["label"], "origin.label")


def _validate_runtime(value: Any, location: str, required: Tuple[str, ...]) -> Dict[str, Any]:
    runtime = _require_dict(value, location)
    _require_keys(runtime, required, location)
    if runtime["provider"] not in PROVIDERS:
        raise ResumeContractError(f"{location}.provider must be one of {sorted(PROVIDERS)}")
    session_id = _string(runtime["session_id"], f"{location}.session_id")
    if not SAFE_TOKEN.fullmatch(session_id):
        raise ResumeContractError(f"{location}.session_id contains unsupported characters")
    pid = _positive_int(runtime["pid"], f"{location}.pid")
    if pid > 2_147_483_647:
        raise ResumeContractError(f"{location}.pid exceeds the supported process id range")
    identity = _string(runtime["process_identity"], f"{location}.process_identity")
    if not SAFE_BASENAME.fullmatch(identity) or os.path.basename(identity) != identity:
        raise ResumeContractError(f"{location}.process_identity must be a safe basename")
    _parse_datetime(runtime["started_at"], f"{location}.started_at")
    _positive_int(runtime["stall_threshold_min"], f"{location}.stall_threshold_min")
    _positive_int(runtime["max_duration_min"], f"{location}.max_duration_min")
    return runtime


def validate_resume(value: Any) -> Dict[str, Any]:
    """Validate and return a development-resume.v1 object; unknown versions fail closed."""
    resume = _require_dict(value, "resume")
    _require_keys(
        resume,
        (
            "schema_version", "task_id", "project", "mode", "initiative_id", "item_id",
            "repo", "out_dir", "origin", "product", "relay", "monitor", "acceptance",
        ),
        "resume",
    )
    version = resume["schema_version"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise ResumeContractError(f"unsupported schema_version: {version!r}")
    task_id = resume["task_id"]
    safe_task_id(task_id)
    task_parts = task_id.split(":")
    if len(task_parts) != 3 or any(not SAFE_BASENAME.fullmatch(part) for part in task_parts):
        raise ResumeContractError("task_id must have exactly project:slug:run-id")
    _string(resume["project"], "project")
    if resume["mode"] not in MODES:
        raise ResumeContractError(f"mode must be one of {sorted(MODES)}")
    _nullable_string(resume["initiative_id"], "initiative_id")
    _nullable_string(resume["item_id"], "item_id")
    _absolute_path(resume["repo"], "repo")
    _absolute_path(resume["out_dir"], "out_dir")
    _validate_origin(resume["origin"])

    product = _require_dict(resume["product"], "product")
    _require_keys(product, ("goal", "acceptance_summary"), "product")
    _string(product["goal"], "product.goal")
    summary = product["acceptance_summary"]
    if not isinstance(summary, list) or not summary:
        raise ResumeContractError("product.acceptance_summary must be a non-empty list")
    for index, item in enumerate(summary):
        _string(item, f"product.acceptance_summary[{index}]")

    _validate_runtime(
        resume["relay"],
        "relay",
        (
            "provider", "session_id", "pid", "process_identity", "started_at",
            "stall_threshold_min", "max_duration_min",
        ),
    )

    monitor = _require_dict(resume["monitor"], "monitor")
    _require_keys(
        monitor,
        ("phase", "cron_job_id", "wrapper_path", "last_status_sent_at", "pending_event"),
        "monitor",
    )
    if monitor["phase"] not in MONITOR_PHASES:
        raise ResumeContractError(f"monitor.phase must be one of {sorted(MONITOR_PHASES)}")
    _nullable_string(monitor["cron_job_id"], "monitor.cron_job_id")
    _absolute_path(monitor["wrapper_path"], "monitor.wrapper_path", nullable=True)
    if monitor["last_status_sent_at"] is not None:
        _parse_datetime(monitor["last_status_sent_at"], "monitor.last_status_sent_at")
    _validate_pending_event(monitor["pending_event"])

    acceptance = _require_dict(resume["acceptance"], "acceptance")
    _require_keys(acceptance, ("phase", "run_id", "evidence_dir", "failed_scenarios"), "acceptance")
    _string(acceptance["phase"], "acceptance.phase")
    _nullable_string(acceptance["run_id"], "acceptance.run_id")
    _absolute_path(acceptance["evidence_dir"], "acceptance.evidence_dir")
    failed = acceptance["failed_scenarios"]
    if not isinstance(failed, list):
        raise ResumeContractError("acceptance.failed_scenarios must be a list")
    for index, item in enumerate(failed):
        _string(item, f"acceptance.failed_scenarios[{index}]")
    return resume


def load_resume(path: os.PathLike) -> Dict[str, Any]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResumeContractError(f"cannot read resume: {exc}") from exc
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ResumeContractError(f"resume is not JSON-compatible YAML: {exc}") from exc
    return validate_resume(value)


def _write_json_atomic(path: os.PathLike, value: Dict[str, Any]) -> None:
    """Write indented JSON through a same-directory temp file, fsync, and replace."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        try:
            directory_fd = os.open(str(destination.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def validate_monitor_state(value: Any) -> Dict[str, Any]:
    """Validate and return a development-monitor.v2 card state; unknown versions fail closed."""
    state = _require_dict(value, "monitor_state")
    _require_keys(state, MONITOR_STATE_REQUIRED, "monitor_state")
    version = state["schema_version"]
    if isinstance(version, bool) or version != MONITOR_SCHEMA_VERSION:
        raise MonitorStateError(f"unsupported schema_version: {version!r}")
    if state["schema_id"] != MONITOR_SCHEMA_ID:
        raise MonitorStateError(f"unsupported schema_id: {state['schema_id']!r}")
    safe_card_id(state["card_id"])
    _string(state["project"], "project")
    _absolute_path(state["repo"], "repo")
    _validate_origin(state["origin"])
    product = _require_dict(state["product"], "product")
    _require_keys(product, ("goal",), "product")
    _string(product["goal"], "product.goal")

    monitor = _require_dict(state["monitor"], "monitor")
    _require_keys(monitor, MONITOR_BLOCK_REQUIRED, "monitor")
    if monitor["state"] not in MONITOR_STATES:
        raise MonitorStateError(f"monitor.state must be one of {sorted(MONITOR_STATES)}")
    _nullable_string(monitor["operation"], "monitor.operation")
    _nonnegative_int(monitor["generation"], "monitor.generation")
    _nullable_string(monitor["cron_job_id"], "monitor.cron_job_id")
    _absolute_path(monitor["wrapper_path"], "monitor.wrapper_path", nullable=True)
    _absolute_path(monitor["state_path"], "monitor.state_path", nullable=True)
    _validate_pending_event(monitor["pending_event"])

    attempt = state["attempt"]
    if attempt is None:
        if monitor["state"] == "relay_running":
            raise MonitorStateError("attempt is required while monitor.state is relay_running")
    else:
        _validate_runtime(attempt, "attempt", ATTEMPT_FIELDS)
        _absolute_path(attempt["out_dir"], "attempt.out_dir")
    return state


def load_monitor_state(path: os.PathLike) -> Dict[str, Any]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MonitorStateError(f"cannot read monitor state: {exc}") from exc
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise MonitorStateError(f"monitor state is not JSON-compatible YAML: {exc}") from exc
    return validate_monitor_state(value)


def write_monitor_state_atomic(path: os.PathLike, value: Dict[str, Any]) -> None:
    """Validate, fsync, and atomically replace monitor-state.json from the same directory."""
    validate_monitor_state(value)
    _write_json_atomic(path, value)


def update_monitor_state(
    path: os.PathLike, mutator: Callable[[Dict[str, Any]], None]
) -> Dict[str, Any]:
    """Apply a mutation to the single card monitor state; a raising mutator writes nothing."""
    value = copy.deepcopy(load_monitor_state(path))
    mutator(value)
    write_monitor_state_atomic(path, value)
    return value


def new_monitor_state(
    card_id: str, project: str, repo: str, origin: Dict[str, Any], goal: str,
    operation: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the idle, zero-agent monitor state a card starts its single Cron with."""
    state = {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "schema_id": MONITOR_SCHEMA_ID,
        "card_id": card_id,
        "project": project,
        "repo": repo,
        "origin": dict(origin),
        "product": {"goal": goal},
        "monitor": {
            "state": "idle",
            "operation": operation,
            "generation": 0,
            "cron_job_id": None,
            "wrapper_path": None,
            "state_path": None,
            "pending_event": None,
        },
        "attempt": None,
    }
    return validate_monitor_state(state)


def rearm_attempt(
    path: os.PathLike, attempt: Dict[str, Any],
    operation: Optional[str] = None, now: Any = None,
) -> Dict[str, Any]:
    """Atomically bind a fresh attempt: increment generation and clear pending_event.

    Every new Relay increments ``monitor.generation`` and must bind a new
    ``out_dir``.  The attempt block is rebuilt from a whitelist so no stale
    identity or event survives the rearm.
    """
    source = _require_dict(attempt, "attempt")
    current = _coerce_now(now)
    fresh = {key: copy.deepcopy(source[key]) for key in ATTEMPT_FIELDS if key in source}
    fresh.setdefault("started_at", current.isoformat())
    _require_keys(fresh, ATTEMPT_FIELDS, "attempt")

    def mutate(value: Dict[str, Any]) -> None:
        monitor = value["monitor"]
        previous = value.get("attempt")
        if isinstance(previous, dict) and previous.get("out_dir") == fresh["out_dir"]:
            raise MonitorStateError(
                "a new generation must use a new attempt out_dir; attempts are immutable"
            )
        monitor["generation"] = _nonnegative_int(monitor["generation"], "monitor.generation") + 1
        if operation is not None:
            monitor["operation"] = _string(operation, "operation")
        monitor["state"] = "relay_running"
        monitor["pending_event"] = None
        value["attempt"] = fresh

    return update_monitor_state(path, mutate)


def idle_monitor(path: os.PathLike, now: Any = None) -> Dict[str, Any]:
    """Park the card's single monitor: every later tick is zero-agent, no Cron edit."""
    del now

    def mutate(value: Dict[str, Any]) -> None:
        value["monitor"]["state"] = "idle"
        value["monitor"]["pending_event"] = None

    return update_monitor_state(path, mutate)


def close_monitor(path: os.PathLike, now: Any = None) -> Dict[str, Any]:
    """Record final card closure; Cron teardown remains a later non-source action."""
    del now

    def mutate(value: Dict[str, Any]) -> None:
        value["monitor"]["state"] = "closed"
        value["monitor"]["pending_event"] = None

    return update_monitor_state(path, mutate)


def _iso_now(now: Any = None) -> str:
    return _coerce_now(now).isoformat()


def _coerce_now(now: Any = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(float(now), timezone.utc)
    if isinstance(now, str):
        return _parse_datetime(now, "now")
    if not isinstance(now, datetime):
        raise TypeError("now must be a datetime, epoch, or None")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return now


def _generation_fence(generation: int) -> str:
    return f"g{generation}"


def event_generation(event_id: Any) -> Optional[int]:
    """Return the generation fenced into a v2 event id."""
    if not isinstance(event_id, str):
        return None
    for part in event_id.split(":"):
        matched = GENERATION_FENCE.fullmatch(part)
        if matched:
            return int(matched.group(1))
    return None


def _current_generation(state: Dict[str, Any]) -> int:
    return state["monitor"]["generation"]


def _pending_for_generation(pending: Any, generation: int) -> Optional[Dict[str, Any]]:
    """Return pending_event only when it belongs to the active generation."""
    if not isinstance(pending, dict):
        return None
    declared = pending.get("generation")
    if declared is not None and declared != generation:
        return None
    fenced = event_generation(pending.get("id"))
    if fenced is not None and fenced != generation:
        return None
    if declared is None and fenced is None:
        return None
    return pending


def acknowledge_event(path: os.PathLike, event_id: str, now: Any = None) -> Dict[str, Any]:
    """Mark an actionable monitor event handled; ACKs are refused across generations."""
    _string(event_id, "event_id")
    value = copy.deepcopy(load_monitor_state(path))
    generation = _current_generation(value)
    if event_generation(event_id) != generation:
        return value
    pending = value["monitor"].get("pending_event")
    if isinstance(pending, dict) and pending.get("id") == event_id and pending.get("acknowledged_at"):
        return value
    value["monitor"]["pending_event"] = {
        "id": event_id,
        "generation": generation,
        "acknowledged_at": _iso_now(now),
    }
    write_monitor_state_atomic(path, value)
    return value


def _command_has_identity(command: str, identity: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return any(token == identity or os.path.basename(token) == identity for token in tokens)


def default_process_probe(runtime: Dict[str, Any]) -> ProcessInfo:
    pid = runtime["pid"]
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return ProcessInfo(False)
    except PermissionError:
        pass
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ProcessInfo(True, False)
    command = result.stdout.strip()
    if result.returncode != 0 or not command:
        return ProcessInfo(False)
    return ProcessInfo(
        True, _command_has_identity(command, runtime["process_identity"]), command=command
    )


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _read_result(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[bytes]]:
    if not path.exists():
        return None, None, None
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"result is not readable JSON: {exc}", raw if "raw" in locals() else b""
    if not isinstance(value, dict):
        return None, "result must be an object", raw
    for key in ("schema", "status", "exitCode"):
        if key not in value:
            return value, f"result missing {key}", raw
    if value["schema"] != RESULT_SCHEMA:
        return value, f"unsupported result schema: {value['schema']!r}", raw
    if value["status"] not in RESULT_STATUSES:
        return value, f"unsupported result status: {value['status']!r}", raw
    if isinstance(value["exitCode"], bool) or not isinstance(value["exitCode"], int):
        return value, "result exitCode must be an integer", raw
    return value, None, raw


def _requests_input(value: Any) -> bool:
    if isinstance(value, dict):
        kind = str(value.get("type", "")).lower()
        subtype = str(value.get("subtype", "")).lower()
        status = str(value.get("status", "")).lower()
        if kind == "interaction_query" and subtype in {"request", "requested", "pending"}:
            return True
        if kind in {
            "permission_request", "permission_requested", "user_input_requested",
            "request_user_input", "awaiting_input", "input_request",
        }:
            return True
        if status in {"awaiting_input", "needs_input", "permission_pending"}:
            return True
        if value.get("requires_user_input") is True or value.get("permission_pending") is True:
            return True
        return any(_requests_input(item) for item in value.values())
    if isinstance(value, list):
        return any(_requests_input(item) for item in value)
    return False


def _resolves_input(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    kind = str(value.get("type", "")).lower()
    subtype = str(value.get("subtype", "")).lower()
    return kind in {"interaction_query", "permission_request", "input_request"} and subtype in {
        "response", "resolved", "completed", "cancelled", "denied", "approved",
    }


def _pending_input(events_path: Path) -> Tuple[bool, Optional[bytes]]:
    if not events_path.exists():
        return False, None
    pending = False
    basis = None
    try:
        with events_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if _resolves_input(event):
                    pending = False
                    basis = None
                elif _requests_input(event):
                    pending = True
                    basis = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except OSError:
        return False, None
    return pending, basis


def _pi_stop_reason(event: Dict[str, Any]) -> Optional[str]:
    reason = event.get("stopReason")
    if isinstance(reason, str) and reason:
        return reason
    message = event.get("message")
    if isinstance(message, dict):
        reason = message.get("stopReason")
        if isinstance(reason, str) and reason:
            return reason
    messages = event.get("messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if isinstance(item, dict):
                reason = item.get("stopReason")
                if isinstance(reason, str) and reason:
                    return reason
    return None


def parse_pi_events(path: os.PathLike) -> Dict[str, Any]:
    """Parse Pi ``--mode json`` events.jsonl into C16 monitor fields."""
    session_id = None
    cwd = None
    auto_retry_count = 0
    agent_settled = False
    last_stop_reason = None
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get("type")
                if kind == "session" and session_id is None:
                    sid = event.get("id")
                    if isinstance(sid, str) and sid:
                        session_id = sid
                    event_cwd = event.get("cwd")
                    if isinstance(event_cwd, str) and event_cwd:
                        cwd = event_cwd
                elif kind == "auto_retry_start":
                    auto_retry_count += 1
                elif kind == "agent_settled":
                    agent_settled = True
                stop = _pi_stop_reason(event)
                if stop is not None:
                    last_stop_reason = stop
    except OSError:
        pass
    return {
        "session_id": session_id,
        "cwd": cwd,
        "auto_retry_count": auto_retry_count,
        "agent_settled": agent_settled,
        "last_stop_reason": last_stop_reason,
    }


def _last_activity(out_dir: Path) -> Optional[float]:
    mtimes = []
    for name in KNOWN_ACTIVITY_FILES:
        path = out_dir / name
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    return max(mtimes) if mtimes else None


def _feature_fingerprint(
    runtime: Dict[str, Any], state: str, basis: Optional[bytes], last: Optional[float],
    fence: Optional[str] = None,
) -> str:
    if basis is not None:
        return _sha(basis if fence is None else fence.encode("utf-8") + b"\x00" + basis)
    feature = {
        "state": state,
        "pid": runtime["pid"],
        "started_at": runtime["started_at"],
        "last_activity": int(last) if last is not None and state == "STALLED" else None,
    }
    if fence is not None:
        feature["fence"] = fence
    return _sha(json.dumps(feature, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _observation(
    state: str, detail: str, resume: Optional[Dict[str, Any]], process: ProcessInfo,
    status: Optional[str], last: Optional[float], now: datetime, basis: Optional[bytes] = None,
) -> RelayObservation:
    fingerprint = "bad-state"
    task_id = None
    if resume is not None:
        task_id = resume["task_id"]
        fingerprint = _feature_fingerprint(resume["relay"], state, basis, last)
    return RelayObservation(
        state, detail, task_id, process.alive, process.identity_valid, status,
        last, now.timestamp(), fingerprint,
    )


def _classify_pi_runtime(
    runtime: Dict[str, Any], current: datetime, process: ProcessInfo,
    events_path: Path, last: Optional[float],
) -> Tuple[str, str, ProcessInfo, Optional[str], Optional[float], Optional[bytes]]:
    """Classify a legacy Pi JSONL relay that did not publish result.json."""
    parsed = parse_pi_events(events_path)
    awaiting, input_basis = _pending_input(events_path)
    effectively_alive = process.alive and process.identity_valid
    if not effectively_alive:
        if parsed["agent_settled"]:
            return (
                "COMPLETED", "Pi process exited after agent_settled", process, None, last, None,
            )
        if process.exit_code == 143:
            return "ABORTED", "Relay process exited", process, None, last, None
        detail = "Relay process exited" if not process.alive else "Relay PID identity mismatched"
        return "EXITED_WITHOUT_RESULT", detail, process, None, last, None
    if awaiting:
        return (
            "AWAITING_INPUT", "Relay requested input or permission", process, None,
            last, input_basis,
        )
    started = _parse_datetime(runtime["started_at"], "started_at")
    elapsed = (current - started).total_seconds()
    if elapsed >= runtime["max_duration_min"] * 60:
        return "TIMEOUT", "Relay exceeded max duration", process, None, last, None
    stall_seconds = runtime["stall_threshold_min"] * 60
    startup_grace = min(120, stall_seconds)
    if not events_path.exists() and elapsed >= startup_grace:
        return (
            "STALLED", "Relay artifacts are missing after startup grace",
            process, None, last, None,
        )
    if last is not None and current.timestamp() - last >= stall_seconds:
        return (
            "STALLED", "Relay artifacts have not changed within the stall threshold",
            process, None, last, None,
        )
    return "RUNNING", "Relay process and artifacts are healthy", process, None, last, None


def _classify_runtime(
    runtime: Dict[str, Any], out_dir: Path, current: datetime,
    process_probe: Callable[[Dict[str, Any]], ProcessInfo],
) -> Tuple[str, str, ProcessInfo, Optional[str], Optional[float], Optional[bytes]]:
    """Classify one Relay attempt from its own out_dir only."""
    events_path = out_dir / "events.jsonl"
    result_path = out_dir / "result.json"
    last = _last_activity(out_dir)
    process = process_probe(runtime)
    if not isinstance(process, ProcessInfo):
        raise TypeError("process_probe must return ProcessInfo")
    result, result_error, result_raw = _read_result(result_path)
    # Historical Pi relays emitted only events.jsonl. New pi-delegate relays
    # publish the shared result contract and must use its terminal status; fall
    # back to JSONL classification only when no result was published at all.
    if runtime.get("provider") == "pi" and result is None and result_error is None:
        return _classify_pi_runtime(runtime, current, process, events_path, last)
    status = result.get("status") if isinstance(result, dict) else None
    awaiting, input_basis = _pending_input(events_path)

    if awaiting or (result is not None and _requests_input(result)):
        return (
            "AWAITING_INPUT", "Relay requested input or permission", process, status,
            last, input_basis or result_raw,
        )
    if result_error:
        return "MALFORMED_RESULT", result_error, process, status, last, result_raw

    effectively_alive = process.alive and process.identity_valid
    if not effectively_alive:
        if result is None:
            state = "ABORTED" if process.exit_code == 143 else "EXITED_WITHOUT_RESULT"
        elif status == "timeout":
            state = "TIMEOUT"
        elif status == "aborted" or result["exitCode"] == 143:
            state = "ABORTED"
        elif status == "completed" and result["exitCode"] == 0:
            state = "COMPLETED"
        else:
            state = "FAILED"
        detail = "Relay process exited" if not process.alive else "Relay PID identity mismatched"
        return state, detail, process, status, last, result_raw

    started = _parse_datetime(runtime["started_at"], "started_at")
    elapsed = (current - started).total_seconds()
    if elapsed >= runtime["max_duration_min"] * 60:
        return "TIMEOUT", "Relay exceeded max duration", process, status, last, result_raw
    if result is not None:
        return (
            "RUNNING", "Terminal result exists; waiting for Relay process exit",
            process, status, last, result_raw,
        )
    stall_seconds = runtime["stall_threshold_min"] * 60
    startup_grace = min(120, stall_seconds)
    if not events_path.exists() and elapsed >= startup_grace:
        return (
            "STALLED", "Relay artifacts are missing after startup grace",
            process, status, last, None,
        )
    if last is not None and current.timestamp() - last >= stall_seconds:
        return (
            "STALLED", "Relay artifacts have not changed within the stall threshold",
            process, status, last, None,
        )
    return "RUNNING", "Relay process and artifacts are healthy", process, status, last, None


def classify_relay(
    resume_path: os.PathLike, now: Any = None,
    process_probe: Callable[[Dict[str, Any]], ProcessInfo] = default_process_probe,
) -> RelayObservation:
    """Classify a historical development-resume.v1 file without rewriting it."""
    current = _coerce_now(now)
    try:
        resume = load_resume(resume_path)
    except ResumeContractError as exc:
        return _observation(
            "BAD_STATE", str(exc), None, ProcessInfo(False, False), None, None, current
        )
    if resume["monitor"]["phase"] == "closed":
        return _observation("CLOSED", "Resume is closed", resume, ProcessInfo(False), None, None, current)
    if resume["acceptance"]["phase"] != "not_started":
        return _observation(
            "ACCEPTANCE_STARTED", "Acceptance has started", resume, ProcessInfo(False), None, None, current
        )
    state, detail, process, status, last, basis = _classify_runtime(
        resume["relay"], Path(resume["out_dir"]), current, process_probe
    )
    return _observation(state, detail, resume, process, status, last, current, basis)


def _monitor_observation(
    state: str, detail: str, card: Optional[Dict[str, Any]], process: ProcessInfo,
    status: Optional[str], last: Optional[float], now: datetime, basis: Optional[bytes] = None,
) -> RelayObservation:
    if card is None:
        return RelayObservation(
            state, detail, None, process.alive, process.identity_valid, status,
            last, now.timestamp(), "bad-state",
        )
    monitor = card["monitor"]
    generation = _current_generation(card)
    fence = _generation_fence(generation)
    attempt = card.get("attempt")
    runtime = attempt if isinstance(attempt, dict) else {"pid": 0, "started_at": fence}
    return RelayObservation(
        state, detail, None, process.alive, process.identity_valid, status, last,
        now.timestamp(), _feature_fingerprint(runtime, state, basis, last, fence),
        card_id=card["card_id"], monitor_state=monitor["state"],
        operation=monitor["operation"], generation=generation,
    )


def classify_monitor_state(
    state_path: os.PathLike, now: Any = None,
    process_probe: Callable[[Dict[str, Any]], ProcessInfo] = default_process_probe,
) -> RelayObservation:
    """Classify the card's single monitor state, fenced to the current generation."""
    current = _coerce_now(now)
    try:
        card = load_monitor_state(state_path)
    except MonitorStateError as exc:
        return _monitor_observation(
            "BAD_STATE", str(exc), None, ProcessInfo(False, False), None, None, current
        )
    monitor_state = card["monitor"]["state"]
    if monitor_state in ZERO_AGENT_MONITOR_STATES:
        return _monitor_observation(
            "IDLE", f"Monitor state is {monitor_state}", card, ProcessInfo(False),
            None, None, current,
        )
    attempt = card["attempt"]
    state, detail, process, status, last, basis = _classify_runtime(
        attempt, Path(attempt["out_dir"]), current, process_probe
    )
    return _monitor_observation(state, detail, card, process, status, last, current, basis)


def default_sender(chat_id: str, text: str) -> bool:
    try:
        result = subprocess.run(
            ["/usr/bin/python3", str(FEISHU_SCRIPT), "send", "--chat", chat_id, "--text", text],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _send(sender: Callable[[str, str], Any], chat_id: str, text: str) -> bool:
    try:
        return sender(chat_id, text) is not False
    except Exception:
        return False


def _card_manual_message(card: Dict[str, Any], state: str) -> str:
    return f"开发任务 {card['card_id']}：Relay 状态 {state}，华生恢复失败，需要人工介入。"


def _card_event_id(card: Dict[str, Any], observation: RelayObservation) -> str:
    fence = _generation_fence(_current_generation(card))
    return f"{card['card_id']}:{fence}:{observation.state}:{observation.fingerprint}"


def _card_wake(path: Path, card: Dict[str, Any], event_id: str, state: str) -> Dict[str, Any]:
    return {
        "wakeAgent": True,
        "context": {
            "state_path": str(path),
            "card_id": card["card_id"],
            "event_id": event_id,
            "relay_state": state,
            "operation": card["monitor"]["operation"],
            "generation": _current_generation(card),
        },
    }


def _card_initial_pending(event_id: str, generation: int, now: datetime) -> Dict[str, Any]:
    return {
        "id": event_id,
        "generation": generation,
        "retry_index": 0,
        "next_retry_at": (now + timedelta(minutes=RETRY_DELAYS_MIN[0])).isoformat(),
    }


def _card_actionable_decision(
    path: Path, card: Dict[str, Any], observation: RelayObservation, now: datetime,
    sender: Callable[[str, str], Any],
) -> Dict[str, Any]:
    event_id = _card_event_id(card, observation)
    generation = _current_generation(card)
    pending = _pending_for_generation(card["monitor"].get("pending_event"), generation)
    if pending is None or pending.get("id") != event_id:
        updated = copy.deepcopy(card)
        updated["monitor"]["pending_event"] = _card_initial_pending(event_id, generation, now)
        write_monitor_state_atomic(path, updated)
        return _card_wake(path, card, event_id, observation.state)
    if pending.get("acknowledged_at") or pending.get("manual_notified_at"):
        return {"wakeAgent": False}
    next_retry = pending.get("next_retry_at")
    if next_retry is not None and now < _parse_datetime(next_retry, "monitor.pending_event.next_retry_at"):
        return {"wakeAgent": False}

    retry_index = pending.get("retry_index", 0)
    if retry_index < len(RETRY_DELAYS_MIN):
        updated = copy.deepcopy(card)
        event = updated["monitor"]["pending_event"]
        new_index = retry_index + 1
        event["retry_index"] = new_index
        event["next_retry_at"] = (
            (now + timedelta(minutes=RETRY_DELAYS_MIN[new_index])).isoformat()
            if new_index < len(RETRY_DELAYS_MIN) else None
        )
        write_monitor_state_atomic(path, updated)
        return _card_wake(path, card, event_id, observation.state)

    sent = _send(sender, card["origin"]["chat_id"], _card_manual_message(card, observation.state))
    if sent:
        updated = copy.deepcopy(card)
        updated["monitor"]["pending_event"]["manual_notified_at"] = now.isoformat()
        write_monitor_state_atomic(path, updated)
    return {"wakeAgent": False}


def card_cron_main(
    state_path: os.PathLike, now: Any = None,
    process_probe: Callable[[Dict[str, Any]], ProcessInfo] = default_process_probe,
    sender: Callable[[str, str], Any] = default_sender,
) -> int:
    """The card's single Cron tick: its sole stdout line is the wake decision JSON."""
    path = Path(state_path)
    current = _coerce_now(now)
    observation = classify_monitor_state(path, now=current, process_probe=process_probe)
    decision: Dict[str, Any] = {"wakeAgent": False}
    try:
        if observation.state in ACTIONABLE_STATES:
            card = load_monitor_state(path)
            try:
                decision = _card_actionable_decision(path, card, observation, current, sender)
            except OSError:
                decision = _card_wake(
                    path, card, _card_event_id(card, observation), observation.state
                )
    except (MonitorStateError, OSError):
        decision = {"wakeAgent": False}
    print(json.dumps(decision, ensure_ascii=False, separators=(",", ":")))
    return 0


def _contained(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _wrapper_destination(
    monitor_dir: os.PathLike, scripts_dir: os.PathLike, name: str
) -> Path:
    scripts_root = Path(scripts_dir).resolve()
    destination_dir = Path(monitor_dir).resolve()
    if not _contained(destination_dir, scripts_root) or destination_dir == scripts_root:
        raise WrapperError("wrapper directory must be contained below ~/.hermes/scripts")
    destination_dir.mkdir(parents=True, exist_ok=True)
    return destination_dir / name


def _wrapper_source(bound_path: Path) -> str:
    return (
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "sys.path.insert(0, os.path.expanduser(\"~/.hermes/scripts\"))\n"
        "from development_relay_gate import card_cron_main\n\n"
        f"raise SystemExit(card_cron_main({str(bound_path)!r}))\n"
    )


def _install_wrapper(destination: Path, source: str) -> bool:
    """Create the wrapper exclusively; an identical existing file is accepted."""
    try:
        fd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(source)
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except FileExistsError:
        try:
            existing = destination.read_text(encoding="utf-8")
        except OSError as exc:
            raise WrapperError(f"wrapper collision at {destination}: {exc}") from exc
        if existing != source or destination.is_symlink():
            raise WrapperError(f"wrapper collision at {destination}")
        return False


def _compile_wrapper(destination: Path) -> None:
    compiled = destination.parent / f".{destination.name}.compile.tmp"
    py_compile.compile(str(destination), cfile=str(compiled), doraise=True)
    try:
        compiled.unlink()
    except FileNotFoundError:
        pass


def make_card_wrapper(
    state_path: os.PathLike, monitor_dir: os.PathLike = MONITOR_ROOT,
    scripts_dir: os.PathLike = SCRIPT_ROOT,
) -> Path:
    """Create the card's one fixed wrapper, bound to one resolved monitor-state path."""
    state_path = Path(state_path)
    if not state_path.is_absolute():
        raise WrapperError("monitor state path must be absolute")
    state_path = state_path.resolve()
    card = load_monitor_state(state_path)
    destination = _wrapper_destination(
        monitor_dir, scripts_dir, f"card-{safe_card_id(card['card_id'])}.py"
    )
    source = _wrapper_source(state_path)
    created = _install_wrapper(destination, source)
    try:
        _compile_wrapper(destination)
        monitor = card["monitor"]
        if (monitor.get("wrapper_path"), monitor.get("state_path")) != (
            str(destination), str(state_path)
        ):
            card = copy.deepcopy(card)
            card["monitor"]["wrapper_path"] = str(destination)
            card["monitor"]["state_path"] = str(state_path)
            write_monitor_state_atomic(state_path, card)
    except Exception:
        if created:
            try:
                destination.unlink()
            except OSError:
                pass
        raise
    return destination


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--state", help=f"absolute path to the card {MONITOR_STATE_BASENAME}"
    )
    target.add_argument(
        "--resume",
        help=f"absolute path to a historical {RESUME_BASENAME} (check only)",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="classify without side effects")
    action.add_argument("--make-wrapper", action="store_true", help="create the card's cron wrapper")
    args = parser.parse_args(argv)
    path = args.state or args.resume
    if not os.path.isabs(path):
        parser.error("--state/--resume must be absolute")
    if args.resume and args.make_wrapper:
        parser.error("--make-wrapper requires --state; historical resume files are check-only")
    if args.make_wrapper:
        print(make_card_wrapper(path))
        return 0
    if args.resume:
        observation = classify_relay(path)
    else:
        observation = classify_monitor_state(path)
    print(json.dumps(asdict(observation), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
