"""Workflow Store, CAS, Artifact ledger, and repo lease (stdlib unittest)."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from plugin_imports import import_plugin

_store = import_plugin("controller.store")
_templates = import_plugin("controller.templates")
_types = import_plugin("controller.types")

WorkflowConflict = _types.WorkflowConflict
WorkflowProtocolError = _types.WorkflowProtocolError
WORKFLOW_SCHEMA = _types.WORKFLOW_SCHEMA
WORKFLOW_TEMPLATE_ID = _types.WORKFLOW_TEMPLATE_ID
DIRECT_TEMPLATE_ID = _templates.DIRECT_TEMPLATE_ID
WorkflowStore = _store.WorkflowStore


def _sha(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _manifest(**overrides):
    data = {
        "schema": WORKFLOW_SCHEMA,
        "templateId": WORKFLOW_TEMPLATE_ID,
        "board": "project-board",
        "taskId": "t_abc",
        "repoRoot": "/abs/repo",
        "workflowStatus": "queued",
        "revision": 1,
        "stageAttempt": 1,
        "activeJobId": None,
        "plannerSessionId": None,
        "implementerSessionId": None,
        "planReworkCount": 0,
        "implementReworkCount": 0,
        "runFailureCounts": {},
        "baseline": {"branch": "main", "head": "a" * 40},
        "candidateFingerprint": None,
        "approvedPlan": None,
        "lastConsumedJobId": None,
        "pendingLifecycle": None,
        "resumeStatus": None,
    }
    data.update(overrides)
    return data


def _job(**overrides):
    data = {
        "job_id": "job_plan1",
        "board": "project-board",
        "task_id": "t_abc",
        "stage": "plan",
        "business_attempt": 1,
        "transport_retry": 0,
        "idempotency_key": "project-board:t_abc:plan:1:0:deadbeef",
        "job_path": "/abs/jobs/job_plan1/job.json",
        "run_dir": "/abs/jobs/job_plan1",
        "job_sha256": _sha("job"),
        "harness_pid": None,
        "process_identity": None,
        "status": "pending",
        "result_path": None,
        "started_at": None,
        "finished_at": None,
        "consumed_at": None,
    }
    data.update(overrides)
    return data


class WorkflowStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-store-")
        self.state_root = Path(self._tmp.name) / "state"
        self.state_root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _store(self, root: Path | None = None) -> WorkflowStore:
        return WorkflowStore(str(root or self.state_root))

    def test_relative_and_empty_state_root_are_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            WorkflowStore("")
        with self.assertRaises(WorkflowProtocolError):
            WorkflowStore("relative/state")
        with self.assertRaises(WorkflowProtocolError):
            WorkflowStore("./state")
        with self.assertRaises(WorkflowProtocolError):
            WorkflowStore(None)  # type: ignore[arg-type]

    def test_state_root_is_not_derived_from_hermes_home(self) -> None:
        source = Path(_store.__file__).read_text(encoding="utf-8")
        self.assertNotIn("HERMES_HOME", source)
        self.assertNotIn("~/.hermes", source)
        self.assertNotIn("plugin_data_dir", source)
        self.assertNotIn("plugin_db", source)
        previous = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = "/tmp/should-not-be-used"
        try:
            store = self._store()
            self.assertEqual(store.state_root, self.state_root.resolve())
            self.assertTrue(str(store.db_path).startswith(str(self.state_root.resolve())))
            self.assertNotIn("/tmp/should-not-be-used", str(store.db_path))
        finally:
            if previous is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous

    def test_symlink_state_roots_share_the_same_realpath_db(self) -> None:
        real = Path(self._tmp.name) / "real-state"
        real.mkdir()
        alias = Path(self._tmp.name) / "alias-state"
        alias.symlink_to(real)
        first = WorkflowStore(str(alias))
        second = WorkflowStore(str(real))
        self.assertEqual(first.db_path.resolve(), second.db_path.resolve())
        first.put_manifest(_manifest())
        loaded = second.get_manifest("project-board", "t_abc")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["taskId"], "t_abc")

    def test_fresh_db_creates_required_tables(self) -> None:
        store = self._store()
        tables = store.table_names()
        self.assertEqual(
            tables,
            {
                "schema_migrations",
                "workflow_manifests",
                "workflow_jobs",
                "workflow_artifacts",
                "workflow_repo_leases",
                "workflow_intake",
            },
        )
        self.assertNotIn("workflow_lifecycle", tables)
        self.assertEqual(store.schema_version(), _store.SCHEMA_VERSION)

    def test_reopen_and_migration_preserve_manifest_job_and_artifact(self) -> None:
        artifact_dir = Path(self._tmp.name) / "arts"
        artifact_dir.mkdir()
        artifact_path = artifact_dir / "requirement-v1.json"
        payload = '{"schema":"requirement.v1","text":"build it"}'
        artifact_path.write_text(payload, encoding="utf-8")
        digest = _sha(payload)

        store = self._store()
        store.put_manifest(_manifest(pendingLifecycle={"tool": "kanban_request_review"}))
        store.put_job(_job())
        store.register_artifact(
            board="project-board",
            task_id="t_abc",
            job_id="job_plan1",
            kind="requirement",
            version=1,
            path=str(artifact_path),
            sha256=digest,
        )
        db_path = store.db_path
        del store

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DELETE FROM schema_migrations")
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 1)",
                (0,),
            )
            conn.commit()
        finally:
            conn.close()

        reopened = self._store()
        self.assertEqual(reopened.schema_version(), _store.SCHEMA_VERSION)
        manifest = reopened.get_manifest("project-board", "t_abc")
        self.assertEqual(manifest["pendingLifecycle"]["tool"], "kanban_request_review")
        self.assertEqual(reopened.get_job("job_plan1")["idempotency_key"], _job()["idempotency_key"])
        artifact = reopened.get_artifact("project-board", "t_abc", "requirement", 1)
        self.assertEqual(artifact["sha256"], digest)

    def test_migration_sql_does_not_drop_recovery_tables(self) -> None:
        joined = "\n".join(_store.MIGRATIONS)
        upper = joined.upper()
        for table in (
            "WORKFLOW_MANIFESTS",
            "WORKFLOW_JOBS",
            "WORKFLOW_ARTIFACTS",
            "WORKFLOW_REPO_LEASES",
            "WORKFLOW_INTAKE",
        ):
            self.assertNotIn(f"DROP TABLE {table}", upper)
            self.assertNotIn(f"DROP TABLE IF EXISTS {table}", upper)

    def test_canonical_json_sorts_keys_and_preserves_unicode(self) -> None:
        store = self._store()
        payload = _manifest(approvedPlan="计划：先写测试")
        store.put_manifest(payload)
        raw = store.get_manifest_row("project-board", "t_abc")
        expected = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        self.assertEqual(raw["manifest_json"], expected)
        self.assertEqual(raw["revision"], payload["revision"])
        loaded = json.loads(raw["manifest_json"])
        self.assertEqual(loaded["revision"], raw["revision"])
        self.assertIn("计划", raw["manifest_json"])
        self.assertNotIn("\\u", raw["manifest_json"])

    def test_cas_rejects_stale_revision_and_revision_mismatch(self) -> None:
        store = self._store()
        store.put_manifest(_manifest())
        with self.assertRaises(WorkflowConflict):
            store.put_manifest(_manifest(revision=1, workflowStatus="planning"))
        with self.assertRaises(WorkflowProtocolError):
            store.cas_update_manifest(
                "project-board",
                "t_abc",
                expected_revision=1,
                manifest=_manifest(revision=1, workflowStatus="planning"),
            )
        store.cas_update_manifest(
            "project-board",
            "t_abc",
            expected_revision=1,
            manifest=_manifest(revision=2, workflowStatus="planning"),
        )
        with self.assertRaises(WorkflowConflict):
            store.cas_update_manifest(
                "project-board",
                "t_abc",
                expected_revision=1,
                manifest=_manifest(revision=2, workflowStatus="blocked"),
            )
        loaded = store.get_manifest("project-board", "t_abc")
        self.assertEqual(loaded["revision"], 2)
        self.assertEqual(loaded["workflowStatus"], "planning")

    def test_concurrent_cas_allows_only_one_success(self) -> None:
        store = self._store()
        store.put_manifest(_manifest())
        barrier = threading.Barrier(2)
        results: list[str] = []
        lock = threading.Lock()

        def attempt(status: str) -> None:
            local = self._store()
            barrier.wait()
            try:
                local.cas_update_manifest(
                    "project-board",
                    "t_abc",
                    expected_revision=1,
                    manifest=_manifest(revision=2, workflowStatus=status),
                )
                outcome = "ok"
            except WorkflowConflict:
                outcome = "conflict"
            with lock:
                results.append(outcome)

        threads = [
            threading.Thread(target=attempt, args=("planning",)),
            threading.Thread(target=attempt, args=("planning",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), ["conflict", "ok"])
        loaded = store.get_manifest("project-board", "t_abc")
        self.assertEqual(loaded["revision"], 2)
        self.assertEqual(loaded["workflowStatus"], "planning")

    def test_artifact_rejects_missing_relative_hash_mismatch_and_overwrite(self) -> None:
        store = self._store()
        store.put_manifest(_manifest())
        missing = Path(self._tmp.name) / "missing.json"
        with self.assertRaises(WorkflowProtocolError):
            store.register_artifact(
                board="project-board",
                task_id="t_abc",
                job_id="job_plan1",
                kind="requirement",
                version=1,
                path=str(missing),
                sha256=_sha("x"),
            )
        with self.assertRaises(WorkflowProtocolError):
            store.register_artifact(
                board="project-board",
                task_id="t_abc",
                job_id="job_plan1",
                kind="requirement",
                version=1,
                path="requirement-v1.json",
                sha256=_sha("x"),
            )
        artifact_path = Path(self._tmp.name) / "requirement-v1.json"
        artifact_path.write_text("hello", encoding="utf-8")
        with self.assertRaises(WorkflowProtocolError):
            store.register_artifact(
                board="project-board",
                task_id="t_abc",
                job_id="job_plan1",
                kind="requirement",
                version=1,
                path=str(artifact_path),
                sha256=_sha("other"),
            )
        digest = _sha("hello")
        store.register_artifact(
            board="project-board",
            task_id="t_abc",
            job_id="job_plan1",
            kind="requirement",
            version=1,
            path=str(artifact_path),
            sha256=digest,
        )
        store.register_artifact(
            board="project-board",
            task_id="t_abc",
            job_id="job_plan1",
            kind="requirement",
            version=1,
            path=str(artifact_path),
            sha256=digest,
        )
        artifact_path.write_text("changed", encoding="utf-8")
        with self.assertRaises(WorkflowConflict):
            store.register_artifact(
                board="project-board",
                task_id="t_abc",
                job_id="job_plan1",
                kind="requirement",
                version=1,
                path=str(artifact_path),
                sha256=_sha("changed"),
            )
        other = Path(self._tmp.name) / "other.json"
        other.write_text("hello", encoding="utf-8")
        with self.assertRaises(WorkflowConflict):
            store.register_artifact(
                board="project-board",
                task_id="t_abc",
                job_id="job_plan1",
                kind="requirement",
                version=1,
                path=str(other),
                sha256=digest,
            )
        stored = store.get_artifact("project-board", "t_abc", "requirement", 1)
        self.assertEqual(stored["sha256"], digest)
        self.assertEqual(stored["path"], str(artifact_path))

    def test_repo_lease_is_unique_by_realpath_and_reentrant_for_same_task(self) -> None:
        real_repo = Path(self._tmp.name) / "repo"
        real_repo.mkdir()
        alias = Path(self._tmp.name) / "repo-alias"
        alias.symlink_to(real_repo)
        store = self._store()
        first = store.acquire_repo_lease(
            str(alias), board="project-board", task_id="t_abc", fencing_token="fence-1"
        )
        again = store.acquire_repo_lease(
            str(real_repo), board="project-board", task_id="t_abc", fencing_token="fence-2"
        )
        self.assertEqual(first["repo_root"], str(real_repo.resolve()))
        self.assertEqual(again["fencing_token"], "fence-1")
        with self.assertRaises(WorkflowConflict):
            store.acquire_repo_lease(
                str(real_repo), board="project-board", task_id="t_other", fencing_token="fence-x"
            )
        for reason in ("review", "rework", "blocked"):
            with self.assertRaises(WorkflowProtocolError):
                store.release_repo_lease(str(real_repo), board="project-board", task_id="t_abc", reason=reason)
        lease = store.get_repo_lease(str(real_repo))
        self.assertIsNone(lease["released_at"])
        store.release_repo_lease(
            str(real_repo), board="project-board", task_id="t_abc", reason="completed"
        )
        released = store.get_repo_lease(str(real_repo))
        self.assertIsNotNone(released["released_at"])
        other = store.acquire_repo_lease(
            str(real_repo), board="project-board", task_id="t_other", fencing_token="fence-3"
        )
        self.assertEqual(other["task_id"], "t_other")
        store.release_repo_lease(
            str(real_repo), board="project-board", task_id="t_other", reason="archived"
        )
        abandoned = store.acquire_repo_lease(
            str(real_repo), board="project-board", task_id="t_abc", fencing_token="fence-4"
        )
        store.release_repo_lease(
            str(real_repo), board="project-board", task_id="t_abc", reason="abandon"
        )
        self.assertEqual(abandoned["fencing_token"], "fence-4")

    def test_write_transactions_do_not_start_harness_git_or_kanban(self) -> None:
        source = Path(_store.__file__).read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("Popen", source)
        self.assertNotRegex(source, r"\bgit\b")
        self.assertNotIn("dispatch_tool", source)
        self.assertNotIn("kanban_", source)
        store = self._store()
        calls: list[str] = []

        def _forbid(*_args, **_kwargs):
            calls.append("side-effect")
            raise AssertionError("store writes must not start harness, git, or kanban")

        import subprocess

        original_run = subprocess.run
        original_popen = subprocess.Popen
        subprocess.run = _forbid  # type: ignore[assignment]
        subprocess.Popen = _forbid  # type: ignore[assignment]
        try:
            store.put_manifest(_manifest())
            store.put_job(_job())
            path = Path(self._tmp.name) / "a.json"
            path.write_text("{}", encoding="utf-8")
            store.register_artifact(
                board="project-board",
                task_id="t_abc",
                job_id="job_plan1",
                kind="plan",
                version=1,
                path=str(path),
                sha256=_sha("{}"),
            )
            repo = Path(self._tmp.name) / "leased"
            repo.mkdir()
            store.acquire_repo_lease(str(repo), board="project-board", task_id="t_abc", fencing_token="f")
            store.put_intake(
                idempotency_key="k1",
                board="project-board",
                task_id="t_abc",
                repo_root="/abs/repo",
                predecessor_task_id=None,
                status="started",
            )
        finally:
            subprocess.run = original_run
            subprocess.Popen = original_popen
        self.assertEqual(calls, [])

    def test_pending_lifecycle_is_stored_on_manifest_not_a_table(self) -> None:
        store = self._store()
        store.put_manifest(
            _manifest(pendingLifecycle={"tool": "kanban_complete", "runId": "run_1"})
        )
        loaded = store.get_manifest("project-board", "t_abc")
        self.assertEqual(loaded["pendingLifecycle"]["runId"], "run_1")
        self.assertNotIn("workflow_lifecycle", store.table_names())
        self.assertNotIn("workflow_sagas", store.table_names())

    def test_direct_queued_to_completed_is_rejected(self) -> None:
        store = self._store()
        store.put_manifest(_manifest(templateId=DIRECT_TEMPLATE_ID))
        with self.assertRaises(WorkflowProtocolError):
            store.cas_update_manifest(
                "project-board",
                "t_abc",
                expected_revision=1,
                manifest=_manifest(
                    templateId=DIRECT_TEMPLATE_ID,
                    revision=2,
                    workflowStatus="completed",
                ),
            )
        loaded = store.get_manifest("project-board", "t_abc")
        self.assertEqual(loaded["workflowStatus"], "queued")
        self.assertEqual(loaded["revision"], 1)

    def test_direct_forbidden_plan_job_is_rejected(self) -> None:
        store = self._store()
        store.put_manifest(_manifest(templateId=DIRECT_TEMPLATE_ID))
        with self.assertRaises(WorkflowProtocolError):
            store.put_job(_job(stage="plan"))
        self.assertIsNone(store.get_job("job_plan1"))
        with self.assertRaises(WorkflowProtocolError):
            store.put_job(_job(board="missing-board", task_id="t_missing", stage="direct_implement"))

    def test_template_schema_and_repo_mutation_is_rejected(self) -> None:
        store = self._store()
        store.put_manifest(_manifest())
        with self.assertRaises(WorkflowProtocolError):
            store.cas_update_manifest(
                "project-board",
                "t_abc",
                expected_revision=1,
                manifest=_manifest(revision=2, templateId=DIRECT_TEMPLATE_ID),
            )
        with self.assertRaises(WorkflowProtocolError):
            store.cas_update_manifest(
                "project-board",
                "t_abc",
                expected_revision=1,
                manifest=_manifest(revision=2, schema="other.workflow.v1", workflowStatus="planning"),
            )
        with self.assertRaises(WorkflowProtocolError):
            store.cas_update_manifest(
                "project-board",
                "t_abc",
                expected_revision=1,
                manifest=_manifest(revision=2, repoRoot="/abs/other", workflowStatus="planning"),
            )
        loaded = store.get_manifest("project-board", "t_abc")
        self.assertEqual(loaded["templateId"], WORKFLOW_TEMPLATE_ID)
        self.assertEqual(loaded["schema"], WORKFLOW_SCHEMA)
        self.assertEqual(loaded["repoRoot"], "/abs/repo")
        self.assertEqual(loaded["revision"], 1)

    def test_same_status_checkpoint_is_allowed(self) -> None:
        store = self._store()
        store.put_manifest(_manifest())
        store.put_job(_job())
        stored = store.checkpoint(
            board="project-board",
            task_id="t_abc",
            expected_revision=1,
            manifest=_manifest(revision=2, workflowStatus="queued", activeJobId="job_plan1"),
            job_patch={"job_id": "job_plan1", "status": "running"},
        )
        self.assertEqual(stored["workflowStatus"], "queued")
        self.assertEqual(stored["activeJobId"], "job_plan1")
        self.assertEqual(store.get_job("job_plan1")["status"], "running")

    def test_legal_direct_and_full_transitions_are_allowed(self) -> None:
        store = self._store()
        store.put_manifest(_manifest())
        store.cas_update_manifest(
            "project-board",
            "t_abc",
            expected_revision=1,
            manifest=_manifest(revision=2, workflowStatus="planning"),
        )
        self.assertEqual(store.get_manifest("project-board", "t_abc")["workflowStatus"], "planning")
        direct_root = Path(self._tmp.name) / "direct-state"
        direct_root.mkdir()
        direct = self._store(direct_root)
        direct.put_manifest(_manifest(templateId=DIRECT_TEMPLATE_ID))
        direct.cas_update_manifest(
            "project-board",
            "t_abc",
            expected_revision=1,
            manifest=_manifest(
                templateId=DIRECT_TEMPLATE_ID,
                revision=2,
                workflowStatus="implementing",
            ),
        )
        self.assertEqual(direct.get_manifest("project-board", "t_abc")["workflowStatus"], "implementing")
        direct.put_job(_job(stage="direct_implement", job_id="job_direct1", idempotency_key="k-direct"))
        self.assertEqual(direct.get_job("job_direct1")["stage"], "direct_implement")


if __name__ == "__main__":
    unittest.main()
