#!/usr/bin/env python3
"""Global read-only development status digest (minimal MVP).

One fixed-interval, zero-agent cron report replaces every per-Card monitor:
each tick enumerates every Kanban board under ``<home>``, selects the active
cards (every native status except ``done``/``archived``), and prints one
line per card built only from native Kanban data plus — when present — the
external guard's Relay classification reduced to five simple states.

The digest is STRICTLY read-only and PURE STDLIB: every board DB is opened
with SQLite ``mode=ro`` plus ``PRAGMA query_only=ON`` (plus ``immutable=1``
when no WAL sidecars exist, so even an empty ``-wal``/``-shm`` is never
created); no file is ever created, migrated, or written.  It runs under
cron with any Python 3.11 interpreter — no ``hermes_cli`` import — and
never prints a card body, prompt, log, file content, or secret.

Optional external guard state (plan §2.2) lives at
``<artifacts-root>/<board-slug>/tasks/<card-id>/external-execution.json``
(``schema: development-external-execution.v1``; ``attempt.state`` one of
``reserved/running/terminal/uncertain``) and maps to exactly five Relay
states: no state file or no attempt -> ``none``; ``reserved`` ->
``reserved``; ``running`` with a live pid -> ``live``; ``running`` with a
dead pid -> ``uncertain``; ``terminal`` -> ``terminal``; ``uncertain`` ->
``uncertain``; a missing, malformed, unreadable, or wrong-schema file ->
``uncertain`` plus at most a one-line note.  Such a problem affects that
one line only: it never crashes the digest and never hides the card's
native line.

Output — one line per active card, stably sorted by (board, column, card
id), byte-identical across runs under a fixed ``--now``; nothing at all
when there are zero active cards:

    <board>/<card-id> | <status> | run <age> | relay <state>[( <note>)]

``<age>`` is the age of the card's current run — the newest of the current
``task_runs`` row's heartbeat/start timestamps, falling back to the task's
own ``started_at``/``last_heartbeat_at`` — rounded like ``3m``/``2h``/
``4h30m``; ``-`` when no timestamp is known.  Exit status is 0 for every
normal run (per-board problems are one-line STDERR diagnostics and the
board is skipped); 2 only for usage errors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

EXTERNAL_SCHEMA = "development-external-execution.v1"
EXTERNAL_FILENAME = "external-execution.json"
ARCHIVED_BOARD_SLUG = "_archived"
DEFAULT_BOARD_SLUG = "default"
MAX_PID = 2_147_483_647
SAFE_CARD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_EPOCH_TEXT = re.compile(r"[+-]?\d+(?:\.\d+)?")
_PROGRAM = "development-status-digest"

SELECT_ACTIVE_SQL = (
    "SELECT t.id, t.status, t.started_at, t.last_heartbeat_at, "
    "r.started_at AS run_started_at, r.last_heartbeat_at AS run_heartbeat_at "
    "FROM tasks t LEFT JOIN task_runs r ON r.id = t.current_run_id "
    "WHERE t.status NOT IN ('done', 'archived')"
)


@dataclass(frozen=True)
class CardLine:
    """One rendered digest row; ordering key is (board, column, card id)."""

    board: str
    card_id: str
    status: str
    age: str
    relay: str
    note: Optional[str] = None

    def order_key(self) -> Tuple[str, str, str]:
        return (self.board, self.status, self.card_id)

    def render(self) -> str:
        line = (
            f"{self.board}/{self.card_id} | {self.status} "
            f"| run {self.age} | relay {self.relay}"
        )
        if self.note:
            line += f" ({self.note})"
        return line


# ---------------------------------------------------------------------------
# Board discovery and strictly read-only DB access
# ---------------------------------------------------------------------------

def discover_boards(home: Path) -> List[Tuple[str, Path]]:
    """``(slug, db_path)`` pairs: named boards under ``<home>/kanban/boards``
    (``_archived`` skipped) plus the default ``<home>/kanban.db``; duplicate
    resolved paths (symlinks to the default DB) keep the named-board slug."""
    found: List[Tuple[str, Path]] = []
    boards_root = home / "kanban" / "boards"
    if boards_root.is_dir():
        try:
            entries = sorted(boards_root.iterdir(), key=lambda item: item.name)
        except OSError as err:
            # Same never-crash contract as per-board DB problems: one STDERR
            # line, then continue with the remaining discoverable boards.
            print(f"{_PROGRAM}: boards dir unreadable: {err}", file=sys.stderr)
            entries = []
        for entry in entries:
            if entry.name == ARCHIVED_BOARD_SLUG or not entry.is_dir():
                continue
            candidate = entry / "kanban.db"
            if candidate.is_file():
                found.append((entry.name, candidate))
    default_db = home / "kanban.db"
    if default_db.is_file():
        found.append((DEFAULT_BOARD_SLUG, default_db))

    deduped: List[Tuple[str, Path]] = []
    seen = set()
    for slug, db_path in found:
        resolved = os.path.realpath(db_path)
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append((slug, db_path))
    return deduped


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a board DB strictly read-only; never create any sidecar file.

    A bare ``mode=ro`` connection still creates fresh ``-wal``/``-shm``
    sidecars when a cleanly-closed WAL database has none, so then the open
    also passes ``immutable=1`` — safe, because a WAL database without a
    ``-wal`` file is fully checkpointed.  With a live ``-wal``/``-shm``
    pair, plain ``mode=ro`` attaches to the existing shared memory, reads
    WAL-committed state, and creates nothing.
    """
    sidecars = (
        db_path.with_name(db_path.name + "-wal").exists()
        or db_path.with_name(db_path.name + "-shm").exists()
    )
    uri = "file:" + urllib.parse.quote(str(db_path))
    uri += "?mode=ro" if sidecars else "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _diagnostic(slug: str, db_path: Path, reason: Any) -> None:
    """One single-line STDERR diagnostic; never a card body or secret."""
    text = " ".join(str(reason).split()) or reason.__class__.__name__
    print(f"{_PROGRAM}: skipping board '{slug}' ({db_path}): {text}", file=sys.stderr)


