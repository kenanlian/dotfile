"""Shared Workflow SQLite store with CAS, immutable artifacts, and repo leases."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from .protocol import assert_allowed_transition, parse_manifest, require_absolute_path, require_sha256
from .templates import get_template
from .types import (
    LEASE_RELEASE_REASONS,
    WorkflowConflict,
    WorkflowProtocolError,
    WorkflowStatus,
)

SCHEMA_VERSION = 2

MIGRATIONS: tuple[str, ...] = (
    """
CREATE TABLE IF NOT EXISTS workflow_manifests (
  board TEXT NOT NULL,
  task_id TEXT NOT NULL,
  schema TEXT NOT NULL,
  template_id TEXT NOT NULL,
  repo_root TEXT NOT NULL,
  workflow_status TEXT NOT NULL,
  revision INTEGER NOT NULL,
  manifest_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY(board, task_id)
);

CREATE TABLE IF NOT EXISTS workflow_jobs (
  job_id TEXT PRIMARY KEY,
  board TEXT NOT NULL,
  task_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  business_attempt INTEGER NOT NULL,
  transport_retry INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  job_path TEXT NOT NULL,
  run_dir TEXT NOT NULL,
  job_sha256 TEXT NOT NULL,
  harness_pid INTEGER,
  process_identity TEXT,
  status TEXT NOT NULL,
  result_path TEXT,
  started_at INTEGER,
  finished_at INTEGER,
  consumed_at INTEGER
);

CREATE TABLE IF NOT EXISTS workflow_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  board TEXT NOT NULL,
  task_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  version INTEGER NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(board, task_id, kind, version)
);

CREATE TABLE IF NOT EXISTS workflow_repo_leases (
  repo_root TEXT PRIMARY KEY,
  board TEXT NOT NULL,
  task_id TEXT NOT NULL,
  fencing_token TEXT NOT NULL,
  acquired_at INTEGER NOT NULL,
  released_at INTEGER
);

