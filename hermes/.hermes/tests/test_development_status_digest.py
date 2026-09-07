"""Tests for the minimal global read-only development status digest.

Runs against the real Hermes Kanban DB API (``hermes_cli``) with an isolated
temporary HERMES_HOME per test — the live board under ``/Users/kenan/.hermes``
is never touched.  The script under test is invoked as a subprocess with an
explicit ``--home`` (and a fixed ``--now`` for determinism), exactly like the
cron launcher runs it.

Run with the installed Hermes interpreter (NO pytest):

    cd hermes/.hermes && /Users/kenan/.hermes/hermes-agent/venv/bin/python -m unittest \\
        tests.test_development_status_digest -v
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPT = TESTS_DIR.parent / "scripts" / "development_status_digest.py"
LAUNCHER = TESTS_DIR.parent / "cron-launchers" / "development_status_digest_cron.py"

# ---------------------------------------------------------------------------
# Bootstrap: make the installed Hermes runtime importable when it is not
# already on sys.path (mirrors the development-workflow plugin tests).
# ---------------------------------------------------------------------------

try:
    import hermes_cli.kanban_db_connect  # noqa: F401
except ImportError:
    _runtime_candidates = [
        Path.home() / ".hermes" / "hermes-agent",
        Path("/Users/kenan/.hermes/hermes-agent"),
    ]
    for _candidate in _runtime_candidates:
        if (_candidate / "hermes_cli" / "kanban_db_connect.py").exists():
            sys.path.insert(0, str(_candidate))
            break
    import hermes_cli.kanban_db_connect  # noqa: F401

from hermes_cli.kanban_db_connect import connect  # not the deprecated re-export
from hermes_cli import kanban_db as kb

# Fixed clock: every deterministic assertion runs under --now NOW.
NOW = 1_788_000_000
NOW_TEXT = str(NOW)

_SCRUB_ENV_VARS = (
    "HERMES_KANBAN_DB",
    "HERMES_KANBAN_BOARD",
    "HERMES_KANBAN_HOME",
    "HERMES_KANBAN_WORKSPACES_ROOT",
    "HERMES_KANBAN_WORKSPACE",
    "HERMES_KANBAN_TASK",
    "HERMES_DELEGATED_CHILD_CONTEXT",
    "HERMES_DEV_DIGEST_ARTIFACTS_ROOT",
)


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

class IsolatedDigestHome(unittest.TestCase):
    """Base case: fresh temp HERMES_HOME + artifacts root, real kanban DBs."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / ".hermes"
        self.home.mkdir()
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self._env_backup = os.environ.copy()
        self.addCleanup(self._restore_env)
        os.environ["HERMES_HOME"] = str(self.home)
        os.environ["HERMES_KANBAN_HOME"] = str(self.home)
        for var in _SCRUB_ENV_VARS:
            os.environ.pop(var, None)
        self._procs = []
        self.addCleanup(self._reap_procs)

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _reap_procs(self) -> None:
        for proc in self._procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

    # -- fixture helpers (real hermes runtime) ------------------------------

    def create_card(self, board, *, title: str = "Dev task", **kwargs) -> str:
        with closing(connect(board=board)) as conn:
            return kb.create_task(
                conn, title=title, body="digest fixture",
                assignee="default", created_by="default", **kwargs
            )

    def claim_card(self, board, card_id: str) -> None:
        with closing(connect(board=board)) as conn:
            claimed = kb.claim_task(conn, card_id)
        self.assertIsNotNone(claimed, "fixture card must claim ready -> running")

    def set_status(self, board, card_id: str, status: str) -> None:
        with closing(connect(board=board)) as conn:
            conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, card_id))
            conn.commit()

    def set_task_times(self, board, card_id: str, started_at: int, heartbeat=None) -> None:
        with closing(connect(board=board)) as conn:
            conn.execute(
                "UPDATE tasks SET started_at = ?, last_heartbeat_at = ? WHERE id = ?",
                (started_at, heartbeat, card_id),
            )
            conn.commit()

    def set_run_times(self, board, card_id: str, started_at: int, heartbeat=None) -> None:
        with closing(connect(board=board)) as conn:
            conn.execute(
                "UPDATE task_runs SET started_at = ?, last_heartbeat_at = ? "
                "WHERE id = (SELECT current_run_id FROM tasks WHERE id = ?)",
                (started_at, heartbeat, card_id),
            )
            conn.commit()

    # -- external guard state fixtures ---------------------------------------

    def write_external(
        self, slug: str, card_id: str, *, attempt=None, raw: str = None,
        payload_updates: dict = None,
    ) -> Path:
        path = self.artifacts / slug / "tasks" / card_id / "external-execution.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
            return path
        payload = {
            "schema": "development-external-execution.v1",
            "card_id": card_id,
            "repo": str(self.root),
            "baseline_head": "0" * 40,
            "baseline_porcelain": [],
            "attempt": attempt,
            "commit": None,
            "updated_at": iso(NOW - 600),
        }
        if payload_updates:
            payload.update(payload_updates)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def external_attempt(self, *, state: str = "running", pid=None) -> dict:
        return {
            "number": 1,
            "operation": "execution",
            "state": state,
            "pid": pid,
            "process_start": None,
            "out_dir": str(self.artifacts / "relay-out"),
            "result_path": str(self.artifacts / "relay-out" / "result.json"),
            "session_id": None,
        }

    # -- digest invocation ---------------------------------------------------

    def run_digest(self, now=NOW_TEXT):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("HERMES_KANBAN_")
        }
        env.pop("HERMES_HOME", None)
        env.pop("HERMES_DEV_DIGEST_ARTIFACTS_ROOT", None)
        command = [
            sys.executable, str(SCRIPT),
            "--home", str(self.home),
            "--artifacts-root", str(self.artifacts),
        ]
        if now is not None:
            command += ["--now", str(now)]
        return subprocess.run(
            command, capture_output=True, text=True, timeout=120, env=env
        )

    def digest_lines(self, now=NOW_TEXT):
        result = self.run_digest(now=now)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line for line in result.stdout.splitlines() if line]

    def by_card(self, lines):
        return {line.split(" | ")[0].split("/", 1)[1]: line for line in lines}

    # -- process fixtures ----------------------------------------------------

    def spawn_sleeper(self) -> subprocess.Popen:
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self._procs.append(proc)
        return proc

    def dead_pid(self) -> int:
        proc = subprocess.Popen(["sleep", "0.2"])
        proc.wait()
        return proc.pid


