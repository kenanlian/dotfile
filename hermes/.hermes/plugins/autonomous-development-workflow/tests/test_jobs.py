"""Job identity, chained artifacts, atomic writes, and Result consumption."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from plugin_imports import import_plugin

_jobs = import_plugin("controller.jobs")
_protocol = import_plugin("controller.protocol")
_store = import_plugin("controller.store")
_types = import_plugin("controller.types")

JOB_SCHEMA = _types.JOB_SCHEMA
RESULT_SCHEMA = _types.RESULT_SCHEMA
ARTIFACT_SCHEMA = _types.ARTIFACT_SCHEMA
WorkflowConflict = _types.WorkflowConflict
WorkflowProtocolError = _types.WorkflowProtocolError
WorkflowStatus = _types.WorkflowStatus
build_job = _jobs.build_job
consume_result = _jobs.consume_result
decide_verification = _jobs.decide_verification
input_sha_prefix = _jobs.input_sha_prefix
make_idempotency_key = _jobs.make_idempotency_key
make_job_id = _jobs.make_job_id
write_job_document = _jobs.write_job_document
parse_job_expectation = _protocol.parse_job_expectation
validate_completed_result = _protocol.validate_completed_result
canonical_dumps = _store.canonical_dumps

AGENTS = {
    "planner": {"model": "planner-model", "thinking": "high"},
    "plan-reviewer": {"model": "review-model", "thinking": "high"},
    "implementer": {"model": "impl-model", "thinking": "high"},
    "execute-reviewer": {"model": "review-model", "thinking": "medium"},
}


def _sha(text: str = "payload") -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _artifact(kind: str, directory: Path, body: str | None = None) -> dict:
    path = directory / f"{kind}.json"
    text = body if body is not None else json.dumps({"kind": kind})
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    schema = {
        "requirement": "autonomous-development.requirement.v1",
        "plan": "plan.v1",
        "plan-review": "plan-review.v1",
        "implementation": "implementation.v1",
    }[kind]
    return {"kind": kind, "path": str(path), "sha256": digest, "schema": schema}


def _workspace(repo: str = "/abs/repo", head: str = "a" * 40) -> dict:
    return {
        "repoRoot": repo,
        "branch": "main",
        "expectedHead": head,
        "requireCleanAtStart": True,
    }


class JobIdentityTests(unittest.TestCase):
    def test_job_id_is_sha256_prefix_of_idempotency_key(self) -> None:
        key = make_idempotency_key(
            board="project-board",
            task_id="t_abc",
            stage="plan",
            business_attempt=1,
            transport_retry=0,
            input_sha_prefix="deadbeefcafebabe",
        )
        self.assertEqual(
            key,
            "project-board:t_abc:plan:1:0:deadbeefcafebabe",
        )
        self.assertEqual(
            make_job_id(key),
            "job_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
        )

    def test_transport_retry_changes_job_id_and_not_business_attempt(self) -> None:
        prefix = "deadbeefcafebabe"
        first = make_idempotency_key(
            board="b",
            task_id="t",
            stage="plan",
            business_attempt=1,
            transport_retry=0,
            input_sha_prefix=prefix,
        )
        retry = make_idempotency_key(
            board="b",
            task_id="t",
            stage="plan",
            business_attempt=1,
            transport_retry=1,
            input_sha_prefix=prefix,
        )
        self.assertNotEqual(make_job_id(first), make_job_id(retry))
        self.assertIn(":1:0:", first)
        self.assertIn(":1:1:", retry)


class BuildJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-jobs-")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_plan_job_fills_stage_matrix_and_requirement_input(self) -> None:
        requirement = _artifact("requirement", self.root)
        job = build_job(
            board="project-board",
            task_id="t_abc",
            stage="plan",
            business_attempt=1,
            transport_retry=0,
            workspace=_workspace(),
            agents=AGENTS,
            inputs=(requirement,),
            session_id=None,
        )
        self.assertEqual(job["schema"], JOB_SCHEMA)
        self.assertEqual(job["stage"], "plan")
        self.assertEqual(job["attempt"], 1)
        self.assertEqual(job["agent"]["adapter"], "pi")
        self.assertEqual(job["agent"]["profile"], "planner")
        self.assertEqual(job["agent"]["model"], "planner-model")
        self.assertEqual(job["agent"]["thinking"], "high")
        self.assertIsNone(job["agent"]["sessionId"])
        self.assertEqual(job["permissions"]["mode"], "read-only")
        self.assertEqual(job["expectedOutput"], {"kind": "plan", "schema": "plan.v1"})
        self.assertEqual(job["verification"], [])
        self.assertEqual(job["limits"], {"timeoutSeconds": None})
        self.assertEqual(job["inputs"], [{"kind": "requirement", "path": requirement["path"], "sha256": requirement["sha256"]}])
        self.assertTrue(job["jobId"].startswith("job_"))
        self.assertIn("project-board:t_abc:plan:1:0:", job["idempotencyKey"])

    def test_implement_job_requires_deterministic_verification(self) -> None:
        plan = _artifact("plan", self.root)
        with self.assertRaisesRegex(
            WorkflowProtocolError, "implement jobs require at least one verification check"
        ):
            build_job(
                board="project-board",
                task_id="t_abc",
                stage="implement",
                business_attempt=1,
                transport_retry=0,
                workspace=_workspace(),
                agents=AGENTS,
                inputs=(plan,),
                session_id=None,
            )

    def test_reviewer_jobs_are_fresh_and_read_only(self) -> None:
        requirement = _artifact("requirement", self.root)
        plan = _artifact("plan", self.root)
        implementation = _artifact("implementation", self.root)
        plan_review = build_job(
            board="b",
            task_id="t",
            stage="plan_review",
            business_attempt=1,
            transport_retry=0,
            workspace=_workspace(),
            agents=AGENTS,
            inputs=(requirement, plan),
            session_id="sess_must_be_ignored",
        )
        self.assertEqual(plan_review["agent"]["profile"], "plan-reviewer")
        self.assertIsNone(plan_review["agent"]["sessionId"])
        self.assertEqual(plan_review["permissions"]["mode"], "read-only")
        execute_review = build_job(
            board="b",
            task_id="t",
            stage="execute_review",
            business_attempt=1,
            transport_retry=0,
            workspace={**_workspace(), "requireCleanAtStart": False},
            agents=AGENTS,
            inputs=(requirement, plan, implementation),
            session_id="sess_impl",
        )
        self.assertEqual(execute_review["agent"]["profile"], "execute-reviewer")
        self.assertIsNone(execute_review["agent"]["sessionId"])
        self.assertEqual(execute_review["permissions"]["mode"], "read-only")
        self.assertFalse(execute_review["workspace"]["requireCleanAtStart"])

    def test_plan_and_implement_rework_use_exact_saved_session(self) -> None:
        requirement = _artifact("requirement", self.root)
        plan = _artifact("plan", self.root)
        plan_job = build_job(
            board="b",
            task_id="t",
            stage="plan",
            business_attempt=2,
            transport_retry=0,
            workspace=_workspace(),
            agents=AGENTS,
            inputs=(requirement,),
            session_id="sess_plan",
        )
        self.assertEqual(plan_job["agent"]["sessionId"], "sess_plan")
        self.assertEqual(plan_job["attempt"], 2)
        impl = build_job(
            board="b",
            task_id="t",
            stage="implement",
            business_attempt=2,
            transport_retry=0,
            workspace={**_workspace(), "requireCleanAtStart": False},
            agents=AGENTS,
            inputs=(plan,),
            session_id="sess_impl",
            verification=(
                {
                    "id": "unit",
                    "argv": ["node", "--test"],
                    "cwd": "/abs/repo",
                    "timeoutSeconds": 30,
                    "expectedExitCode": 0,
                },
            ),
        )
        self.assertEqual(impl["agent"]["profile"], "implementer")
        self.assertEqual(impl["permissions"]["mode"], "write")
        self.assertEqual(impl["agent"]["sessionId"], "sess_impl")
        self.assertEqual(impl["verification"][0]["id"], "unit")

    def test_missing_chained_artifact_is_rejected(self) -> None:
        requirement = _artifact("requirement", self.root)
        with self.assertRaises(WorkflowProtocolError):
            build_job(
                board="b",
                task_id="t",
                stage="plan_review",
                business_attempt=1,
                transport_retry=0,
                workspace=_workspace(),
                agents=AGENTS,
                inputs=(requirement,),
                session_id=None,
            )

    def test_implement_rejects_verification_on_other_stages(self) -> None:
        requirement = _artifact("requirement", self.root)
        with self.assertRaises(WorkflowProtocolError):
            build_job(
                board="b",
                task_id="t",
                stage="plan",
                business_attempt=1,
                transport_retry=0,
                workspace=_workspace(),
                agents=AGENTS,
                inputs=(requirement,),
                session_id=None,
                verification=(
                    {
                        "id": "unit",
                        "argv": ["true"],
                        "cwd": "/abs/repo",
                        "timeoutSeconds": 1,
                        "expectedExitCode": 0,
                    },
                ),
            )

    def test_input_hash_mismatch_is_rejected(self) -> None:
        requirement = _artifact("requirement", self.root)
        with self.assertRaises(WorkflowProtocolError):
            build_job(
                board="b",
                task_id="t",
                stage="plan",
                business_attempt=1,
                transport_retry=0,
                workspace=_workspace(),
                agents=AGENTS,
                inputs=({**requirement, "sha256": _sha("other")},),
                session_id=None,
            )


class WriteJobDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-jobwrite-")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_atomic_write_reuses_identical_document_and_conflicts_on_drift(self) -> None:
        requirement = _artifact("requirement", self.root)
        job = build_job(
            board="b",
            task_id="t",
            stage="plan",
            business_attempt=1,
            transport_retry=0,
            workspace=_workspace(),
            agents=AGENTS,
            inputs=(requirement,),
            session_id=None,
        )
        run_dir = self.root / "run"
        first = write_job_document(job, run_dir)
        second = write_job_document(job, run_dir)
        self.assertEqual(first["job_sha256"], second["job_sha256"])
        self.assertEqual(first["job_path"], str(run_dir / "job.json"))
        self.assertTrue(Path(first["job_path"]).is_file())
        drifted = dict(job)
        drifted["agent"] = {**job["agent"], "model": "other-model"}
        with self.assertRaises(WorkflowConflict):
            write_job_document(drifted, run_dir)

    def test_write_job_document_pairs_job_json_with_job_sha256(self) -> None:
        requirement = _artifact("requirement", self.root)
        job = build_job(
            board="b",
            task_id="t",
            stage="plan",
            business_attempt=1,
            transport_retry=0,
            workspace=_workspace(),
            agents=AGENTS,
            inputs=(requirement,),
            session_id=None,
        )
        run_dir = self.root / "run"
        written = write_job_document(job, run_dir)
        job_path = Path(written["job_path"])
        hash_path = run_dir / "job.sha256"
        self.assertTrue(job_path.is_file())
        self.assertTrue(hash_path.is_file())
        digest = _protocol.job_document_sha256(job)
        self.assertEqual(written["job_sha256"], digest)
        self.assertEqual(hash_path.read_text(encoding="utf-8"), digest + "\n")
        hash_path.unlink()
        repaired = write_job_document(job, run_dir)
        self.assertEqual(repaired["job_sha256"], digest)
        self.assertEqual(hash_path.read_text(encoding="utf-8"), digest + "\n")

    def test_plugin_prepared_out_dir_passes_real_harness_ownership(self) -> None:
        import subprocess

        requirement = _artifact("requirement", self.root)
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True, capture_output=True)
        (repo / "README").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
        job = build_job(
            board="b",
            task_id="t",
            stage="plan",
            business_attempt=1,
            transport_retry=0,
            workspace=_workspace(repo=str(repo.resolve()), head="a" * 40),
            agents=AGENTS,
            inputs=(requirement,),
            session_id=None,
        )
        run_dir = self.root / "out"
        write_job_document(job, run_dir)
        harness = (
            Path(__file__).resolve().parents[3]
            / "skills"
            / "autonomous-ai-agents"
            / "coding-agent-harness"
            / "scripts"
            / "harness.mjs"
        )
        completed = subprocess.run(
            ["node", str(harness), "run", "--job", str(run_dir / "job.json"), "--out-dir", str(run_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        combined = (completed.stdout or "") + (completed.stderr or "")
        self.assertNotIn("incomplete stored Job ownership evidence", combined)
        self.assertTrue((run_dir / "job.sha256").is_file())


class ConsumeResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-consume-")
        self.root = Path(self._tmp.name)
        requirement = _artifact("requirement", self.root)
        self.job = build_job(
            board="project-board",
            task_id="t_abc",
            stage="plan",
            business_attempt=1,
            transport_retry=0,
            workspace=_workspace(),
            agents=AGENTS,
            inputs=(requirement,),
            session_id=None,
        )
        self.job_sha = write_job_document(self.job, self.root / "run")["job_sha256"]
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text('{"schema":"plan.v1","title":"ok"}', encoding="utf-8")
        self.plan_sha = hashlib.sha256(self.plan_path.read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _result(self, **overrides) -> dict:
        data = {
            "schema": RESULT_SCHEMA,
            "jobId": self.job["jobId"],
            "idempotencyKey": self.job["idempotencyKey"],
            "jobSha256": self.job_sha,
            "taskId": "t_abc",
            "stage": "plan",
            "status": "completed",
            "adapter": "pi",
            "sessionId": "sess_plan",
            "startedAt": "2026-09-14T00:00:00Z",
            "finishedAt": "2026-09-14T00:01:00Z",
            "structuredOutput": {"kind": "plan", "payload": {"schema": "plan.v1", "title": "ok"}},
            "artifacts": [
                {
                    "kind": "plan",
                    "path": str(self.plan_path),
                    "sha256": self.plan_sha,
                    "schema": ARTIFACT_SCHEMA,
                    "canonical": True,
                }
            ],
            "touchedFiles": [],
            "checks": [],
            "usage": {},
            "workspace": {
                "repoRoot": "/abs/repo",
                "branchBefore": "main",
                "branchAfter": "main",
                "headBefore": "a" * 40,
                "headAfter": "a" * 40,
                "snapshotBeforeSha256": "c" * 64,
                "snapshotAfterSha256": "c" * 64,
            },
            "error": None,
            "paths": {
                "events": "/abs/events.jsonl",
                "stderr": "/abs/stderr.log",
                "final": "/abs/final.txt",
                "adapterRuns": [],
            },
        }
        data.update(overrides)
        return data

    def test_completed_plan_advances_to_plan_reviewing_and_keeps_session(self) -> None:
        outcome = consume_result(self.job, self._result())
        self.assertEqual(outcome.kind, "consumed")
        self.assertEqual(outcome.next_status, WorkflowStatus.PLAN_REVIEWING)
        self.assertEqual(outcome.session_id, "sess_plan")
        self.assertEqual(len(outcome.artifacts), 1)
        self.assertEqual(outcome.artifacts[0].kind, "plan")

    def test_same_result_reconsume_is_noop(self) -> None:
        result = self._result()
        first = consume_result(self.job, result)
        second = consume_result(self.job, result, previously_consumed_sha256=first.result_sha256)
        self.assertEqual(second.kind, "noop")
        self.assertEqual(second.next_status, None)

    def test_different_result_for_same_job_conflicts(self) -> None:
        first = consume_result(self.job, self._result())
        other = self._result(sessionId="sess_other")
        with self.assertRaises(WorkflowConflict):
            consume_result(self.job, other, previously_consumed_sha256=first.result_sha256)

    def test_invalid_completed_result_is_protocol_failure(self) -> None:
        outcome = consume_result(
            self.job,
            self._result(
                artifacts=[
                    {
                        "kind": "plan",
                        "path": str(self.plan_path),
                        "sha256": self.plan_sha,
                        "schema": "plan.v1",
                        "canonical": False,
                    }
                ]
            ),
        )
        self.assertEqual(outcome.kind, "protocol_failure")
        self.assertIsNone(outcome.next_status)

    def test_payload_schema_on_canonical_artifact_is_protocol_failure(self) -> None:
        outcome = consume_result(
            self.job,
            self._result(
                artifacts=[
                    {
                        "kind": "plan",
                        "path": str(self.plan_path),
                        "sha256": self.plan_sha,
                        "schema": "plan.v1",
                        "canonical": True,
                    }
                ]
            ),
        )
        self.assertEqual(outcome.kind, "protocol_failure")
        self.assertIsNone(outcome.next_status)

    def test_transport_failure_does_not_advance_stage(self) -> None:
        outcome = consume_result(
            self.job,
            self._result(
                status="failed",
                sessionId=None,
                structuredOutput=None,
                artifacts=[],
                error={"kind": "adapter_failed", "message": "pi died", "details": {}},
            ),
        )
        self.assertEqual(outcome.kind, "transport_failure")
        self.assertIsNone(outcome.next_status)

    def test_plan_review_verdicts(self) -> None:
        requirement = _artifact("requirement", self.root)
        plan = _artifact("plan", self.root)
        review_job = build_job(
            board="project-board",
            task_id="t_abc",
            stage="plan_review",
            business_attempt=1,
            transport_retry=0,
            workspace=_workspace(),
            agents=AGENTS,
            inputs=(requirement, plan),
            session_id=None,
        )
        review_sha = write_job_document(review_job, self.root / "review-run")["job_sha256"]
        artifact_path = self.root / "plan-review.json"
        payload = {"schema": "plan-review.v1", "verdict": "approved", "summary": "ok", "findings": []}
        artifact_path.write_text(json.dumps(payload), encoding="utf-8")
        result = {
            "schema": RESULT_SCHEMA,
            "jobId": review_job["jobId"],
            "idempotencyKey": review_job["idempotencyKey"],
            "jobSha256": review_sha,
            "taskId": "t_abc",
            "stage": "plan_review",
            "status": "completed",
            "adapter": "pi",
            "sessionId": "sess_review",
            "startedAt": "2026-09-14T00:00:00Z",
            "finishedAt": "2026-09-14T00:01:00Z",
            "structuredOutput": {"kind": "plan-review", "payload": payload},
            "artifacts": [
                {
                    "kind": "plan-review",
                    "path": str(artifact_path),
                    "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                    "schema": ARTIFACT_SCHEMA,
                    "canonical": True,
                }
            ],
            "touchedFiles": [],
            "checks": [],
            "usage": {},
            "workspace": {
                "repoRoot": "/abs/repo",
                "branchBefore": "main",
                "branchAfter": "main",
                "headBefore": "a" * 40,
                "headAfter": "a" * 40,
                "snapshotBeforeSha256": "c" * 64,
                "snapshotAfterSha256": "c" * 64,
            },
            "error": None,
            "paths": {
                "events": "/abs/events.jsonl",
                "stderr": "/abs/stderr.log",
                "final": "/abs/final.txt",
                "adapterRuns": [],
            },
        }
        approved = consume_result(review_job, result)
        self.assertEqual(approved.next_status, WorkflowStatus.IMPLEMENTING)
        self.assertEqual(approved.review_verdict, "approved")

        payload["verdict"] = "request_changes"
        artifact_path.write_text(json.dumps(payload), encoding="utf-8")
        result["artifacts"][0]["sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        result["structuredOutput"] = {"kind": "plan-review", "payload": payload}
        result["jobSha256"] = review_sha
        requested = consume_result(review_job, result)
        self.assertEqual(requested.next_status, WorkflowStatus.PLAN_REWORK)
        self.assertEqual(requested.review_verdict, "request_changes")

    def test_implement_completed_goes_to_verifying(self) -> None:
        plan = _artifact("plan", self.root)
        job = build_job(
            board="project-board",
            task_id="t_abc",
            stage="implement",
            business_attempt=1,
            transport_retry=0,
            workspace=_workspace(),
            agents=AGENTS,
            inputs=(plan,),
            session_id=None,
            verification=(
                {
                    "id": "unit",
                    "argv": ["node", "--test"],
                    "cwd": "/abs/repo",
                    "timeoutSeconds": 30,
                    "expectedExitCode": 0,
                },
            ),
        )
        job_sha = write_job_document(job, self.root / "impl-run")["job_sha256"]
        impl_path = self.root / "implementation.json"
        impl_path.write_text('{"schema":"implementation.v1","outcome":"completed"}', encoding="utf-8")
        result = {
            "schema": RESULT_SCHEMA,
            "jobId": job["jobId"],
            "idempotencyKey": job["idempotencyKey"],
            "jobSha256": job_sha,
            "taskId": "t_abc",
            "stage": "implement",
            "status": "completed",
            "adapter": "pi",
            "sessionId": "sess_impl",
            "startedAt": "2026-09-14T00:00:00Z",
            "finishedAt": "2026-09-14T00:01:00Z",
            "structuredOutput": {
                "kind": "implementation",
                "payload": {"schema": "implementation.v1", "outcome": "completed"},
            },
            "artifacts": [
                {
                    "kind": "implementation",
                    "path": str(impl_path),
                    "sha256": hashlib.sha256(impl_path.read_bytes()).hexdigest(),
                    "schema": ARTIFACT_SCHEMA,
                    "canonical": True,
                }
            ],
            "touchedFiles": [],
            "checks": [{"id": "unit", "status": "passed"}],
            "usage": {},
            "workspace": {
                "repoRoot": "/abs/repo",
                "branchBefore": "main",
                "branchAfter": "main",
                "headBefore": "a" * 40,
                "headAfter": "a" * 40,
                "snapshotBeforeSha256": "c" * 64,
                "snapshotAfterSha256": "c" * 64,
            },
            "error": None,
            "paths": {
                "events": "/abs/events.jsonl",
                "stderr": "/abs/stderr.log",
                "final": "/abs/final.txt",
                "adapterRuns": [],
            },
        }
        outcome = consume_result(job, result)
        self.assertEqual(outcome.next_status, WorkflowStatus.VERIFYING)
        self.assertEqual(outcome.session_id, "sess_impl")

    def test_execute_review_approved_goes_to_product_acceptance(self) -> None:
        requirement = _artifact("requirement", self.root)
        plan = _artifact("plan", self.root)
        implementation = _artifact("implementation", self.root)
        job = build_job(
            board="project-board",
            task_id="t_abc",
            stage="execute_review",
            business_attempt=1,
            transport_retry=0,
            workspace={**_workspace(), "requireCleanAtStart": False},
            agents=AGENTS,
            inputs=(requirement, plan, implementation),
            session_id=None,
        )
        job_sha = write_job_document(job, self.root / "exec-run")["job_sha256"]
        payload = {
            "schema": "execute-review.v1",
            "verdict": "approved",
            "summary": "ok",
            "findings": [],
            "acceptanceCoverage": [],
        }
        path = self.root / "execute-review.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result = {
            "schema": RESULT_SCHEMA,
            "jobId": job["jobId"],
            "idempotencyKey": job["idempotencyKey"],
            "jobSha256": job_sha,
            "taskId": "t_abc",
            "stage": "execute_review",
            "status": "completed",
            "adapter": "pi",
            "sessionId": "sess_exec",
            "startedAt": "2026-09-14T00:00:00Z",
            "finishedAt": "2026-09-14T00:01:00Z",
            "structuredOutput": {"kind": "execute-review", "payload": payload},
            "artifacts": [
                {
                    "kind": "execute-review",
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "schema": ARTIFACT_SCHEMA,
                    "canonical": True,
                }
            ],
            "touchedFiles": [],
            "checks": [],
            "usage": {},
            "workspace": {
                "repoRoot": "/abs/repo",
                "branchBefore": "main",
                "branchAfter": "main",
                "headBefore": "a" * 40,
                "headAfter": "a" * 40,
                "snapshotBeforeSha256": "c" * 64,
                "snapshotAfterSha256": "c" * 64,
            },
            "error": None,
            "paths": {
                "events": "/abs/events.jsonl",
                "stderr": "/abs/stderr.log",
                "final": "/abs/final.txt",
                "adapterRuns": [],
            },
        }
        outcome = consume_result(job, result)
        self.assertEqual(outcome.next_status, WorkflowStatus.PRODUCT_ACCEPTANCE)
        payload["verdict"] = "request_changes"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result["artifacts"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result["structuredOutput"] = {"kind": "execute-review", "payload": payload}
        rework = consume_result(job, result)
        self.assertEqual(rework.next_status, WorkflowStatus.IMPLEMENT_REWORK)


class VerifyDecisionTests(unittest.TestCase):
    def test_verification_is_derived_only_from_checks(self) -> None:
        self.assertEqual(decide_verification({"checks": []}), "passed")
        self.assertEqual(
            decide_verification({"checks": [{"id": "a", "status": "passed"}]}),
            "passed",
        )
        self.assertEqual(
            decide_verification(
                {"checks": [{"id": "a", "status": "passed"}, {"id": "b", "status": "failed"}]}
            ),
            "failed",
        )
        self.assertEqual(
            decide_verification({"checks": [{"id": "a", "status": "timed_out"}]}),
            "failed",
        )


if __name__ == "__main__":
    unittest.main()