def load_board_rows(slug: str, db_path: Path, is_default: bool) -> List[sqlite3.Row]:
    """Read one board's active cards read-only; a board whose DB cannot be
    opened or queried yields one STDERR diagnostic and no cards — it never
    crashes the digest.  The default ``<home>/kanban.db`` is only a board
    when it carries the Kanban schema, so a stray file there is skipped
    silently.
    """
    try:
        conn = _open_readonly(db_path)
    except (sqlite3.Error, OSError) as exc:
        _diagnostic(slug, db_path, exc)
        return []
    try:
        has_tasks = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tasks' LIMIT 1"
        ).fetchone()
        if has_tasks is None:
            if not is_default:
                _diagnostic(slug, db_path, "no Kanban tasks table")
            return []
        return conn.execute(SELECT_ACTIVE_SQL).fetchall()
    except sqlite3.Error as exc:
        _diagnostic(slug, db_path, exc)
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Optional external guard state -> five simple Relay states
# ---------------------------------------------------------------------------

def _pid_alive(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, but is owned by another user
    except (OSError, OverflowError, ValueError):
        return False
    return True


def classify_relay(artifacts_root: Path, slug: str, card_id: str) -> Tuple[str, Optional[str]]:
    """Map the optional external guard state to ``(relay_state, note)``.

    The state file is only consulted at the canonical path when the ids can
    name a safe one.  The note is at most one short fixed line (never file
    content) and only accompanies an ``uncertain`` classification.
    """
    if SAFE_SLUG.fullmatch(slug) is None or SAFE_CARD_ID.fullmatch(card_id) is None:
        return "none", None
    path = artifacts_root / slug / "tasks" / card_id / EXTERNAL_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "none", None
    except (OSError, ValueError):  # unreadable / undecodable
        return "uncertain", "external state unreadable"
    try:
        value = json.loads(raw)
    except ValueError:  # JSONDecodeError and UnicodeError are both ValueError
        return "uncertain", "external state not JSON"
    if not isinstance(value, dict):
        return "uncertain", "external state not an object"
    if value.get("schema") != EXTERNAL_SCHEMA:
        return "uncertain", "external state wrong schema"
    attempt = value.get("attempt")
    if attempt is None:
        return "none", None
    if not isinstance(attempt, dict):
        return "uncertain", "attempt not an object"
    state = attempt.get("state")
    if state == "reserved":
        return "reserved", None
    if state == "terminal":
        return "terminal", None
    if state == "uncertain":
        return "uncertain", None
    if state == "running":
        pid = attempt.get("pid")
        if (
            isinstance(pid, int) and not isinstance(pid, bool)
            and 0 < pid <= MAX_PID and _pid_alive(pid)
        ):
            return "live", None
        return "uncertain", "running attempt without a live pid"
    return "uncertain", "unknown attempt state"


# ---------------------------------------------------------------------------
# Native run age and report assembly
# ---------------------------------------------------------------------------

def format_elapsed(seconds: float) -> str:
    """Rounded human form: ``3m``, ``2h``, ``4h30m``."""
    total_minutes = int(seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours == 0:
        return f"{minutes}m"
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h{minutes}m"


def _newest(*stamps: Any) -> Optional[float]:
    values = [
        float(stamp)
        for stamp in stamps
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and stamp > 0
    ]
    return max(values) if values else None


def age_text(now: float, row: sqlite3.Row) -> str:
    """Age of the current run (heartbeat/start); ``-`` when nothing is known."""
    base = _newest(row["run_heartbeat_at"], row["run_started_at"],
                   row["last_heartbeat_at"], row["started_at"])
    return "-" if base is None else format_elapsed(max(0.0, now - base))


def build_report(home: Path, artifacts_root: Path, now: float) -> List[CardLine]:
    """Classify every active card across every board, stably sorted."""
    cards: List[CardLine] = []
    for slug, db_path in discover_boards(home):
        for row in load_board_rows(slug, db_path, is_default=slug == DEFAULT_BOARD_SLUG):
            card_id = str(row["id"])
            relay, note = classify_relay(artifacts_root, slug, card_id)
            cards.append(
                CardLine(
                    board=slug,
                    card_id=card_id,
                    status=str(row["status"] or ""),
                    age=age_text(now, row),
                    relay=relay,
                    note=note,
                )
            )
    cards.sort(key=CardLine.order_key)
    return cards


def _coerce_now(text: str) -> float:
    """Accept an epoch or an ISO-8601 timestamp; naive ISO reads as UTC."""
    stripped = text.strip()
    if _EPOCH_TEXT.fullmatch(stripped):
        return float(stripped)
    value = stripped[:-1] + "+00:00" if stripped.endswith(("Z", "z")) else stripped
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"not an epoch or ISO-8601 timestamp: {text!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=_PROGRAM, description="Global read-only development status digest."
    )
    parser.add_argument("--home", default=None,
                        help="Hermes home (default: $HERMES_HOME or ~/.hermes)")
    parser.add_argument(
        "--artifacts-root", default=None,
        help="development artifacts root (default: $HERMES_DEV_DIGEST_ARTIFACTS_ROOT "
             "or ~/Secret-Projects/development-artifacts)",
    )
    parser.add_argument(
        "--now", default=None,
        help="override the clock with an epoch or ISO-8601 timestamp (deterministic runs)",
    )
    args = parser.parse_args(argv)

    home = Path(args.home or os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
    artifacts_root = Path(
        args.artifacts_root
        or os.environ.get("HERMES_DEV_DIGEST_ARTIFACTS_ROOT")
        or "~/Secret-Projects/development-artifacts"
    ).expanduser()
    now = time.time()
    if args.now is not None:
        try:
            now = _coerce_now(args.now)
        except ValueError as exc:
            parser.error(f"--now: {exc}")

    for card in build_report(home, artifacts_root, now):
        print(card.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