# ---------------------------------------------------------------------------
# 1. Empty active state is silent
# ---------------------------------------------------------------------------

class TestSilentWhenEmpty(IsolatedDigestHome):
    def test_empty_boards_print_nothing(self) -> None:
        # Real (hermes-created) empty board DBs on both the default and a
        # named board: zero active cards -> empty stdout, exit 0.
        with closing(connect(board=None)) as conn:
            conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
        with closing(connect(board="alpha")) as conn:
            conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
        result = self.run_digest()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_home_without_any_kanban_db_is_quiet(self) -> None:
        result = self.run_digest()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_only_inactive_cards_are_silent(self) -> None:
        done = self.create_card(None)
        self.set_status(None, done, "done")
        archived = self.create_card(None)
        self.set_status(None, archived, "archived")
        result = self.run_digest()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


# ---------------------------------------------------------------------------
# 2. Active cards: stable sort + native status/run age
# ---------------------------------------------------------------------------

class TestActiveCards(IsolatedDigestHome):
    def test_active_cards_stably_sorted_with_native_status_and_run_age(self) -> None:
        blocked = self.create_card("alpha", initial_status="blocked")
        ready_a = self.create_card("alpha")
        ready_b = self.create_card("alpha")
        running = self.create_card(None)
        done = self.create_card(None)
        self.set_status(None, done, "done")
        self.claim_card(None, running)
        # 1h since the blocked card's last known activity.
        self.set_task_times("alpha", blocked, NOW - 3_600)
        # Current run: started 4h30m ago, last heartbeat 1m ago -> run 1m.
        self.set_task_times(None, running, NOW - 16_200, heartbeat=NOW - 300)
        self.set_run_times(None, running, NOW - 16_200, heartbeat=NOW - 60)

        lines = self.digest_lines()
        expected = [
            f"alpha/{blocked} | blocked | run 1h | relay none",
            f"alpha/{min(ready_a, ready_b)} | ready | run - | relay none",
            f"alpha/{max(ready_a, ready_b)} | ready | run - | relay none",
            f"default/{running} | running | run 1m | relay none",
        ]
        self.assertEqual(lines, expected)

    def test_two_runs_identical(self) -> None:
        card_id = self.create_card("alpha")
        self.claim_card("alpha", card_id)
        self.set_task_times("alpha", card_id, NOW - 120)
        self.set_run_times("alpha", card_id, NOW - 120)
        first = self.run_digest()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_digest()
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(
            first.stdout, f"alpha/{card_id} | running | run 2m | relay none\n"
        )
        self.assertEqual(first.stderr, "")

    def test_corrupt_board_db_skipped_without_crashing(self) -> None:
        good = self.create_card("good")
        broken = self.home / "kanban" / "boards" / "broken"
        broken.mkdir(parents=True)
        (broken / "kanban.db").write_bytes(b"this is definitely not a sqlite database" * 8)

        result = self.run_digest()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, f"good/{good} | ready | run - | relay none\n")
        stderr_lines = [line for line in result.stderr.splitlines() if line]
        self.assertEqual(len(stderr_lines), 1)
        self.assertIn("broken", stderr_lines[0])


