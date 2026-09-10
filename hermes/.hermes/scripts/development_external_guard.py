#!/usr/bin/env python3
"""External-execution guard for the Hermes development workflow.

Fail-closed CLI that prevents duplicate Coding Agent Relay starts and records
exact-session recovery facts plus attempt/landing lineage.  Hermes Kanban
stays the only workflow control plane; this guard owns ONLY relay
identity/session/result evidence plus git baseline/landing facts (design
§9.2, §15).  Canonical state:

    <artifacts-root>/<board>/tasks/<card-id>/external-execution.json

Schema ``development-external-execution.v2`` stores append-only ``attempts``
and ``landings``.  A valid v1 file migrates in place on the first exclusive
write (atomic ``external-execution.v1.bak.json`` backup).  Read-only
commands classify v1 without mutating it.

Commands: init | start-or-inspect | inspect | record-terminal | check-run |
record-commit.  Outcomes: spawned | attach | terminal | uncertain (``inspect``
also reports ``none`` before the first attempt).  Ambiguity never causes a
second spawn; it classifies ``uncertain`` and durably blocks new attempts.

Exit codes: 0 classified outcome (uncertain included); 2 usage; 3 init
conflict or state-transition violation; 4 corrupt/missing state or invalid
evidence; 5 check-run failure; 6 unexpected internal error.  Every command
prints one JSON object to stdout.  Stdlib only; ``check-run`` lazily imports
the installed ``hermes_cli`` runtime, bootstrapping ``sys.path`` from
``<home>/hermes-agent``.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_V1 = "development-external-execution.v1"
SCHEMA_V2 = "development-external-execution.v2"
SCHEMA = SCHEMA_V2
RESULT_SCHEMA = "delegate-relay.result.v1"
RESULT_STATUSES = ("completed", "failed", "timeout", "aborted", "unavailable")
OPERATIONS = ("planning", "execution", "rework")
ATTEMPT_STATES = ("reserved", "running", "terminal", "uncertain")
NON_TERMINAL_STATES = ("reserved", "running", "uncertain")
ATTEMPT_KEYS = ("number", "operation", "state", "pid", "process_start",
                "out_dir", "result_path", "session_id", "terminal_status")
V1_ATTEMPT_KEYS = ("number", "operation", "state", "pid", "process_start",
                   "out_dir", "result_path", "session_id")
LANDING_KEYS = ("attempt_number", "commit", "parent", "recorded_at")
TERMINAL_CARD_STATUSES = ("done", "archived")
V1_BACKUP_NAME = "external-execution.v1.bak.json"
EXIT_OK, EXIT_USAGE, EXIT_CONFLICT = 0, 2, 3
EXIT_EVIDENCE, EXIT_CHECK_RUN, EXIT_INTERNAL = 4, 5, 6


class GuardError(Exception):
    """Fail-closed refusal; ``code`` is the process exit status."""

    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _bad(reason: str) -> GuardError:
    return GuardError(EXIT_EVIDENCE, reason)


def report(command: str, outcome: str, ok: bool = True, **info: Any) -> None:
    """Every command answers with exactly one JSON object on stdout."""
    payload = {"ok": ok, "command": command, "outcome": outcome}
    payload.update(info)
    print(json.dumps(payload, sort_keys=True))
    sys.stdout.flush()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but is another user's
    except OSError:
        return False
    return True


def ps_lstart(pid: int) -> Optional[str]:
    """Exact ``ps -o lstart= -p PID`` output, or None when unavailable."""
    proc = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                          capture_output=True, text=True, check=False)
    output = proc.stdout.strip()
    return output if proc.returncode == 0 and output else None


def git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True, check=False)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_optional_str(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


# --- State I/O: one advisory lock; atomic temp-file + os.replace writes ---

def state_path_for(args: argparse.Namespace) -> Path:
    return Path(args.artifacts_root) / args.board / "tasks" / args.card_id \
        / "external-execution.json"


def v1_backup_path(path: Path) -> Path:
    return path.parent / V1_BACKUP_NAME


@contextlib.contextmanager
def state_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=".external-execution.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _validate_attempt_fields(attempt: Any, *, keys: Tuple[str, ...],
                             require_terminal_status: bool) -> None:
    if not isinstance(attempt, dict) or any(k not in attempt for k in keys):
        raise _bad("state-attempt-corrupt")
    number, pid = attempt.get("number"), attempt.get("pid")
    ok = (
        attempt["state"] in ATTEMPT_STATES
        and attempt["operation"] in OPERATIONS
        and _is_int(number) and number >= 1
        and (pid is None or _is_int(pid))
        and _is_optional_str(attempt.get("process_start"))
        and _is_optional_str(attempt.get("session_id"))
        and all(_is_nonempty_str(attempt[k]) for k in ("out_dir", "result_path"))
    )
    if require_terminal_status:
        terminal_status = attempt.get("terminal_status")
        ok = ok and (
            terminal_status is None
            or (isinstance(terminal_status, str)
                and terminal_status in RESULT_STATUSES)
        )
        if attempt["state"] != "terminal" and terminal_status is not None:
            ok = False
    if not ok:
        raise _bad("state-attempt-corrupt")


def _validate_v1_attempt(attempt: Any) -> None:
    if attempt is None:
        return
    _validate_attempt_fields(attempt, keys=V1_ATTEMPT_KEYS,
                             require_terminal_status=False)


def _validate_v2_attempt(attempt: Any) -> None:
    _validate_attempt_fields(attempt, keys=ATTEMPT_KEYS,
                             require_terminal_status=True)


def _validate_v1_state(state: Dict[str, Any], card_id: str) -> None:
    if state.get("card_id") != card_id:
        raise _bad("state-card-mismatch")
    repo, head, porcelain = (
        state.get("repo"), state.get("baseline_head"),
        state.get("baseline_porcelain"),
    )
    if not _is_nonempty_str(repo) or not _is_nonempty_str(head):
        raise _bad("harness-incompatible")
    if not isinstance(porcelain, list) or not all(isinstance(x, str) for x in porcelain):
        raise _bad("harness-incompatible")
    _validate_v1_attempt(state.get("attempt"))
    commit = state.get("commit")
    if commit is None:
        return
    if not (isinstance(commit, dict) and _is_nonempty_str(commit.get("sha"))):
        raise _bad("harness-incompatible")


def _validate_v2_state(state: Dict[str, Any], card_id: str) -> None:
    if state.get("schema") != SCHEMA_V2:
        raise _bad("state-schema-invalid")
    if state.get("card_id") != card_id:
        raise _bad("state-card-mismatch")
    if not _is_nonempty_str(state.get("repo")):
        raise _bad("state-schema-invalid")
    baseline = state.get("baseline")
    if not (
        isinstance(baseline, dict)
        and _is_nonempty_str(baseline.get("head"))
        and isinstance(baseline.get("porcelain"), list)
        and all(isinstance(x, str) for x in baseline["porcelain"])
    ):
        raise _bad("state-schema-invalid")
    attempts = state.get("attempts")
    landings = state.get("landings")
    if not isinstance(attempts, list) or not isinstance(landings, list):
        raise _bad("state-schema-invalid")
    non_terminal = 0
    by_number: Dict[int, Dict[str, Any]] = {}
    for index, attempt in enumerate(attempts, start=1):
        _validate_v2_attempt(attempt)
        if attempt["number"] != index:
            raise _bad("state-attempt-corrupt")
        if attempt["state"] in NON_TERMINAL_STATES:
            non_terminal += 1
        by_number[attempt["number"]] = attempt
    if non_terminal > 1:
        raise _bad("state-attempt-corrupt")
    seen_commits: set = set()
    for landing in landings:
        if not isinstance(landing, dict) or any(k not in landing for k in LANDING_KEYS):
            raise _bad("state-landing-corrupt")
        number, commit, parent, recorded_at = (
            landing.get("attempt_number"), landing.get("commit"),
            landing.get("parent"), landing.get("recorded_at"),
        )
        if not _is_nonempty_str(commit) or not isinstance(parent, str) \
                or not _is_nonempty_str(recorded_at):
            raise _bad("state-landing-corrupt")
        if number is not None:
            if not _is_int(number) or number not in by_number:
                raise _bad("state-landing-corrupt")
            if by_number[number]["state"] != "terminal":
                raise _bad("state-landing-corrupt")
        if commit in seen_commits:
            raise _bad("state-landing-corrupt")
        seen_commits.add(commit)


def _read_raw_state(path: Path) -> Tuple[bytes, Any]:
    try:
        raw = path.read_bytes()
    except OSError:
        raise _bad("state-missing")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise _bad("state-corrupt-json")
    return raw, parsed


def git_first_parent(repo: str, sha: str, *, missing_reason: str) -> str:
    """First parent SHA of ``sha``, or ``''`` for a root commit."""
    parents = git(repo, "rev-parse", f"{sha}^@")
    if parents.returncode == 0:
        lines = [line.strip() for line in parents.stdout.splitlines() if line.strip()]
        if lines:
            return lines[0]
        verify = git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}")
        if verify.returncode == 0 and verify.stdout.strip():
            return ""
        raise _bad(missing_reason)
    pretty = git(repo, "log", "-1", "--format=%P", sha)
    if pretty.returncode == 0:
        parts = pretty.stdout.strip().split()
        return parts[0] if parts else ""
    raise _bad(missing_reason)


def git_full_sha(repo: str, sha: str, *, missing_reason: str) -> str:
    resolved = git(repo, "rev-parse", f"{sha}^{{commit}}")
    if resolved.returncode != 0 or not resolved.stdout.strip():
        raise _bad(missing_reason)
    return resolved.stdout.strip()


def _v1_attempt_to_v2(attempt: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if attempt is None:
        return None
    converted = {key: attempt[key] for key in V1_ATTEMPT_KEYS}
    converted["terminal_status"] = None
    return converted


def _v1_to_v2(v1: Dict[str, Any], *, recorded_at: str,
              resolve_parent: bool) -> Dict[str, Any]:
    attempt = _v1_attempt_to_v2(v1.get("attempt"))
    attempts: List[Dict[str, Any]] = [] if attempt is None else [attempt]
    landings: List[Dict[str, Any]] = []
    commit = v1.get("commit")
    if isinstance(commit, dict) and _is_nonempty_str(commit.get("sha")):
        sha = commit["sha"]
        parent = ""
        if resolve_parent:
            sha = git_full_sha(v1["repo"], sha,
                               missing_reason="migration-commit-unresolvable")
            parent = git_first_parent(
                v1["repo"], sha, missing_reason="migration-commit-unresolvable")
        attempt_number = None
        if attempts:
            if attempts[0]["state"] != "terminal":
                raise _bad("harness-incompatible")
            attempt_number = attempts[0]["number"]
        landings.append({
            "attempt_number": attempt_number,
            "commit": sha,
            "parent": parent,
            "recorded_at": recorded_at,
        })
    return {
        "schema": SCHEMA_V2,
        "card_id": v1["card_id"],
        "repo": v1["repo"],
        "baseline": {
            "head": v1["baseline_head"],
            "porcelain": list(v1["baseline_porcelain"]),
        },
        "attempts": attempts,
        "landings": landings,
    }


def _migrate_v1(path: Path, raw: bytes, v1: Dict[str, Any],
                card_id: str) -> Dict[str, Any]:
    """Lossless v1→v2 rewrite. Fail closed before touching files on error."""
    _validate_v1_state(v1, card_id)
    migrated = _v1_to_v2(v1, recorded_at=utc_now(), resolve_parent=True)
    _validate_v2_state(migrated, card_id)
    _atomic_write_bytes(v1_backup_path(path), raw)
    write_state(path, migrated)
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    _validate_v2_state(reloaded, card_id)
    return reloaded


def load_state(path: Path, card_id: str, *, migrate: bool = False) -> Dict[str, Any]:
    raw, parsed = _read_raw_state(path)
    if not isinstance(parsed, dict):
        raise _bad("state-corrupt-json")
    schema = parsed.get("schema")
    if schema == SCHEMA_V2:
        _validate_v2_state(parsed, card_id)
        return parsed
    if schema == SCHEMA_V1:
        _validate_v1_state(parsed, card_id)
        if migrate:
            return _migrate_v1(path, raw, parsed, card_id)
        converted = _v1_to_v2(parsed, recorded_at=utc_now(), resolve_parent=False)
        _validate_v2_state(converted, card_id)
        return converted
    raise _bad("state-schema-invalid")


def write_state(path: Path, state: Dict[str, Any]) -> None:
    state["schema"] = SCHEMA_V2
    state["updated_at"] = utc_now()
    _validate_v2_state(state, state["card_id"])
    data = json.dumps(state, indent=2) + "\n"
    _atomic_write_bytes(path, data.encode("utf-8"))


def current_attempt(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    attempts = state["attempts"]
    return attempts[-1] if attempts else None


def latest_terminal_attempt(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for attempt in reversed(state["attempts"]):
        if attempt["state"] == "terminal":
            return attempt
    return None


def non_terminal_attempt(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    found = [a for a in state["attempts"] if a["state"] != "terminal"]
    return found[-1] if found else None


def attempts_summary(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"number": a["number"], "operation": a["operation"],
             "state": a["state"]} for a in state["attempts"]]


def landings_summary(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"attempt_number": row["attempt_number"], "commit": row["commit"]}
            for row in state["landings"]]


def next_attempt_number(state: Dict[str, Any]) -> int:
    attempts = state["attempts"]
    return (max(a["number"] for a in attempts) + 1) if attempts else 1


# --- Relay result evidence --------------------------------------------------

def load_result(result_path: str) -> Tuple[Optional[dict], Optional[str]]:
    try:
        raw = Path(result_path).read_text(encoding="utf-8")
    except OSError:
        return None, "result-missing"
    try:
        result = json.loads(raw)
    except ValueError:
        return None, "result-malformed"
    if not isinstance(result, dict) or result.get("schema") != RESULT_SCHEMA:
        return None, "result-schema-mismatch"
    if result.get("status") not in RESULT_STATUSES:
        return None, "result-status-invalid"
    if result["status"] == "completed":
        exit_code = result.get("exitCode")
        if not _is_int(exit_code) or exit_code != 0:
            return None, "result-exitcode-invalid"
        if not _is_nonempty_str(result.get("sessionId")):
            return None, "session-id-required-for-completed"
    return result, None


def result_session_id(result: dict) -> Optional[str]:
    for key in ("sessionId", "threadId"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    return None


# --- Classification (shared by start-or-inspect and inspect; no mutation) ---

def classify_attempt(attempt: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Map a recorded attempt to attach | terminal | uncertain using the most
    authoritative evidence first (live pid identity beats result files)."""
    if attempt["state"] == "terminal":
        return "terminal", {"attempt_number": attempt["number"],
                            "session_id": attempt["session_id"]}
    if attempt["state"] == "uncertain":
        return "uncertain", {"reason": "attempt-uncertain"}
    pid = attempt["pid"]
    if pid is None:
        return "uncertain", {"reason": "pid-missing"}
    if pid_alive(pid):
        recorded = attempt["process_start"]
        if not recorded:
            return "uncertain", {"reason": "process-start-missing"}
        current = ps_lstart(pid)
        if current is None:
            return "uncertain", {"reason": "process-unreachable"}
        if current != recorded:
            return "uncertain", {"reason": "pid-identity-mismatch"}
        return "attach", {"attempt_number": attempt["number"], "pid": pid}
    result, reason = load_result(attempt["result_path"])
    if result is None:
        return "uncertain", {"reason": reason}
    return "terminal", {"attempt_number": attempt["number"],
                        "session_id": result_session_id(result),
                        "status": result["status"]}


