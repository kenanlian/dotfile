#!/usr/bin/env python3
"""External-execution guard for the Hermes development workflow MVP.

Fail-closed CLI that prevents duplicate Coding Agent Relay starts and records
exact-session recovery facts.  Hermes Kanban stays the only workflow control
plane; this guard owns ONLY relay identity/session/result evidence plus the
git baseline/commit facts (plan sections 2.2-2.4).  Canonical state:

    <artifacts-root>/<board>/tasks/<card-id>/external-execution.json

Commands: init | start-or-inspect | inspect | record-terminal | check-run |
record-commit.  Outcomes: spawned | attach | terminal | uncertain (``inspect``
also reports ``none`` before the first attempt).  Ambiguity never causes a
second spawn; it classifies ``uncertain`` and durably blocks new attempts.

Exit codes: 0 classified outcome (uncertain included); 2 usage; 3 init
conflict or state-transition violation; 4 corrupt/missing state or invalid
evidence; 5 check-run failure; 6 unexpected internal error.  Every command prints one JSON object to
stdout.  Stdlib only; ``check-run`` lazily imports the installed ``hermes_cli``
runtime, bootstrapping ``sys.path`` from ``<home>/hermes-agent``.
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
from typing import Any, Dict, Optional, Tuple

SCHEMA = "development-external-execution.v1"
RESULT_SCHEMA = "delegate-relay.result.v1"
RESULT_STATUSES = ("completed", "failed", "timeout", "aborted", "unavailable")
OPERATIONS = ("planning", "execution", "rework")
ATTEMPT_STATES = ("reserved", "running", "terminal", "uncertain")
ATTEMPT_KEYS = ("number", "operation", "state", "pid", "process_start",
                "out_dir", "result_path", "session_id")
TERMINAL_CARD_STATUSES = ("done", "archived")
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


# --- State I/O: one advisory lock; atomic temp-file + os.replace writes ---

def state_path_for(args: argparse.Namespace) -> Path:
    return Path(args.artifacts_root) / args.board / "tasks" / args.card_id \
        / "external-execution.json"


@contextlib.contextmanager
def state_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _validate_attempt(attempt: Any) -> None:
    if attempt is None:
        return
    number, pid = attempt.get("number"), attempt.get("pid")
    ok = (
        isinstance(attempt, dict)
        and all(k in attempt for k in ATTEMPT_KEYS)
        and attempt["state"] in ATTEMPT_STATES
        and attempt["operation"] in OPERATIONS
        and isinstance(number, int) and not isinstance(number, bool) and number >= 1
        and (pid is None or (isinstance(pid, int) and not isinstance(pid, bool)))
        and all(attempt[k] is None or isinstance(attempt[k], str)
                for k in ("process_start", "session_id"))
        and all(isinstance(attempt[k], str) and attempt[k]
                for k in ("out_dir", "result_path"))
    )
    if not ok:
        raise _bad("state-attempt-corrupt")


def load_state(path: Path, card_id: str) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raise _bad("state-missing")
    try:
        state = json.loads(raw)
    except ValueError:
        raise _bad("state-corrupt-json")
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise _bad("state-schema-invalid")
    if state.get("card_id") != card_id:
        raise _bad("state-card-mismatch")
    _validate_attempt(state.get("attempt"))
    return state


def write_state(path: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    data = json.dumps(state, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=".external-execution.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


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
            "baseline_head": head.stdout.strip(),
            "baseline_porcelain": porcelain.stdout.splitlines(),
            "attempt": None, "commit": None,
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
    state["attempt"] = {
        "number": number, "operation": args.operation, "state": "reserved",
        "pid": None, "process_start": None, "out_dir": args.out_dir,
        "result_path": args.result_path, "session_id": None,
    }
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
    attempt = state["attempt"]
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
        state = load_state(path, args.card_id)
        attempt = state["attempt"]
        if attempt is None:
            return _spawn_attempt(args, path, state, 1)
        outcome, info = classify_attempt(attempt)
        if outcome == "terminal" and attempt["state"] == "terminal" and (
                args.new_attempt or attempt["operation"] != args.operation):
            # Only a recorded-terminal attempt may be replaced (number+1):
            # either an explicit --new-attempt request or a lifecycle-stage
            # change (planning -> execution -> rework).  Plain same-operation
            # re-entry keeps consuming the recorded terminal result.
            return _spawn_attempt(args, path, state, attempt["number"] + 1)
        if outcome == "uncertain" and attempt["state"] != "uncertain":
            attempt["state"] = "uncertain"  # durably block new attempts
            write_state(path, state)
        report("start-or-inspect", outcome, **info)
        return EXIT_OK


def cmd_inspect(args: argparse.Namespace) -> int:
    state = load_state(state_path_for(args), args.card_id)
    if state["attempt"] is None:
        report("inspect", "none")
        return EXIT_OK
    outcome, info = classify_attempt(state["attempt"])
    report("inspect", outcome, **info)
    return EXIT_OK


def cmd_record_terminal(args: argparse.Namespace) -> int:
    path = state_path_for(args)
    with state_lock(path):
        state = load_state(path, args.card_id)
        attempt = state["attempt"]
        if attempt is None:
            raise GuardError(EXIT_CONFLICT, "no-attempt")
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
    report("check-run", "ok", card_id=args.card_id, run_id=task.current_run_id)
    return EXIT_OK


def cmd_record_commit(args: argparse.Namespace) -> int:
    path = state_path_for(args)
    with state_lock(path):
        state = load_state(path, args.card_id)
        resolved = git(state["repo"], "rev-parse", args.commit + "^{commit}")
        if resolved.returncode != 0 or not resolved.stdout.strip():
            raise _bad("commit-unknown")
        full_sha = resolved.stdout.strip()
        trailer = f"Kanban-Task: {args.card_id}"
        recorded = state.get("commit")
        if isinstance(recorded, dict):
            if recorded.get("sha") == full_sha:
                report("record-commit", "recorded", commit=recorded,
                       idempotent=True)
                return EXIT_OK
            raise GuardError(EXIT_CONFLICT, "commit-already-recorded")
        message = git(state["repo"], "show", "-s", "--format=%B", full_sha)
        if message.returncode != 0 or trailer not in message.stdout.splitlines():
            raise _bad("trailer-missing")
        ancestry = git(state["repo"], "merge-base", "--is-ancestor",
                       state["baseline_head"], full_sha)
        if ancestry.returncode != 0:
            raise _bad("commit-pre-baseline")
        state["commit"] = {"sha": full_sha, "trailer": trailer}
        write_state(path, state)
    report("record-commit", "recorded", commit=state["commit"])
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