# ---------------------------------------------------------------------------
# 3. Optional external state -> five simple Relay states
# ---------------------------------------------------------------------------

class TestRelayStates(IsolatedDigestHome):
    def _running_card(self, slug: str = "default") -> str:
        card_id = self.create_card(slug)
        self.claim_card(slug, card_id)
        self.set_task_times(slug, card_id, NOW - 600)
        self.set_run_times(slug, card_id, NOW - 600)
        return card_id

    def test_five_relay_states_from_external_attempt(self) -> None:
        no_file = self._running_card()
        no_attempt = self._running_card()
        reserved = self._running_card()
        live = self._running_card()
        terminal = self._running_card()
        uncertain = self._running_card()
        dead_pid = self._running_card()

        self.write_external("default", no_attempt, attempt=None)
        self.write_external("default", reserved, attempt=self.external_attempt(state="reserved"))
        self.write_external(
            "default", live,
            attempt=self.external_attempt(state="running", pid=self.spawn_sleeper().pid),
        )
        self.write_external("default", terminal, attempt=self.external_attempt(state="terminal"))
        self.write_external("default", uncertain, attempt=self.external_attempt(state="uncertain"))
        self.write_external(
            "default", dead_pid,
            attempt=self.external_attempt(state="running", pid=self.dead_pid()),
        )

        lines = self.by_card(self.digest_lines())
        self.assertEqual(lines[no_file], f"default/{no_file} | running | run 10m | relay none")
        self.assertEqual(lines[no_attempt], f"default/{no_attempt} | running | run 10m | relay none")
        self.assertEqual(lines[reserved], f"default/{reserved} | running | run 10m | relay reserved")
        self.assertEqual(lines[live], f"default/{live} | running | run 10m | relay live")
        self.assertEqual(lines[terminal], f"default/{terminal} | running | run 10m | relay terminal")
        self.assertEqual(lines[uncertain], f"default/{uncertain} | running | run 10m | relay uncertain")
        self.assertEqual(
            lines[dead_pid],
            f"default/{dead_pid} | running | run 10m | relay uncertain "
            "(running attempt without a live pid)",
        )


# ---------------------------------------------------------------------------
# 4. Missing/malformed external state never crashes or hides the card
# ---------------------------------------------------------------------------