# --- Commands ---------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    if not repo.is_absolute():
        raise GuardError(EXIT_USAGE, "repo-not-absolute")
    if not repo.is_dir():
        raise _bad("repo-not-found")
    head = git(args.repo, "rev-parse", "HEAD")
    porcelain = git(args.repo, "status", "--porcelain")
    if head.returncode != 0 or not head.stdout.strip():
        raise _bad("repo-not-git")
    if porcelain.returncode != 0:
        raise _bad("baseline-unavailable")
    path = state_path_for(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    with state_lock(path):
        if path.exists():
            load_state(path, args.card_id)  # corrupt existing state is exit 4
            raise GuardError(EXIT_CONFLICT, "init-conflict")
        write_state(path, {
            "schema": SCHEMA, "card_id": args.card_id, "repo": args.repo,
            "baseline": {
                "head": head.stdout.strip(),
                "porcelain": porcelain.stdout.splitlines(),
            },
            "attempts": [], "landings": [],
        })
    report("init", "initialized", card_id=args.card_id, board=args.board,
           state_path=str(path), baseline_head=head.stdout.strip())
    return EXIT_OK


def _parse_cmd_json(value: str) -> list:
    try:
        argv = json.loads(value)
    except ValueError:
        raise GuardError(EXIT_USAGE, "cmd-json-invalid")
    if (not isinstance(argv, list) or not argv
            or not all(isinstance(part, str) and part for part in argv)):
        raise GuardError(EXIT_USAGE, "cmd-json-invalid")
    return argv


def _validate_spawn_paths(args: argparse.Namespace) -> None:
    out_dir, result_path = Path(args.out_dir), Path(args.result_path)
    if not out_dir.is_absolute() or not result_path.is_absolute():
        raise GuardError(EXIT_USAGE, "path-not-absolute")
    if args.cwd is not None and not Path(args.cwd).is_dir():
        raise GuardError(EXIT_USAGE, "cwd-not-found")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        result_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise _bad("out-dir-not-creatable")
    # ``--plan-artifact`` is a caller-selected input invariant.  Initial
    # planning has no Plan yet, while execute-plan must supply the accepted
    # Plan.  Validate whenever the caller provides it; stage policy decides
    # when it is required.
    if args.plan_artifact is not None:
        plan = Path(args.plan_artifact)
        if not plan.is_absolute() or not plan.is_file() \
                or plan.stat().st_size == 0:
            raise _bad("plan-artifact-invalid")


def _spawn_attempt(args: argparse.Namespace, path: Path,
                   state: Dict[str, Any], number: int) -> int:
    argv = _parse_cmd_json(args.cmd_json)
    _validate_spawn_paths(args)  # usage errors must not leave a reservation
    attempt = {
        "number": number, "operation": args.operation, "state": "reserved",
        "pid": None, "process_start": None, "out_dir": args.out_dir,
        "result_path": args.result_path, "session_id": None,
        "terminal_status": None,
    }
    state["attempts"].append(attempt)
    write_state(path, state)  # reserve BEFORE any process exists
    try:
        with open(os.path.join(args.out_dir, "guard-stdout.log"), "ab") as out_fh, \
                open(os.path.join(args.out_dir, "guard-stderr.log"), "ab") as err_fh:
            proc = subprocess.Popen(
                argv, cwd=args.cwd, stdin=subprocess.DEVNULL,
                stdout=out_fh, stderr=err_fh, start_new_session=True)
    except OSError as err:
        # Reserved-without-proof stays on disk: every later call classifies
        # uncertain.  Fail closed; never retry the spawn here.
        report("start-or-inspect", "uncertain", attempt_number=number,
               reason=f"spawn-failed: {err}")
        return EXIT_OK
    attempt["pid"] = proc.pid
    attempt["process_start"] = ps_lstart(proc.pid)
    attempt["state"] = "running"
    write_state(path, state)
    report("start-or-inspect", "spawned", attempt_number=number, pid=proc.pid,
           process_start=attempt["process_start"])
    return EXIT_OK


def cmd_start_or_inspect(args: argparse.Namespace) -> int:
    path = state_path_for(args)
    with state_lock(path):
        state = load_state(path, args.card_id, migrate=True)
        attempt = current_attempt(state)
        if attempt is None:
            return _spawn_attempt(args, path, state, 1)
        outcome, info = classify_attempt(attempt)
        if outcome == "terminal" and attempt["state"] == "terminal" and (
                args.new_attempt or attempt["operation"] != args.operation):
            # Only a recorded-terminal attempt may be followed (max+1):
            # either an explicit --new-attempt request or a lifecycle-stage
            # change (planning -> execution -> rework).  Plain same-operation
            # re-entry keeps consuming the recorded terminal result.
            return _spawn_attempt(args, path, state, next_attempt_number(state))
        if outcome == "uncertain" and attempt["state"] != "uncertain":
            attempt["state"] = "uncertain"  # durably block new attempts
            write_state(path, state)
        report("start-or-inspect", outcome, **info)
        return EXIT_OK


def cmd_inspect(args: argparse.Namespace) -> int:
    state = load_state(state_path_for(args), args.card_id)
    attempt = current_attempt(state)
    extra = {"attempts": attempts_summary(state),
             "landings": landings_summary(state)}
    if attempt is None:
        report("inspect", "none", **extra)
        return EXIT_OK
    outcome, info = classify_attempt(attempt)
    report("inspect", outcome, **extra, **info)
    return EXIT_OK


def cmd_record_terminal(args: argparse.Namespace) -> int:
    path = state_path_for(args)
    with state_lock(path):
        state = load_state(path, args.card_id, migrate=True)
        attempt = non_terminal_attempt(state)
        if attempt is None:
            reason = "no-attempt" if not state["attempts"] else "attempt-terminal"
            raise GuardError(EXIT_CONFLICT, reason)
        if attempt["state"] not in ("reserved", "running"):
            raise GuardError(EXIT_CONFLICT, f"attempt-{attempt['state']}")
        if attempt["pid"] is not None and pid_alive(attempt["pid"]):
            # A live recorded pid is never terminal evidence.
            raise GuardError(EXIT_CONFLICT, "process-still-running")
        if os.path.realpath(args.result_path) != \
                os.path.realpath(attempt["result_path"]):
            raise _bad("result-path-mismatch")
        result, reason = load_result(args.result_path)
        if result is None:
            raise _bad(reason)
        session_id = args.session_id or result_session_id(result)
        if result["status"] == "completed" and not session_id:
            raise _bad("session-id-required-for-completed")
        attempt["state"] = "terminal"
        attempt["session_id"] = session_id
        attempt["terminal_status"] = result["status"]
        write_state(path, state)
    report("record-terminal", "terminal", attempt_number=attempt["number"],
           session_id=session_id, status=result["status"])
    return EXIT_OK


def _load_kanban_task(args: argparse.Namespace):
    home = Path(args.home).expanduser()
    runtime = home / "hermes-agent"
    if (runtime / "hermes_cli" / "kanban_db.py").is_file() \
            and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    os.environ["HERMES_KANBAN_HOME"] = str(home)
    os.environ.pop("HERMES_KANBAN_DB", None)   # never inherit path overrides
    os.environ.pop("HERMES_KANBAN_BOARD", None)
    try:
        from hermes_cli import kanban_db, kanban_db_connect
    except ImportError as err:
        raise GuardError(EXIT_CHECK_RUN, f"hermes-runtime-unavailable: {err}")
    if not kanban_db.board_exists(args.board):
        raise GuardError(EXIT_CHECK_RUN, "board-missing")
    conn = kanban_db_connect.connect(board=args.board)
    try:
        return kanban_db.get_task(conn, args.card_id)
    finally:
        conn.close()


def cmd_check_run(args: argparse.Namespace) -> int:
    state = load_state(state_path_for(args), args.card_id)

    def reject(reason: str) -> int:
        report("check-run", "rejected", ok=False, reason=reason,
               card_id=args.card_id)
        return EXIT_CHECK_RUN

    env_task = os.environ.get("HERMES_KANBAN_TASK", "").strip()
    env_run = os.environ.get("HERMES_KANBAN_RUN_ID", "").strip()
    if not env_task:
        return reject("task-env-missing")
    if env_task != state["card_id"]:
        return reject("task-env-mismatch")
    if not env_run:
        return reject("run-env-missing")
    task = _load_kanban_task(args)
    if task is None:
        return reject("card-missing")
    if task.status in TERMINAL_CARD_STATUSES:
        return reject(f"card-{task.status}")
    if task.current_run_id is None:
        return reject("card-not-running")
    if str(task.current_run_id) != env_run:
        return reject("run-id-mismatch")
    env_lock = os.environ.get("HERMES_KANBAN_CLAIM_LOCK", "").strip()
    if not env_lock:
        return reject("claim-lock-env-missing")
    if env_lock != task.claim_lock:
        return reject("claim-lock-mismatch")
    report("check-run", "ok", card_id=args.card_id, run_id=task.current_run_id)
    return EXIT_OK


def _landing_for_commit(state: Dict[str, Any], sha: str) -> Optional[Dict[str, Any]]:
    for landing in state["landings"]:
        if landing["commit"] == sha:
            return landing
    return None


def cmd_record_commit(args: argparse.Namespace) -> int:
    path = state_path_for(args)
    with state_lock(path):
        state = load_state(path, args.card_id, migrate=True)
        full_sha = git_full_sha(state["repo"], args.commit,
                                missing_reason="commit-unknown")
        existing = _landing_for_commit(state, full_sha)
        if existing is not None:
            trailer = f"Kanban-Task: {args.card_id}"
            report("record-commit", "recorded",
                   commit={"sha": existing["commit"], "trailer": trailer},
                   landing=existing, idempotent=True)
            return EXIT_OK
        terminal = latest_terminal_attempt(state)
        if terminal is None:
            raise GuardError(EXIT_CONFLICT, "no-terminal-attempt")
        if terminal.get("terminal_status") != "completed":
            raise GuardError(EXIT_CONFLICT, "last-attempt-not-completed")
        trailer = f"Kanban-Task: {args.card_id}"
        message = git(state["repo"], "show", "-s", "--format=%B", full_sha)
        if message.returncode != 0 or trailer not in message.stdout.splitlines():
            raise _bad("trailer-missing")
        ancestry = git(state["repo"], "merge-base", "--is-ancestor",
                       state["baseline"]["head"], full_sha)
        if ancestry.returncode != 0:
            raise _bad("commit-pre-baseline")
        parent = git_first_parent(state["repo"], full_sha,
                                  missing_reason="commit-parent-unresolvable")
        landing = {
            "attempt_number": terminal["number"],
            "commit": full_sha,
            "parent": parent,
            "recorded_at": utc_now(),
        }
        state["landings"].append(landing)
        write_state(path, state)
    report("record-commit", "recorded",
           commit={"sha": full_sha, "trailer": trailer}, landing=landing)
    return EXIT_OK


# --- CLI --------------------------------------------------------------------

def parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="development_external_guard.py", description=(
            "Fail-closed external-execution guard for development cards."))
    parser.add_argument(
        "--artifacts-root", default=None,
        help="default: $HOME/Secret-Projects/development-artifacts")
    parser.add_argument("--home", default=None,
                        help="Hermes home (default: $HOME/.hermes)")
    parser.add_argument("--board", required=True)
    parser.add_argument("--card", dest="card_id", required=True)
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    p = sub.add_parser("init", help="record card/repo/git baseline once")
    p.add_argument("--repo", required=True)
    p = sub.add_parser("start-or-inspect", help="reserve/start once, or report")
    p.add_argument("--operation", choices=OPERATIONS, required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--result-path", required=True)
    p.add_argument("--cmd-json", required=True, help='["argv", ...] as JSON')
    p.add_argument("--cwd")
    p.add_argument("--plan-artifact")
    p.add_argument("--new-attempt", action="store_true",
                   help="start the next attempt (prior must be recorded "
                        "terminal; without it, same-operation re-entry only "
                        "consumes the recorded terminal result)")
    sub.add_parser("inspect", help="classify without mutation")
    p = sub.add_parser("record-terminal", help="accept a terminal relay result")
    p.add_argument("--result-path", required=True)
    p.add_argument("--session-id")
    sub.add_parser("check-run", help="verify native card/run ownership")
    p = sub.add_parser("record-commit", help="record the Kanban-Task commit")
    p.add_argument("--commit", required=True)

    args = parser.parse_args(argv)
    args.home = str(Path(args.home).expanduser() if args.home else Path.home() / ".hermes")
    args.artifacts_root = str(
        Path(args.artifacts_root).expanduser() if args.artifacts_root
        else Path.home() / "Secret-Projects" / "development-artifacts")
    return args


def main(argv: Optional[list] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else list(argv))
    handler = {
        "init": cmd_init,
        "start-or-inspect": cmd_start_or_inspect,
        "inspect": cmd_inspect,
        "record-terminal": cmd_record_terminal,
        "check-run": cmd_check_run,
        "record-commit": cmd_record_commit,
    }[args.command]
    try:
        return handler(args)
    except GuardError as err:
        report(args.command, "error", ok=False, reason=err.reason)
        return err.code
    except Exception as err:  # noqa: BLE001 - fail closed, keep JSON envelope
        report(args.command, "error", ok=False, reason="internal-error",
               detail=f"{type(err).__name__}: {err}")
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
