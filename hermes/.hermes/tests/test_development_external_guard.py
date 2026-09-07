"""Tests for the development external-execution guard (MVP).

Runs against the real Hermes Kanban DB API (``hermes_cli.kanban_db`` for
fixtures, ``hermes_cli.kanban_db_connect.connect`` for connections) with an
isolated temporary ``HERMES_HOME`` plus artifacts root and a disposable git
repository per test -- the live board under ``/Users/kenan/.hermes`` is never
touched.  The guard itself is exercised end-to-end as a subprocess CLI,
exactly like its callers use it.

Run with the installed Hermes interpreter:

    /Users/kenan/.hermes/hermes-agent/venv/bin/python \\
        hermes/.hermes/tests/test_development_external_guard.py -v
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import closing
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPT = TESTS_DIR.parent / "scripts" / "development_external_guard.py"

# ---------------------------------------------------------------------------
# Bootstrap the installed Hermes runtime (mirrors the digest test harness).
# ---------------------------------------------------------------------------

def _runtime_root() -> Path | None:
    for candidate in (
        Path.home() / ".hermes" / "hermes-agent",
        Path("/Users/kenan/.hermes/hermes-agent"),
    ):
        if (candidate / "hermes_cli" / "kanban_db.py").exists():
            return candidate
    return None


RUNTIME_ROOT = _runtime_root()
try:
    import hermes_cli.kanban_db_connect  # noqa: F401
except ImportError:
    if RUNTIME_ROOT is not None:
        sys.path.insert(0, str(RUNTIME_ROOT))
    import hermes_cli.kanban_db_connect  # noqa: F401

from hermes_cli import kanban_db as kb  # noqa: E402
from hermes_cli import kanban_db_connect  # noqa: E402

_SCRUB_ENV_VARS = (
    "HERMES_KANBAN_DB",
    "HERMES_KANBAN_BOARD",
    "HERMES_KANBAN_HOME",
    "HERMES_KANBAN_WORKSPACES_ROOT",
    "HERMES_KANBAN_WORKSPACE",
    "HERMES_KANBAN_TASK",
    "HERMES_KANBAN_RUN_ID",
    "HERMES_DELEGATED_CHILD_CONTEXT",
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class GuardCase(unittest.TestCase):
    """Fresh temp home + artifacts root + disposable git repo per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / ".hermes"
        self.home.mkdir()
        if RUNTIME_ROOT is not None:
            # The guard bootstraps hermes_cli from <home>/hermes-agent.
            (self.home / "hermes-agent").symlink_to(RUNTIME_ROOT)
        self.artifacts = self.root / "development-artifacts"
        self.board = "dotfile"
        self._env_backup = os.environ.copy()
        self.addCleanup(self._restore_env)
        os.environ["HERMES_HOME"] = str(self.home)
        os.environ["HERMES_KANBAN_HOME"] = str(self.home)
        for var in _SCRUB_ENV_VARS:
            os.environ.pop(var, None)
        self._pids: list[int] = []
        self._procs: list[subprocess.Popen] = []
        self.addCleanup(self._reap)
        self.repo = self.make_repo()

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _reap(self) -> None:
        for pid in self._pids:
            self.kill_tree(pid)
        for proc in self._procs:
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)

    # -- git / board fixtures ------------------------------------------------

    def git(self, *args: str, cwd: Path = None, check: bool = True) -> str:
        repo = cwd if cwd is not None else self.repo
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, check=False)
        if check and proc.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout

    def make_repo(self) -> Path:
        repo = self.root / "repo"
        repo.mkdir()
        self.git("init", "-q", cwd=repo)
        self.git("config", "user.email", "dev@example.com", cwd=repo)
        self.git("config", "user.name", "Dev Test", cwd=repo)
        (repo / "file1.txt").write_text("one\n")
        (repo / "file2.txt").write_text("two\n")
        self.git("add", ".", cwd=repo)
        self.git("commit", "-q", "-m", "initial", cwd=repo)
        # Dirty baseline: one modification plus one untracked file.
        (repo / "file1.txt").write_text("one changed\n")
        (repo / "file3-untracked.txt").write_text("three\n")
        return repo

    def commit(self, message: str) -> str:
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def make_card(self, *, worker: str = "worker-a") -> tuple[str, int]:
        with closing(kanban_db_connect.connect(board=self.board)) as conn:
            tid = kb.create_task(conn, title="Dev task", board=self.board,
                                 workspace_kind="scratch")
            task = kb.claim_task(conn, tid, ttl_seconds=3600, claimer=worker)
        self.assertIsNotNone(task, "fixture card must claim ready -> running")
        return tid, task.current_run_id

    def reclaim_card(self, card: str, *, worker: str) -> int:
        with closing(kanban_db_connect.connect(board=self.board)) as conn:
            with kb.write_txn(conn):
                conn.execute(
                    "UPDATE tasks SET status = 'ready', claim_lock = NULL, "
                    "claim_expires = NULL, worker_pid = NULL, "
                    "current_run_id = NULL WHERE id = ?", (card,),
                )
            task = kb.claim_task(conn, card, ttl_seconds=3600, claimer=worker)
        return task.current_run_id

    def complete_card(self, card: str) -> None:
        with closing(kanban_db_connect.connect(board=self.board)) as conn:
            self.assertTrue(kb.complete_task(conn, card, summary="done"))

    # -- guard CLI -----------------------------------------------------------

    def state_path(self, card: str) -> Path:
        return (self.artifacts / self.board / "tasks" / card
                / "external-execution.json")

    def guard(self, card: str, *argv, expect: int = 0,
              env_extra: dict = None):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--artifacts-root", str(self.artifacts), "--home", str(self.home),
             "--board", self.board, "--card", card,
             *[str(a) for a in argv]],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, **(env_extra or {})},
        )
        if expect is not None:
            self.assertEqual(
                expect, proc.returncode,
                f"rc={proc.returncode}\nstdout={proc.stdout}\n"
                f"stderr={proc.stderr}",
            )
        if not proc.stdout.strip():
            return None
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.fail(f"non-JSON stdout: {proc.stdout!r}")

    def init(self, card: str, repo: Path = None, expect: int = 0):
        return self.guard(card, "init", "--repo",
                          str(repo if repo is not None else self.repo),
                          expect=expect)

    def read_state(self, card: str) -> dict:
        return json.loads(self.state_path(card).read_text(encoding="utf-8"))

    def write_state(self, card: str, state: dict) -> None:
        self.state_path(card).write_text(
            json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def start_or_inspect(self, card: str, *, operation: str = "execution",
                         out_dir: Path = None, result_path: Path = None,
                         cmd: list = None, plan: Path = None,
                         cwd: Path = None, new_attempt: bool = False,
                         expect: int = 0):
        out_dir = out_dir if out_dir is not None else self.root / "relay-out"
        result_path = result_path if result_path is not None \
            else out_dir / "result.json"
        if cmd is None:
            cmd = self.long_sleep_cmd()
        argv = ["start-or-inspect", "--operation", operation,
                "--out-dir", str(out_dir), "--result-path", str(result_path),
                "--cmd-json", json.dumps(cmd)]
        if plan is not None:
            argv += ["--plan-artifact", str(plan)]
        if cwd is not None:
            argv += ["--cwd", str(cwd)]
        if new_attempt:
            argv += ["--new-attempt"]
        out = self.guard(card, *argv, expect=expect)
        pid = (out or {}).get("pid")
        if pid:
            self._pids.append(pid)
        return out

    # -- relay / process helpers ------------------------------------------------

    def marker(self) -> str:
        return f"guard-marker-{uuid.uuid4().hex[:10]}"

    def long_sleep_cmd(self, seconds: int = 30, marker: str = None) -> list:
        marker = marker or self.marker()
        # Two statements so /bin/sh keeps its -c command line (and thus the
        # marker) instead of exec-optimizing into a bare `sleep`.
        return ["/bin/sh", "-c", f"sleep {seconds}; true # {marker}"]

    def relay_cmd(self, result_path: Path, *, sleep: float = 0.5,
                  session: str = None, status: str = "completed",
                  body: str = None) -> list:
        """A bounded /bin/sh relay writing a delegate-relay.result.v1 file."""
        if body is None:
            result = {"schema": "delegate-relay.result.v1", "status": status,
                      "exitCode": 0, "artifacts": []}
            if session is not None:
                result["sessionId"] = session
            body = json.dumps(result)
        script = (f"sleep {sleep}; printf '%s' {shlex.quote(body)} > "
                  f"{shlex.quote(str(result_path))}")
        return ["/bin/sh", "-c", script]

    def result_body(self, *, session: str = None, status: str = "completed",
                    thread: str = None) -> str:
        result = {"schema": "delegate-relay.result.v1", "status": status,
                  "exitCode": 0, "artifacts": []}
        if session is not None:
            result["sessionId"] = session
        if thread is not None:
            result["threadId"] = thread
        return json.dumps(result)

    def spawn_helper(self, argv: list) -> subprocess.Popen:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
        self._pids.append(proc.pid)
        self._procs.append(proc)
        return proc

    def kill_tree(self, pid: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(pid, signal.SIGKILL)

    def pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def pgrep_count(self, marker: str) -> int:
        proc = subprocess.run(["pgrep", "-f", marker],
                              capture_output=True, text=True, check=False)
        return len([line for line in proc.stdout.splitlines() if line.strip()])

    def wait_until(self, predicate, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def wait_relay_finished(self, pid: int, result_path: Path) -> bool:
        return self.wait_until(
            lambda: not self.pid_alive(pid) and result_path.exists()
        ) or (not self.pid_alive(pid) and result_path.exists())


# ---------------------------------------------------------------------------
# 1. init
# ---------------------------------------------------------------------------

class TestInit(GuardCase):
    def test_init_records_card_repo_head_porcelain_once(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        out = self.init(card)
        self.assertTrue(out["ok"])
        state = self.read_state(card)
        self.assertEqual("development-external-execution.v1", state["schema"])
        self.assertEqual(card, state["card_id"])
        self.assertEqual(str(self.repo), state["repo"])
        self.assertEqual(self.git("rev-parse", "HEAD").strip(),
                         state["baseline_head"])
        self.assertEqual(self.git("status", "--porcelain").splitlines(),
                         state["baseline_porcelain"])
        self.assertIsNone(state["attempt"])
        self.assertIsNone(state["commit"])
        self.assertTrue(state["updated_at"])

        # A second init on existing state is an init conflict (exit 3).
        self.init(card, expect=3)
        self.assertEqual(state, self.read_state(card))

    def test_init_requires_absolute_existing_git_repo(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card, repo=Path("relative/repo"), expect=2)
        self.init(card, repo=self.root / "missing", expect=4)
        self.assertFalse(self.state_path(card).exists())


# ---------------------------------------------------------------------------
# 2 + 3. spawn once, attach to the live relay
# ---------------------------------------------------------------------------

class TestSpawnAndAttach(GuardCase):
    def test_concurrent_start_or_inspect_spawns_exactly_once(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        out_dir = self.root / "relay-out"
        marker = self.marker()
        base = [sys.executable, str(SCRIPT),
                "--artifacts-root", str(self.artifacts),
                "--home", str(self.home), "--board", self.board,
                "--card", card, "start-or-inspect", "--operation", "execution",
                "--out-dir", str(out_dir),
                "--result-path", str(out_dir / "result.json"),
                "--cmd-json", json.dumps(self.long_sleep_cmd(marker=marker))]
        procs = [subprocess.Popen(base, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
                 for _ in range(2)]
        results = []
        for proc in procs:
            stdout, stderr = proc.communicate(timeout=120)
            results.append((proc.returncode, stdout, stderr))
        for rc, stdout, stderr in results:
            self.assertEqual(0, rc, f"stdout={stdout}\nstderr={stderr}")
        outcomes = sorted(json.loads(stdout)["outcome"]
                          for _rc, stdout, _stderr in results)
        self.assertEqual(["attach", "spawned"], outcomes)
        attempt = self.read_state(card)["attempt"]
        self.assertEqual("running", attempt["state"])
        self.assertEqual(1, attempt["number"])
        self.assertIsNotNone(attempt["pid"])
        self._pids.append(attempt["pid"])
        self.assertEqual(1, self.pgrep_count(marker))

    def test_matching_live_process_returns_attach(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        spawn = self.start_or_inspect(card, operation="execution")
        self.assertEqual("spawned", spawn["outcome"])
        pid = spawn["pid"]
        self.assertTrue(self.pid_alive(pid))
        attempt = self.read_state(card)["attempt"]
        self.assertEqual("running", attempt["state"])
        self.assertEqual(pid, attempt["pid"])
        # Recorded identity is the exact current ps lstart output.
        current = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                                 capture_output=True, text=True,
                                 check=True).stdout.strip()
        self.assertEqual(current, attempt["process_start"])

        attach = self.start_or_inspect(card, operation="execution")
        self.assertEqual("attach", attach["outcome"])
        self.assertEqual(pid, attach["pid"])

        # Attach wins regardless of the requested operation.
        rework = self.start_or_inspect(card, operation="rework")
        self.assertEqual("attach", rework["outcome"])
        self.assertEqual(pid, rework["pid"])


# ---------------------------------------------------------------------------
# 4. terminal result + exact session id
# ---------------------------------------------------------------------------

class TestRecordTerminal(GuardCase):
    def test_dead_relay_with_valid_result_reports_then_records_terminal(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        result_path = self.root / "relay-out" / "result.json"
        spawn = self.start_or_inspect(
            card, operation="execution", result_path=result_path,
            cmd=self.relay_cmd(result_path, session="sess-42"))
        pid = spawn["pid"]
        self.assertTrue(self.wait_relay_finished(pid, result_path))

        # Classification reports terminal but does NOT mutate the attempt.
        seen = self.start_or_inspect(card, operation="execution",
                                     result_path=result_path,
                                     cmd=self.long_sleep_cmd())
        self.assertEqual("terminal", seen["outcome"])
        self.assertEqual("sess-42", seen["session_id"])
        self.assertEqual("completed", seen["status"])
        self.assertEqual("running", self.read_state(card)["attempt"]["state"])

        recorded = self.guard(card, "record-terminal", "--result-path",
                              str(result_path))
        self.assertTrue(recorded["ok"])
        self.assertEqual("sess-42", recorded["session_id"])
        attempt = self.read_state(card)["attempt"]
        self.assertEqual("terminal", attempt["state"])
        self.assertEqual("sess-42", attempt["session_id"])

        # Re-entering with the same operation consumes the result; no rerun.
        marker = self.marker()
        again = self.start_or_inspect(card, operation="execution",
                                      result_path=result_path,
                                      cmd=self.long_sleep_cmd(marker=marker))
        self.assertEqual("terminal", again["outcome"])
        self.assertEqual("sess-42", again["session_id"])
        self.assertEqual(1, self.read_state(card)["attempt"]["number"])
        self.assertEqual(0, self.pgrep_count(marker))

    def test_record_terminal_rejects_live_relay_and_invalid_evidence(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        result_path = self.root / "relay-out" / "result.json"
        live = self.start_or_inspect(card, operation="execution",
                                     result_path=result_path)

        # A valid result while the recorded relay is still live is refused.
        result_path.write_text(self.result_body(session="sess-42"),
                               encoding="utf-8")
        self.guard(card, "record-terminal", "--result-path", str(result_path),
                   expect=3)
        self.assertEqual("running", self.read_state(card)["attempt"]["state"])

        self.kill_tree(live["pid"])
        self.wait_until(lambda: not self.pid_alive(live["pid"]))

        # A result at a different path than the attempt recorded is invalid.
        other = self.root / "other-result.json"
        other.write_text(self.result_body(session="sess-x"), encoding="utf-8")
        self.guard(card, "record-terminal", "--result-path", str(other),
                   expect=4)
        # Completed without any session id is invalid evidence.
        result_path.write_text(self.result_body(), encoding="utf-8")
        self.guard(card, "record-terminal", "--result-path", str(result_path),
                   expect=4)
        # Malformed / wrong-schema / unknown-status bodies are invalid.
        for body in ("{not: json",
                     '{"schema": "other.v1", "status": "completed"}',
                     '{"schema": "delegate-relay.result.v1", '
                     '"status": "weird"}'):
            result_path.write_text(body, encoding="utf-8")
            self.guard(card, "record-terminal", "--result-path",
                       str(result_path), expect=4)
        self.assertEqual("running", self.read_state(card)["attempt"]["state"])

    def test_session_id_resolution_precedence(self):
        # --session-id wins over every result-borne id.
        card_a = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card_a)
        result_a = self.root / "out-a" / "result.json"
        relay_a = self.start_or_inspect(card_a, result_path=result_a)
        self.kill_tree(relay_a["pid"])
        self.wait_until(lambda: not self.pid_alive(relay_a["pid"]))
        result_a.write_text(self.result_body(session="sess-result",
                                             thread="thread-result"),
                            encoding="utf-8")
        out = self.guard(card_a, "record-terminal", "--result-path",
                         str(result_a), "--session-id", "sess-override")
        self.assertEqual("sess-override", out["session_id"])

        # Without --session-id, result sessionId beats threadId.
        card_b = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card_b)
        result_b = self.root / "out-b" / "result.json"
        relay_b = self.start_or_inspect(card_b, result_path=result_b)
        self.kill_tree(relay_b["pid"])
        self.wait_until(lambda: not self.pid_alive(relay_b["pid"]))
        result_b.write_text(self.result_body(session="sess-b",
                                             thread="thread-b"),
                            encoding="utf-8")
        out = self.guard(card_b, "record-terminal", "--result-path",
                         str(result_b))
        self.assertEqual("sess-b", out["session_id"])

        # threadId alone still resolves; non-completed may end without an id.
        card_c = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card_c)
        result_c = self.root / "out-c" / "result.json"
        relay_c = self.start_or_inspect(card_c, result_path=result_c)
        self.kill_tree(relay_c["pid"])
        self.wait_until(lambda: not self.pid_alive(relay_c["pid"]))
        result_c.write_text(self.result_body(thread="thread-c"),
                            encoding="utf-8")
        out = self.guard(card_c, "record-terminal", "--result-path",
                         str(result_c))
        self.assertEqual("thread-c", out["session_id"])
        card_d = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card_d)
        result_d = self.root / "out-d" / "result.json"
        relay_d = self.start_or_inspect(card_d, result_path=result_d)
        self.kill_tree(relay_d["pid"])
        self.wait_until(lambda: not self.pid_alive(relay_d["pid"]))
        result_d.write_text(self.result_body(status="failed"),
                            encoding="utf-8")
        out = self.guard(card_d, "record-terminal", "--result-path",
                         str(result_d))
        self.assertIsNone(out["session_id"])
        self.assertEqual("terminal",
                         self.read_state(card_d)["attempt"]["state"])


# ---------------------------------------------------------------------------
# 5. uncertain never spawns
# ---------------------------------------------------------------------------

class TestUncertain(GuardCase):
    def _fabricated(self, card: str, **attempt_fields) -> None:
        state = self.read_state(card)
        attempt = {
            "number": 1, "operation": "execution", "state": "running",
            "pid": None, "process_start": None,
            "out_dir": str(self.root / "relay-out"),
            "result_path": str(self.root / "relay-out" / "result.json"),
            "session_id": None,
        }
        attempt.update(attempt_fields)
        state["attempt"] = attempt
        self.write_state(card, state)

    def test_reserved_without_pid_is_uncertain_and_blocks(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        self._fabricated(card, state="reserved", pid=None)
        marker = self.marker()
        out = self.start_or_inspect(card, cmd=self.long_sleep_cmd(marker=marker))
        self.assertEqual("uncertain", out["outcome"])
        self.assertEqual(0, self.pgrep_count(marker))
        # The block is durable: new attempts (any operation) stay uncertain.
        self.assertEqual("uncertain",
                         self.read_state(card)["attempt"]["state"])
        again = self.start_or_inspect(card, operation="rework")
        self.assertEqual("uncertain", again["outcome"])
        self.assertEqual(0, self.pgrep_count(marker))

    def test_pid_identity_mismatch_is_uncertain(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        helper = self.spawn_helper(self.long_sleep_cmd())
        self._fabricated(card, pid=helper.pid,
                         process_start="FORGED-identity")
        marker = self.marker()
        out = self.start_or_inspect(card, cmd=self.long_sleep_cmd(marker=marker))
        self.assertEqual("uncertain", out["outcome"])
        self.assertEqual("pid-identity-mismatch", out["reason"])
        self.assertEqual(0, self.pgrep_count(marker))

    def test_dead_pid_without_result_is_uncertain(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        helper = self.spawn_helper(["/bin/sh", "-c", "true"])
        self.wait_until(lambda: not self.pid_alive(helper.pid))
        self._fabricated(card, pid=helper.pid, process_start="whatever")
        marker = self.marker()
        out = self.start_or_inspect(card, cmd=self.long_sleep_cmd(marker=marker))
        self.assertEqual("uncertain", out["outcome"])
        self.assertEqual(0, self.pgrep_count(marker))

    def test_malformed_result_after_death_is_uncertain(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        result_path = self.root / "relay-out" / "result.json"
        spawn = self.start_or_inspect(
            card, result_path=result_path,
            cmd=self.relay_cmd(result_path, body="{not: json"))
        self.assertTrue(self.wait_relay_finished(spawn["pid"], result_path))
        marker = self.marker()
        out = self.start_or_inspect(card, result_path=result_path,
                                    cmd=self.long_sleep_cmd(marker=marker))
        self.assertEqual("uncertain", out["outcome"])
        self.assertEqual("result-malformed", out["reason"])
        self.assertEqual(0, self.pgrep_count(marker))
        self.assertEqual("uncertain",
                         self.read_state(card)["attempt"]["state"])

    def test_inspect_classifies_without_mutation(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        self.assertEqual("none", self.guard(card, "inspect")["outcome"])
        self._fabricated(card, state="reserved", pid=None)
        before = self.read_state(card)
        out = self.guard(card, "inspect")
        self.assertEqual("uncertain", out["outcome"])
        self.assertEqual(before, self.read_state(card))


# ---------------------------------------------------------------------------
# 6. new attempts only after recorded terminal
# ---------------------------------------------------------------------------

class TestAttemptReplacement(GuardCase):
    def test_rejected_while_live_then_attempt_two_after_terminal(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        first = self.start_or_inspect(card, operation="execution")
        self.assertEqual("spawned", first["outcome"])

        # A different operation while the relay is live is attach, not spawn.
        rejected_marker = self.marker()
        rejected = self.start_or_inspect(card, operation="rework",
                                         cmd=self.long_sleep_cmd(
                                             marker=rejected_marker))
        self.assertEqual("attach", rejected["outcome"])
        self.assertEqual(0, self.pgrep_count(rejected_marker))
        self.assertEqual(1, self.read_state(card)["attempt"]["number"])

        # Relay ends with a valid result; record-terminal closes attempt 1.
        result_path = self.root / "relay-out" / "result.json"
        self.kill_tree(first["pid"])
        self.wait_until(lambda: not self.pid_alive(first["pid"]))
        result_path.write_text(self.result_body(session="sess-1"),
                               encoding="utf-8")
        self.guard(card, "record-terminal", "--result-path", str(result_path))

        # A different operation now spawns attempt number 2.
        second_out = self.root / "relay-out-2"
        second_result = second_out / "result.json"
        second_marker = self.marker()
        second = self.start_or_inspect(
            card, operation="rework", out_dir=second_out,
            result_path=second_result,
            cmd=self.long_sleep_cmd(marker=second_marker))
        self.assertEqual("spawned", second["outcome"])
        attempt = self.read_state(card)["attempt"]
        self.assertEqual(2, attempt["number"])
        self.assertEqual("rework", attempt["operation"])
        self.assertEqual(str(second_result), attempt["result_path"])
        self.assertEqual(1, self.pgrep_count(second_marker))

    def test_consecutive_rework_needs_new_attempt_flag(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)

        # Attempt 1: execution -> recorded terminal.
        out_one = self.root / "relay-one"
        first = self.start_or_inspect(card, operation="execution",
                                     out_dir=out_one,
                                     result_path=out_one / "result.json")
        result_one = out_one / "result.json"
        self.kill_tree(first["pid"])
        self.wait_until(lambda: not self.pid_alive(first["pid"]))
        result_one.write_text(self.result_body(session="sess-1"),
                              encoding="utf-8")
        self.guard(card, "record-terminal", "--result-path", str(result_one))

        # Attempt 2: rework (lifecycle change) -> recorded terminal.
        out_two = self.root / "relay-two"
        second = self.start_or_inspect(card, operation="rework",
                                       out_dir=out_two,
                                       result_path=out_two / "result.json")
        self.assertEqual("spawned", second["outcome"])
        result_two = out_two / "result.json"
        self.kill_tree(second["pid"])
        self.wait_until(lambda: not self.pid_alive(second["pid"]))
        result_two.write_text(self.result_body(session="sess-2"),
                              encoding="utf-8")
        self.guard(card, "record-terminal", "--result-path", str(result_two))

        # Plain same-operation re-entry consumes the terminal result
        # (RP-01 regression): no third relay without the explicit flag.
        consumed = self.start_or_inspect(card, operation="rework")
        self.assertEqual("terminal", consumed["outcome"])
        self.assertEqual("sess-2", consumed.get("session_id"))
        self.assertEqual(2, self.read_state(card)["attempt"]["number"])

        # --new-attempt explicitly reserves and spawns attempt 3.
        third_marker = self.marker()
        third = self.start_or_inspect(card, operation="rework",
                                      out_dir=self.root / "relay-three",
                                      result_path=self.root / "relay-three"
                                      / "result.json",
                                      cmd=self.long_sleep_cmd(
                                          marker=third_marker),
                                      new_attempt=True)
        self.assertEqual("spawned", third["outcome"])
        attempt = self.read_state(card)["attempt"]
        self.assertEqual(3, attempt["number"])
        self.assertEqual("rework", attempt["operation"])
        self.assertEqual(1, self.pgrep_count(third_marker))

        # --new-attempt never bypasses the recorded-terminal requirement.
        self.kill_tree(third["pid"])
        self.wait_until(lambda: not self.pid_alive(third["pid"]))
        denied = self.start_or_inspect(card, operation="rework",
                                       new_attempt=True)
        self.assertEqual("uncertain", denied["outcome"])
        self.assertEqual(3, self.read_state(card)["attempt"]["number"])

    def test_planning_operation_requires_plan_artifact(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        self.init(card)
        self.start_or_inspect(card, operation="planning", expect=4)
        plan = self.root / "plan.md"
        plan.write_text("", encoding="utf-8")
        self.start_or_inspect(card, operation="planning", plan=plan, expect=4)
        plan.write_text("# Plan\n", encoding="utf-8")
        out = self.start_or_inspect(card, operation="planning", plan=plan)
        self.assertEqual("spawned", out["outcome"])


# ---------------------------------------------------------------------------
# 7. check-run against a real temp board
# ---------------------------------------------------------------------------

class TestCheckRun(GuardCase):
    def test_check_run_rejects_stale_reclaimed_and_mismatched_workers(self):
        card, run = self.make_card()
        self.init(card)
        env_ok = {"HERMES_KANBAN_TASK": card,
                  "HERMES_KANBAN_RUN_ID": str(run)}
        out = self.guard(card, "check-run", env_extra=env_ok)
        self.assertTrue(out["ok"])
        self.assertEqual(run, out["run_id"])

        # Mismatched env task and env run are both rejected with exit 5.
        self.guard(card, "check-run", expect=5,
                   env_extra={"HERMES_KANBAN_TASK": "t_someone_else",
                              "HERMES_KANBAN_RUN_ID": str(run)})
        self.guard(card, "check-run", expect=5,
                   env_extra={"HERMES_KANBAN_TASK": card,
                              "HERMES_KANBAN_RUN_ID": str(run + 9)})

        # A reclaimed card runs under a new run: the stale worker is refused.
        new_run = self.reclaim_card(card, worker="worker-b")
        self.assertNotEqual(run, new_run)
        self.guard(card, "check-run", expect=5, env_extra=env_ok)
        fresh = self.guard(card, "check-run", env_extra={
            "HERMES_KANBAN_TASK": card,
            "HERMES_KANBAN_RUN_ID": str(new_run)})
        self.assertTrue(fresh["ok"])

        # A done card is never owned again.
        self.complete_card(card)
        self.guard(card, "check-run", expect=5, env_extra={
            "HERMES_KANBAN_TASK": card,
            "HERMES_KANBAN_RUN_ID": str(new_run)})


# ---------------------------------------------------------------------------
# 8. record-commit trailer rules
# ---------------------------------------------------------------------------

class TestRecordCommit(GuardCase):
    def test_record_commit_accepts_only_real_trailer_commit(self):
        card = f"t_{uuid.uuid4().hex[:12]}"
        trailer = f"Kanban-Task: {card}"
        # A pre-baseline trailer commit exists, then the baseline moves past it.
        pre = self.commit(f"pre-baseline\n\n{trailer}")
        baseline = self.commit("baseline")
        self.init(card)
        self.assertEqual(baseline, self.read_state(card)["baseline_head"])

        # Unknown SHA, pre-baseline commit, missing and wrong trailers fail.
        self.guard(card, "record-commit", "--commit", "0" * 40, expect=4)
        self.guard(card, "record-commit", "--commit", pre, expect=4)
        no_trailer = self.commit("no trailer here")
        self.guard(card, "record-commit", "--commit", no_trailer, expect=4)
        wrong = self.commit(f"work\n\nKanban-Task: t_someone_else")
        self.guard(card, "record-commit", "--commit", wrong, expect=4)
        self.assertIsNone(self.read_state(card)["commit"])

        # The exact trailer commit is recorded; re-recording is idempotent.
        good = self.commit(f"land it\n\n{trailer}")
        out = self.guard(card, "record-commit", "--commit", good)
        self.assertTrue(out["ok"])
        self.assertEqual({"sha": good, "trailer": trailer},
                         self.read_state(card)["commit"])
        again = self.guard(card, "record-commit", "--commit", good)
        self.assertTrue(again["ok"])

        # A different SHA after one commit is recorded is a conflict.
        other = self.commit(f"more work\n\n{trailer}")
        self.guard(card, "record-commit", "--commit", other, expect=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