class TestMalformedExternalState(IsolatedDigestHome):
    def test_missing_or_malformed_external_state_maps_to_uncertain(self) -> None:
        labels = (
            "bad_json", "wrong_schema", "not_object",
            "attempt_string", "unknown_state", "unreadable",
        )
        cards = {}
        for label in labels:
            card_id = self.create_card(None)
            self.claim_card(None, card_id)
            self.set_task_times(None, card_id, NOW - 600)
            self.set_run_times(None, card_id, NOW - 600)
            if label == "bad_json":
                self.write_external("default", card_id, raw="{not json at all")
            elif label == "wrong_schema":
                self.write_external(
                    "default", card_id,
                    raw=json.dumps({"schema": "development-execution-receipt.v1"}),
                )
            elif label == "not_object":
                self.write_external("default", card_id, raw=json.dumps([1, 2, 3]))
            elif label == "attempt_string":
                self.write_external("default", card_id, attempt="spawned")
            elif label == "unknown_state":
                self.write_external(
                    "default", card_id, attempt=self.external_attempt(state="wedged")
                )
            elif label == "unreadable":
                path = self.write_external(
                    "default", card_id, attempt=self.external_attempt(state="running", pid=1)
                )
                path.chmod(0o000)
                self.addCleanup(path.chmod, 0o644)
            cards[label] = card_id

        result = self.run_digest()
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.by_card([line for line in result.stdout.splitlines() if line])
        self.assertEqual(set(lines), set(cards.values()))
        for label, card_id in cards.items():
            with self.subTest(label=label):
                self.assertIn(
                    f"default/{card_id} | running | run 10m | relay uncertain (", lines[card_id]
                )
                # At most a one-line, bracketed note; no card content leaks.
                self.assertNotIn("not json at all", lines[card_id])

    def test_secret_in_external_state_file_never_reaches_output(self) -> None:
        secret = "sk-live-abcdef123456WXYZ"
        card_id = self.create_card(None)
        self.claim_card(None, card_id)
        self.set_task_times(None, card_id, NOW - 600)
        self.set_run_times(None, card_id, NOW - 600)
        self.write_external("default", card_id, raw=f'{{"schema": "{secret}", "x": "{secret}"}}')

        result = self.run_digest()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, result.stderr)
        self.assertIn(
            f"default/{card_id} | running | run 10m | relay uncertain (external state wrong schema)",
            result.stdout,
        )


# ---------------------------------------------------------------------------
# 5. Read-only proof
# ---------------------------------------------------------------------------

class TestReadOnly(IsolatedDigestHome):
    def _snapshot(self, root: Path):
        """names + sizes + mtimes + inodes for every file; content hashes for
        everything except SQLite ``-shm`` sidecars (readers legitimately rotate
        the pre-existing shared-memory read marks; database bytes must not
        change and no file may appear or disappear)."""
        meta = {}
        hashes = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(root))
            stat = path.stat()
            meta[relative] = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            if not relative.endswith("-shm"):
                hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return meta, hashes

    def test_board_files_external_state_files_and_mtimes_unchanged(self) -> None:
        # Cold board: created through hermes (realistic WAL-mode DB), then
        # cleanly closed -> no sidecars left -> the immutable read path must
        # not recreate even an empty -wal/-shm.
        cold_id = self.create_card("cold")
        self.claim_card("cold", cold_id)
        self.set_task_times("cold", cold_id, NOW - 60)
        self.set_run_times("cold", cold_id, NOW - 60)
        cold_db = self.home / "kanban" / "boards" / "cold" / "kanban.db"
        self.assertEqual(
            cold_db.with_name(cold_db.name + "-wal").exists(), False
        )

        # Hot board: a live hermes connection keeps -wal/-shm present; its
        # committed-but-uncheckpointed card must still be read via the WAL.
        writer = connect(board="hot")
        self.addCleanup(writer.close)
        hot_id = kb.create_task(
            writer, title="Hot dev task", body="hot probe",
            assignee="default", created_by="default",
        )
        hot_wal = self.home / "kanban" / "boards" / "hot" / "kanban.db-wal"
        self.assertTrue(hot_wal.exists())

        # External guard state on disk for both cards.
        self.write_external(
            "cold", cold_id, attempt=self.external_attempt(state="reserved")
        )
        self.write_external(
            "hot", hot_id, attempt=self.external_attempt(state="terminal")
        )

        before_meta, before_hashes = self._snapshot(self.root)

        result = self.run_digest()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"cold/{cold_id} | running | run 1m | relay reserved\n"
            f"hot/{hot_id} | ready | run - | relay terminal\n",
        )

        after_meta, after_hashes = self._snapshot(self.root)
        self.assertEqual(sorted(before_meta), sorted(after_meta), "file list changed")
        self.assertEqual(before_meta, after_meta, "file size/mtime/inode changed")
        self.assertEqual(before_hashes, after_hashes, "file content changed")
        self.assertFalse(cold_db.with_name(cold_db.name + "-wal").exists())

        # DB content is unchanged through the real API as well.
        with closing(connect(board="cold")) as conn:
            task = kb.get_task(conn, cold_id)
        self.assertEqual(task.status, "running")
        self.assertEqual(task.started_at, NOW - 60)


# ---------------------------------------------------------------------------
# Cron launcher compatibility (job 7f5731367ce5 runs the launcher, which
# executes the tracked digest with sys.argv passthrough / env defaults)
# ---------------------------------------------------------------------------

class TestCronLauncherCompat(IsolatedDigestHome):
    """Cron job 7f5731367ce5 runs the launcher from ``<home>/scripts/``, where
    the deployed digest sits beside it (the launcher resolves the digest via
    ``Path(__file__).with_name``), so the tests stage that deployed layout."""

    def _deployed_launcher(self) -> Path:
        deployed = self.root / "scripts"
        deployed.mkdir(exist_ok=True)
        shutil.copy2(LAUNCHER, deployed / LAUNCHER.name)
        shutil.copy2(SCRIPT, deployed / SCRIPT.name)
        return deployed / LAUNCHER.name

    def _launcher_env(self) -> dict:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("HERMES_KANBAN_")
        }
        env.pop("HERMES_HOME", None)
        env.pop("HERMES_DEV_DIGEST_ARTIFACTS_ROOT", None)
        return env

    def test_launcher_passes_home_argument_through(self) -> None:
        card_id = self.create_card(None)
        self.claim_card(None, card_id)
        self.set_task_times(None, card_id, NOW - 120)
        self.set_run_times(None, card_id, NOW - 120)
        result = subprocess.run(
            [
                sys.executable, str(self._deployed_launcher()),
                "--home", str(self.home),
                "--artifacts-root", str(self.artifacts),
                "--now", NOW_TEXT,
            ],
            capture_output=True, text=True, timeout=120, env=self._launcher_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"default/{card_id} | running | run 2m | relay none\n")

    def test_launcher_works_with_env_defaults_and_no_arguments(self) -> None:
        # The cron scheduler executes the launcher with NO argv; the digest
        # must resolve home from $HERMES_HOME (as set for cron subprocesses).
        card_id = self.create_card(None)
        self.set_task_times(None, card_id, NOW - 3_600)
        env = self._launcher_env()
        env["HERMES_HOME"] = str(self.home)
        env["HERMES_DEV_DIGEST_ARTIFACTS_ROOT"] = str(self.artifacts)
        result = subprocess.run(
            [sys.executable, str(self._deployed_launcher()), "--now", NOW_TEXT],
            capture_output=True, text=True, timeout=120, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"default/{card_id} | ready | run 1h | relay none\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCli(IsolatedDigestHome):
    def test_usage_error_exits_two(self) -> None:
        env = os.environ.copy()
        env.pop("HERMES_HOME", None)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--home", str(self.home), "--now", "not-a-timestamp"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