CREATE TABLE IF NOT EXISTS workflow_intake (
  idempotency_key TEXT PRIMARY KEY,
  board TEXT NOT NULL,
  task_id TEXT,
  repo_root TEXT NOT NULL,
  predecessor_task_id TEXT,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
""",
    """
ALTER TABLE workflow_intake ADD COLUMN template_id TEXT;
ALTER TABLE workflow_intake ADD COLUMN verification_sha256 TEXT;
""",
)


def canonical_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> int:
    return int(time.time())


def _exec_statements(conn: sqlite3.Connection, sql: str) -> None:
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    if column not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _load_cas_manifest_row(
    conn: sqlite3.Connection, board: str, task_id: str, expected_revision: int
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM workflow_manifests WHERE board = ? AND task_id = ? AND revision = ?",
        (board, task_id, expected_revision),
    ).fetchone()
    loaded = _row_dict(row)
    if loaded is None:
        raise WorkflowConflict(f"CAS failed for {board}/{task_id} at revision {expected_revision}")
    return loaded


def _assert_manifest_identity_and_transition(existing_json: str, parsed_new: Any) -> None:
    old = parse_manifest(json.loads(existing_json))
    if (
        old.schema != parsed_new.schema
        or old.template_id != parsed_new.template_id
        or old.repo_root != parsed_new.repo_root
        or old.board != parsed_new.board
        or old.task_id != parsed_new.task_id
    ):
        raise WorkflowProtocolError(
            "manifest schema, templateId, repoRoot, and task identity cannot change"
        )
    if old.status is parsed_new.status:
        return
    template = get_template(old.template_id)
    if parsed_new.status is WorkflowStatus.BLOCKED and old.status is not WorkflowStatus.COMPLETED:
        return
    if old.status is WorkflowStatus.BLOCKED and parsed_new.status in template.allowed_statuses:
        if parsed_new.status is not WorkflowStatus.COMPLETED:
            return
    assert_allowed_transition(old.status, parsed_new.status, template_id=old.template_id)


class WorkflowStore:
    """Durable checkpoints for one explicit absolute state root."""

    def __init__(self, state_root: str) -> None:
        if not isinstance(state_root, str) or not state_root.strip():
            raise WorkflowProtocolError("state_root must be an explicit absolute path")
        root = Path(state_root)
        if not root.is_absolute() or state_root.startswith("./") or state_root.startswith("../"):
            raise WorkflowProtocolError("state_root must be an explicit absolute path")
        self._state_root = root.resolve()
        self._state_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._state_root / "data.db"
        self._migrate()

    @property
    def state_root(self) -> Path:
        return self._state_root

    @property
    def db_path(self) -> Path:
        return self._db_path

    def table_names(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        return {row["name"] for row in rows}

    def schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
        return int(row["version"])

    def put_manifest(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        parsed = parse_manifest(manifest)
        text = canonical_dumps(manifest)
        stored = json.loads(text)
        if stored["revision"] != parsed.revision:
            raise WorkflowProtocolError("stored revision must match JSON revision")
        now = _now()
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT revision FROM workflow_manifests WHERE board = ? AND task_id = ?",
                (parsed.board, parsed.task_id),
            ).fetchone()
            if existing is not None:
                raise WorkflowConflict(
                    f"manifest already exists for {parsed.board}/{parsed.task_id}"
                )
            conn.execute(
                """
                INSERT INTO workflow_manifests(
                  board, task_id, schema, template_id, repo_root, workflow_status,
                  revision, manifest_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parsed.board,
                    parsed.task_id,
                    parsed.schema,
                    parsed.template_id,
                    parsed.repo_root,
                    parsed.status.value,
                    parsed.revision,
                    text,
                    now,
                ),
            )
        return stored

    def get_manifest(self, board: str, task_id: str) -> dict[str, Any] | None:
        row = self.get_manifest_row(board, task_id)
        if row is None:
            return None
        return json.loads(row["manifest_json"])

    def get_manifest_row(self, board: str, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_manifests WHERE board = ? AND task_id = ?",
                (board, task_id),
            ).fetchone()
        return _row_dict(row)

    def cas_update_manifest(
        self,
        board: str,
        task_id: str,
        *,
        expected_revision: int,
        manifest: Mapping[str, Any],
    ) -> dict[str, Any]:
        parsed = parse_manifest(manifest)
        if parsed.board != board or parsed.task_id != task_id:
            raise WorkflowProtocolError("CAS manifest board/task must match the row identity")
        if parsed.revision != expected_revision + 1:
            raise WorkflowProtocolError("CAS revision must increment by 1")
        text = canonical_dumps(manifest)
        stored = json.loads(text)
        if stored["revision"] != parsed.revision:
            raise WorkflowProtocolError("stored revision must match JSON revision")
        now = _now()
        with self._transaction() as conn:
            existing = _load_cas_manifest_row(conn, board, task_id, expected_revision)
            _assert_manifest_identity_and_transition(existing["manifest_json"], parsed)
            cursor = conn.execute(
                """
                UPDATE workflow_manifests
                SET schema = ?, template_id = ?, repo_root = ?, workflow_status = ?,
                    revision = ?, manifest_json = ?, updated_at = ?
                WHERE board = ? AND task_id = ? AND revision = ?
                """,
                (
                    parsed.schema,
                    parsed.template_id,
                    parsed.repo_root,
                    parsed.status.value,
                    parsed.revision,
                    text,
                    now,
                    board,
                    task_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise WorkflowConflict(
                    f"CAS failed for {board}/{task_id} at revision {expected_revision}"
                )
        return stored

    def put_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        record = {
            "job_id": job["job_id"],
            "board": job["board"],
            "task_id": job["task_id"],
            "stage": job["stage"],
            "business_attempt": int(job["business_attempt"]),
            "transport_retry": int(job["transport_retry"]),
            "idempotency_key": job["idempotency_key"],
            "job_path": require_absolute_path(job["job_path"], "job_path"),
            "run_dir": require_absolute_path(job["run_dir"], "run_dir"),
            "job_sha256": require_sha256(job["job_sha256"], "job_sha256"),
            "harness_pid": job.get("harness_pid"),
            "process_identity": job.get("process_identity"),
            "status": job["status"],
            "result_path": job.get("result_path"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "consumed_at": job.get("consumed_at"),
        }
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM workflow_jobs WHERE job_id = ? OR idempotency_key = ?",
                (record["job_id"], record["idempotency_key"]),
            ).fetchone()
            if existing is not None:
                current = _row_dict(existing)
                if current != record:
                    raise WorkflowConflict("job identity conflict")
                return current
            bound = conn.execute(
                "SELECT manifest_json FROM workflow_manifests WHERE board = ? AND task_id = ?",
                (record["board"], record["task_id"]),
            ).fetchone()
            if bound is None:
                raise WorkflowProtocolError("cannot insert a Job without a bound Manifest")
            manifest = parse_manifest(json.loads(bound["manifest_json"]))
            template = get_template(manifest.template_id)
            if record["stage"] not in template.allowed_stages:
                raise WorkflowProtocolError(
                    f"job stage {record['stage']!r} is not allowed for template {template.id}"
                )
            conn.execute(
                """
                INSERT INTO workflow_jobs(
                  job_id, board, task_id, stage, business_attempt, transport_retry,
                  idempotency_key, job_path, run_dir, job_sha256, harness_pid,
                  process_identity, status, result_path, started_at, finished_at, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["job_id"],
                    record["board"],
                    record["task_id"],
                    record["stage"],
                    record["business_attempt"],
                    record["transport_retry"],
                    record["idempotency_key"],
                    record["job_path"],
                    record["run_dir"],
                    record["job_sha256"],
                    record["harness_pid"],
                    record["process_identity"],
                    record["status"],
                    record["result_path"],
                    record["started_at"],
                    record["finished_at"],
                    record["consumed_at"],
                ),
            )
        return record

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workflow_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _row_dict(row)

    def list_jobs(self, board: str, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_jobs
                WHERE board = ? AND task_id = ?
                ORDER BY business_attempt ASC, transport_retry ASC, job_id ASC
                """,
                (board, task_id),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "harness_pid",
            "process_identity",
            "status",
            "result_path",
            "started_at",
            "finished_at",
            "consumed_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise WorkflowProtocolError(f"cannot update job fields {sorted(unknown)}")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values())
        with self._transaction() as conn:
            cursor = conn.execute(
                f"UPDATE workflow_jobs SET {assignments} WHERE job_id = ?",
                (*values, job_id),
            )
            if cursor.rowcount != 1:
                raise WorkflowConflict(f"job {job_id} does not exist")
            row = conn.execute("SELECT * FROM workflow_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _row_dict(row)

    def latest_artifact(self, board: str, task_id: str, kind: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM workflow_artifacts
                WHERE board = ? AND task_id = ? AND kind = ?
                ORDER BY version DESC LIMIT 1
                """,
                (board, task_id, kind),
            ).fetchone()
        return _row_dict(row)

    def next_artifact_version(self, board: str, task_id: str, kind: str) -> int:
        current = self.latest_artifact(board, task_id, kind)
        return 1 if current is None else int(current["version"]) + 1

    def checkpoint(
        self,
        *,
        board: str,
        task_id: str,
        expected_revision: int,
        manifest: Mapping[str, Any],
        job_patch: Mapping[str, Any] | None = None,
        artifacts: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Atomically persist job completion, artifacts, and the next Manifest revision."""
        parsed = parse_manifest(manifest)
        if parsed.board != board or parsed.task_id != task_id:
            raise WorkflowProtocolError("checkpoint manifest board/task must match the row identity")
        if parsed.revision != expected_revision + 1:
            raise WorkflowProtocolError("CAS revision must increment by 1")
        text = canonical_dumps(manifest)
        stored = json.loads(text)
        now = _now()
        with self._transaction() as conn:
            existing = _load_cas_manifest_row(conn, board, task_id, expected_revision)
            _assert_manifest_identity_and_transition(existing["manifest_json"], parsed)
            if job_patch:
                job_id = job_patch["job_id"]
                updates = {
                    key: job_patch[key]
                    for key in (
                        "harness_pid",
                        "process_identity",
                        "status",
                        "result_path",
                        "started_at",
                        "finished_at",
                        "consumed_at",
                    )
                    if key in job_patch
                }
                if updates:
                    assignments = ", ".join(f"{key} = ?" for key in updates)
                    cursor = conn.execute(
                        f"UPDATE workflow_jobs SET {assignments} WHERE job_id = ?",
                        (*updates.values(), job_id),
                    )
                    if cursor.rowcount != 1:
                        raise WorkflowConflict(f"job {job_id} does not exist")
            for artifact in artifacts or []:
                path = require_absolute_path(artifact["path"], "artifact.path")
                digest = require_sha256(artifact["sha256"], "artifact.sha256")
                existing = conn.execute(
                    """
                    SELECT * FROM workflow_artifacts
                    WHERE board = ? AND task_id = ? AND kind = ? AND version = ?
                    """,
                    (board, task_id, artifact["kind"], int(artifact["version"])),
                ).fetchone()
                if existing is not None:
                    current = _row_dict(existing)
                    if current["path"] != path or current["sha256"] != digest:
                        raise WorkflowConflict(
                            f"artifact {artifact['kind']}@v{artifact['version']} is immutable"
                        )
                    continue
                conn.execute(
                    """
                    INSERT INTO workflow_artifacts(
                      board, task_id, job_id, kind, version, path, sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        board,
                        task_id,
                        artifact["job_id"],
                        artifact["kind"],
                        int(artifact["version"]),
                        path,
                        digest,
                        now,
                    ),
                )
            cursor = conn.execute(
                """
                UPDATE workflow_manifests
                SET schema = ?, template_id = ?, repo_root = ?, workflow_status = ?,
                    revision = ?, manifest_json = ?, updated_at = ?
                WHERE board = ? AND task_id = ? AND revision = ?
                """,
                (
                    parsed.schema,
                    parsed.template_id,
                    parsed.repo_root,
                    parsed.status.value,
                    parsed.revision,
                    text,
                    now,
                    board,
                    task_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise WorkflowConflict(
                    f"CAS failed for {board}/{task_id} at revision {expected_revision}"
                )
        return stored

    def register_artifact(
        self,
        *,
        board: str,
        task_id: str,
        job_id: str,
        kind: str,
        version: int,
        path: str,
        sha256: str,
    ) -> dict[str, Any]:
        absolute = require_absolute_path(path, "artifact.path")
        expected = require_sha256(sha256, "artifact.sha256")
        file_path = Path(absolute)
        if not file_path.is_file():
            raise WorkflowProtocolError("artifact path does not exist")
        actual = sha256_file(file_path)
        if actual != expected:
            raise WorkflowProtocolError("artifact SHA-256 does not match file contents")
        now = _now()
        with self._transaction() as conn:
            existing = conn.execute(
                """
                SELECT * FROM workflow_artifacts
                WHERE board = ? AND task_id = ? AND kind = ? AND version = ?
                """,
                (board, task_id, kind, version),
            ).fetchone()
            if existing is not None:
                current = _row_dict(existing)
                if current["path"] != absolute or current["sha256"] != expected:
                    raise WorkflowConflict(
                        f"artifact {kind}@v{version} is immutable and cannot be overwritten"
                    )
                return current
            cursor = conn.execute(
                """
                INSERT INTO workflow_artifacts(
                  board, task_id, job_id, kind, version, path, sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (board, task_id, job_id, kind, version, absolute, expected, now),
            )
            return {
                "id": cursor.lastrowid,
                "board": board,
                "task_id": task_id,
                "job_id": job_id,
                "kind": kind,
                "version": version,
                "path": absolute,
                "sha256": expected,
                "created_at": now,
            }

    def get_artifact(self, board: str, task_id: str, kind: str, version: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM workflow_artifacts
                WHERE board = ? AND task_id = ? AND kind = ? AND version = ?
                """,
                (board, task_id, kind, version),
            ).fetchone()
        return _row_dict(row)

    def acquire_repo_lease(
        self,
        repo_root: str,
        *,
        board: str,
        task_id: str,
        fencing_token: str,
    ) -> dict[str, Any]:
        real = str(Path(require_absolute_path(repo_root, "repo_root")).resolve())
        now = _now()
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM workflow_repo_leases WHERE repo_root = ?",
                (real,),
            ).fetchone()
            if existing is not None and existing["released_at"] is None:
                if existing["board"] == board and existing["task_id"] == task_id:
                    return _row_dict(existing)
                raise WorkflowConflict(f"repo already leased by {existing['board']}/{existing['task_id']}")
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO workflow_repo_leases(
                      repo_root, board, task_id, fencing_token, acquired_at, released_at
                    ) VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (real, board, task_id, fencing_token, now),
                )
            else:
                conn.execute(
                    """
                    UPDATE workflow_repo_leases
                    SET board = ?, task_id = ?, fencing_token = ?, acquired_at = ?, released_at = NULL
                    WHERE repo_root = ?
                    """,
                    (board, task_id, fencing_token, now, real),
                )
            row = conn.execute(
                "SELECT * FROM workflow_repo_leases WHERE repo_root = ?",
                (real,),
            ).fetchone()
        return _row_dict(row)

    def release_repo_lease(
        self,
        repo_root: str,
        *,
        board: str,
        task_id: str,
        reason: str,
    ) -> dict[str, Any]:
        if reason not in LEASE_RELEASE_REASONS:
            raise WorkflowProtocolError(
                "repo lease can only be released for completed, archived, or abandon"
            )
        real = str(Path(require_absolute_path(repo_root, "repo_root")).resolve())
        now = _now()
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE workflow_repo_leases
                SET released_at = ?
                WHERE repo_root = ? AND board = ? AND task_id = ? AND released_at IS NULL
                """,
                (now, real, board, task_id),
            )
            if cursor.rowcount != 1:
                raise WorkflowConflict("repo lease is not held by this task")
            row = conn.execute(
                "SELECT * FROM workflow_repo_leases WHERE repo_root = ?",
                (real,),
            ).fetchone()
        return _row_dict(row)

    def get_repo_lease(self, repo_root: str) -> dict[str, Any] | None:
        real = str(Path(require_absolute_path(repo_root, "repo_root")).resolve())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_repo_leases WHERE repo_root = ?",
                (real,),
            ).fetchone()
        return _row_dict(row)

    def put_intake(
        self,
        *,
        idempotency_key: str,
        board: str,
        repo_root: str,
        status: str,
        task_id: str | None = None,
        predecessor_task_id: str | None = None,
        template_id: str | None = None,
        verification_sha256: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM workflow_intake WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                current = _row_dict(existing)
                stored_template = current.get("template_id") or "autonomous-development.v1"
                stored_verification = current.get("verification_sha256") or None
                requested_template = template_id or stored_template
                requested_verification = verification_sha256 if verification_sha256 is not None else stored_verification
                if stored_template != requested_template or stored_verification != requested_verification:
                    raise WorkflowConflict(
                        "intake idempotency key is bound to a different flow or verification document"
                    )
                if template_id is None:
                    template_id = stored_template
                if verification_sha256 is None:
                    verification_sha256 = stored_verification
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO workflow_intake(
                      idempotency_key, board, task_id, repo_root, predecessor_task_id,
                      status, created_at, updated_at, template_id, verification_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        idempotency_key,
                        board,
                        task_id,
                        repo_root,
                        predecessor_task_id,
                        status,
                        now,
                        now,
                        template_id,
                        verification_sha256,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE workflow_intake
                    SET board = ?, task_id = ?, repo_root = ?, predecessor_task_id = ?,
                        status = ?, updated_at = ?, template_id = ?, verification_sha256 = ?
                    WHERE idempotency_key = ?
                    """,
                    (
                        board,
                        task_id,
                        repo_root,
                        predecessor_task_id,
                        status,
                        now,
                        template_id,
                        verification_sha256,
                        idempotency_key,
                    ),
                )
            row = conn.execute(
                "SELECT * FROM workflow_intake WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _row_dict(row)

    def get_intake(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_intake WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _row_dict(row)

    def list_manifests(self, board: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT manifest_json FROM workflow_manifests WHERE board = ?",
                (board,),
            ).fetchall()
        return [json.loads(row["manifest_json"]) for row in rows]

    def list_intake(self, board: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_intake WHERE board = ?",
                (board,),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def _migrate(self) -> None:
        with self._transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version INTEGER PRIMARY KEY,
                  applied_at INTEGER NOT NULL
                )
                """
            )
            row = conn.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
            current = int(row["version"])
            now = _now()
            for version, sql in enumerate(MIGRATIONS, start=1):
                if current >= version:
                    continue
                if version == 2:
                    _add_column_if_missing(conn, "workflow_intake", "template_id", "TEXT")
                    _add_column_if_missing(conn, "workflow_intake", "verification_sha256", "TEXT")
                else:
                    _exec_statements(conn, sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, now),
                )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            if conn.in_transaction:
                conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn
