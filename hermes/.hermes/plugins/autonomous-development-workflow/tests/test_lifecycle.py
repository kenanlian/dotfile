"""Lifecycle saga: pendingLifecycle fencing, read-back, and Result-before-start."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from plugin_imports import import_plugin

_jobs = import_plugin("controller.jobs")
_lifecycle = import_plugin("controller.lifecycle")
_protocol = import_plugin("controller.protocol")
_service = import_plugin("controller.service")
_store = import_plugin("controller.store")
_types = import_plugin("controller.types")

PluginConfig = _types.PluginConfig
ARTIFACT_SCHEMA = _types.ARTIFACT_SCHEMA
RESULT_SCHEMA = _types.RESULT_SCHEMA
WORKFLOW_SCHEMA = _types.WORKFLOW_SCHEMA
WORKFLOW_TEMPLATE_ID = _types.WORKFLOW_TEMPLATE_ID
WorkflowProtocolError = _types.WorkflowProtocolError
WorkflowStore = _store.WorkflowStore
WorkflowController = _service.WorkflowController
apply_pending_lifecycle = _lifecycle.apply_pending_lifecycle
make_pending_lifecycle = _lifecycle.make_pending_lifecycle
build_job = _jobs.build_job
write_job_document = _jobs.write_job_document
job_document_sha256 = _protocol.job_document_sha256

AGENTS = {
    "planner": {"model": "planner-model", "thinking": "high"},
    "plan-reviewer": {"model": "review-model", "thinking": "high"},
    "implementer": {"model": "impl-model", "thinking": "high"},
    "execute-reviewer": {"model": "review-model", "thinking": "medium"},
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_canonical_plan(path: Path, *, job: dict[str, Any], job_sha256: str, session_id: str) -> str:
    payload = {"schema": "plan.v1", "title": "ok"}
    wrapper = {
        "schema": ARTIFACT_SCHEMA,
        "kind": "plan",
        "job": {
            "jobId": job["jobId"],
            "idempotencyKey": job["idempotencyKey"],
            "taskId": job["taskId"],
            "stage": job["stage"],
            "attempt": job["attempt"],
            "jobSha256": job_sha256,
        },
        "sessionId": session_id,
        "inputs": [
            {"kind": item["kind"], "path": item["path"], "sha256": item["sha256"]}
            for item in job["inputs"]
        ],
        "workspace": {
            "repoRoot": job["workspace"]["repoRoot"],
            "branch": job["workspace"]["branch"],
            "head": job["workspace"]["expectedHead"],
            "baselineSnapshotSha256": "0" * 64,
        },
        "payload": payload,
    }
    text = json.dumps(wrapper, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _config(state_root: Path) -> PluginConfig:
    return PluginConfig(
        profile="autodev",
        state_root=str(state_root),
        harness_command=("node", "/abs/harness.mjs"),
        main_branch="main",
        poll_interval_seconds=5,
        advance_wait_seconds=60,
    )


def _manifest(**overrides):
    data = {
        "schema": WORKFLOW_SCHEMA,
        "templateId": WORKFLOW_TEMPLATE_ID,
        "board": "project-board",
        "taskId": "t_abc",
        "repoRoot": "/abs/repo",
        "workflowStatus": "review_requested",
        "revision": 4,
        "stageAttempt": 1,
        "activeJobId": None,
        "plannerSessionId": "sess_plan",
        "implementerSessionId": "sess_impl",
        "planReworkCount": 0,
        "implementReworkCount": 0,
        "runFailureCounts": {},
        "baseline": {"branch": "main", "head": "a" * 40},
        "candidateFingerprint": None,
        "approvedPlan": None,
        "lastConsumedJobId": "job_impl",
        "pendingLifecycle": None,
        "resumeStatus": None,
    }
    data.update(overrides)
    return data


def _plant_completed_plan(store: WorkflowStore, state_root: Path, *, consumed: bool) -> dict[str, Any]:
    requirement = state_root / "requirement.json"
    requirement.write_text('{"schema":"autonomous-development.requirement.v1"}', encoding="utf-8")
    store.put_manifest(
        _manifest(
            workflowStatus="planning",
            revision=1,
            activeJobId=None,
            lastConsumedJobId=None,
            pendingLifecycle=None,
        )
    )
    digest = _sha(requirement.read_text(encoding="utf-8"))
    store.register_artifact(
        board="project-board",
        task_id="t_abc",
        job_id="intake:t_abc",
        kind="requirement",
        version=1,
        path=str(requirement),
        sha256=digest,
    )
    job = build_job(
        board="project-board",
        task_id="t_abc",
        stage="plan",
        business_attempt=1,
        transport_retry=0,
        workspace={
            "repoRoot": "/abs/repo",
            "branch": "main",
            "expectedHead": "a" * 40,
            "requireCleanAtStart": True,
        },
        agents=AGENTS,
        inputs=({"kind": "requirement", "path": str(requirement), "sha256": digest},),
        session_id=None,
    )
    run_dir = state_root / "boards" / "project-board" / "t_abc" / "jobs" / job["jobId"]
    written = write_job_document(job, run_dir)
    now = 1_000_000 if consumed else None
    store.put_job(
        {
            "job_id": job["jobId"],
            "board": "project-board",
            "task_id": "t_abc",
            "stage": "plan",
            "business_attempt": 1,
            "transport_retry": 0,
            "idempotency_key": job["idempotencyKey"],
            "job_path": written["job_path"],
            "run_dir": written["run_dir"],
            "job_sha256": written["job_sha256"],
            "harness_pid": None,
            "process_identity": None,
            "status": "completed",
            "result_path": str(run_dir / "result.json"),
            "started_at": now,
            "finished_at": now,
            "consumed_at": now,
        }
    )
    plan_path = state_root / "plan.json"
    payload = {"schema": "plan.v1", "title": "ok"}
    digest = _write_canonical_plan(
        plan_path, job=job, job_sha256=written["job_sha256"], session_id="sess_plan"
    )
    result = {
        "schema": RESULT_SCHEMA,
        "jobId": job["jobId"],
        "idempotencyKey": job["idempotencyKey"],
        "jobSha256": written["job_sha256"],
        "taskId": "t_abc",
        "stage": "plan",
        "status": "completed",
        "adapter": "pi",
        "sessionId": "sess_plan",
        "startedAt": "2026-09-14T00:00:00Z",
        "finishedAt": "2026-09-14T00:01:00Z",
        "structuredOutput": {"kind": "plan", "payload": payload},
        "artifacts": [
            {
                "kind": "plan",
                "path": str(plan_path),
                "sha256": digest,
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
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return {"job": job, "written": written, "requirement": requirement}


class FakeKanban:
    def __init__(self, *, status: str = "running", run_id: str = "7") -> None:
        self.status = status
        self.run_id = run_id
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name: str, args: dict, **kwargs) -> str:
        self.calls.append((name, dict(args)))
        if name == "kanban_show":
            return json.dumps(
                {
                    "task": {
                        "id": args.get("task_id", "t_abc"),
                        "status": self.status,
                        "assignee": "autodev",
                        "workspace_kind": "dir",
                        "workspace_path": "/abs/repo",
                        "current_run_id": self.run_id,
                    },
                    "parents": [],
                    "children": [],
                    "comments": [],
                    "events": [],
                    "runs": [{"id": self.run_id, "status": "running"}],
                }
            )
        if name == "kanban_request_review":
            self.status = "review"
            return json.dumps({"ok": True, "task_id": args.get("task_id")})
        if name == "kanban_complete":
            self.status = "done"
            return json.dumps({"ok": True, "task_id": args.get("task_id")})
        if name == "kanban_block":
            self.status = "blocked"
            return json.dumps({"ok": True, "task_id": args.get("task_id")})
        if name == "kanban_request_changes":
            self.status = "todo"
            return json.dumps({"ok": True, "task_id": args.get("task_id")})
        if name == "kanban_heartbeat":
            return json.dumps({"ok": True})
        return json.dumps({"error": f"unknown tool {name}"})


class LifecycleSagaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-life-")
        self.state_root = Path(self._tmp.name) / "state"
        self.state_root.mkdir()
        self.store = WorkflowStore(str(self.state_root))
        self.kanban = FakeKanban()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _controller(self) -> WorkflowController:
        return WorkflowController(
            store=self.store,
            config=_config(self.state_root),
            dispatch_tool=self.kanban,
            agents=AGENTS,
            popen=Mock(side_effect=AssertionError("harness must not start")),
        )

    def test_checkpointed_review_request_is_applied_once_on_restart(self) -> None:
        pending = make_pending_lifecycle(
            target_status="review_requested",
            run_id="7",
            workflow_revision=4,
        )
        self.store.put_manifest(_manifest(pendingLifecycle=pending, revision=4))
        controller = self._controller()
        first = controller.advance(board="project-board", task_id="t_abc", run_id="7")
        self.assertEqual(first["workflowStatus"], "review_requested")
        self.assertIsNone(first["pendingLifecycle"])
        reviews = [name for name, _ in self.kanban.calls if name == "kanban_request_review"]
        self.assertEqual(len(reviews), 1)
        second = controller.advance(board="project-board", task_id="t_abc", run_id="7")
        reviews = [name for name, _ in self.kanban.calls if name == "kanban_request_review"]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(second["nextAction"], "noop")

    def test_checkpointed_complete_is_applied_once_on_restart(self) -> None:
        self.kanban.status = "review"
        pending = make_pending_lifecycle(
            target_status="completed",
            run_id="7",
            workflow_revision=8,
        )
        self.store.put_manifest(
            _manifest(workflowStatus="completed", pendingLifecycle=pending, revision=8)
        )
        controller = self._controller()
        controller.advance(board="project-board", task_id="t_abc", run_id="7")
        completes = [name for name, _ in self.kanban.calls if name == "kanban_complete"]
        self.assertEqual(len(completes), 1)
        controller.advance(board="project-board", task_id="t_abc", run_id="7")
        completes = [name for name, _ in self.kanban.calls if name == "kanban_complete"]
        self.assertEqual(len(completes), 1)

    def test_pending_lifecycle_bound_to_old_run_is_refused(self) -> None:
        pending = make_pending_lifecycle(
            target_status="review_requested",
            run_id="old-run",
            workflow_revision=4,
        )
        self.store.put_manifest(_manifest(pendingLifecycle=pending))
        controller = self._controller()
        with self.assertRaises(WorkflowProtocolError):
            controller.advance(board="project-board", task_id="t_abc", run_id="7")
        self.assertFalse(any(name == "kanban_request_review" for name, _ in self.kanban.calls))

    def test_existing_result_is_consumed_without_starting_harness(self) -> None:
        requirement = self.state_root / "requirement.json"
        requirement.write_text('{"schema":"autonomous-development.requirement.v1"}', encoding="utf-8")
        self.store.put_manifest(
            _manifest(
                workflowStatus="planning",
                revision=1,
                activeJobId=None,
                lastConsumedJobId=None,
                pendingLifecycle=None,
            )
        )
        self.store.register_artifact(
            board="project-board",
            task_id="t_abc",
            job_id="intake:t_abc",
            kind="requirement",
            version=1,
            path=str(requirement),
            sha256=_sha(requirement.read_text(encoding="utf-8")),
        )
        job = build_job(
            board="project-board",
            task_id="t_abc",
            stage="plan",
            business_attempt=1,
            transport_retry=0,
            workspace={
                "repoRoot": "/abs/repo",
                "branch": "main",
                "expectedHead": "a" * 40,
                "requireCleanAtStart": True,
            },
            agents=AGENTS,
            inputs=(
                {
                    "kind": "requirement",
                    "path": str(requirement),
                    "sha256": _sha(requirement.read_text(encoding="utf-8")),
                },
            ),
            session_id=None,
        )
        run_dir = self.state_root / "boards" / "project-board" / "t_abc" / "jobs" / job["jobId"]
        written = write_job_document(job, run_dir)
        self.store.put_job(
            {
                "job_id": job["jobId"],
                "board": "project-board",
                "task_id": "t_abc",
                "stage": "plan",
                "business_attempt": 1,
                "transport_retry": 0,
                "idempotency_key": job["idempotencyKey"],
                "job_path": written["job_path"],
                "run_dir": written["run_dir"],
                "job_sha256": written["job_sha256"],
                "harness_pid": None,
                "process_identity": None,
                "status": "pending",
                "result_path": None,
                "started_at": None,
                "finished_at": None,
                "consumed_at": None,
            }
        )
        plan_path = self.state_root / "plan.json"
        payload = {"schema": "plan.v1", "title": "ok"}
        digest = _write_canonical_plan(
            plan_path, job=job, job_sha256=written["job_sha256"], session_id="sess_plan"
        )
        result = {
            "schema": RESULT_SCHEMA,
            "jobId": job["jobId"],
            "idempotencyKey": job["idempotencyKey"],
            "jobSha256": written["job_sha256"],
            "taskId": "t_abc",
            "stage": "plan",
            "status": "completed",
            "adapter": "pi",
            "sessionId": "sess_plan",
            "startedAt": "2026-09-14T00:00:00Z",
            "finishedAt": "2026-09-14T00:01:00Z",
            "structuredOutput": {"kind": "plan", "payload": payload},
            "artifacts": [
                {
                    "kind": "plan",
                    "path": str(plan_path),
                    "sha256": digest,
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
        (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
        current = self.store.get_manifest("project-board", "t_abc")
        current["activeJobId"] = job["jobId"]
        current["revision"] = 2
        self.store.cas_update_manifest(
            "project-board", "t_abc", expected_revision=1, manifest=current
        )
        popen = Mock(side_effect=AssertionError("must not start harness"))
        controller = WorkflowController(
            store=self.store,
            config=_config(self.state_root),
            dispatch_tool=self.kanban,
            agents=AGENTS,
            popen=popen,
        )
        outcome = controller.advance(board="project-board", task_id="t_abc", run_id="7")
        popen.assert_not_called()
        self.assertEqual(outcome["workflowStatus"], "plan_reviewing")
        loaded = self.store.get_job(job["jobId"])
        self.assertIsNotNone(loaded["consumed_at"])

    def test_replaced_job_json_cannot_complete_even_with_matching_forged_result(self) -> None:
        requirement = self.state_root / "requirement.json"
        requirement.write_text('{"schema":"autonomous-development.requirement.v1"}', encoding="utf-8")
        self.store.put_manifest(
            _manifest(
                workflowStatus="planning",
                revision=1,
                activeJobId=None,
                lastConsumedJobId=None,
                pendingLifecycle=None,
            )
        )
        self.store.register_artifact(
            board="project-board",
            task_id="t_abc",
            job_id="intake:t_abc",
            kind="requirement",
            version=1,
            path=str(requirement),
            sha256=_sha(requirement.read_text(encoding="utf-8")),
        )
        job = build_job(
            board="project-board",
            task_id="t_abc",
            stage="plan",
            business_attempt=1,
            transport_retry=0,
            workspace={
                "repoRoot": "/abs/repo",
                "branch": "main",
                "expectedHead": "a" * 40,
                "requireCleanAtStart": True,
            },
            agents=AGENTS,
            inputs=(
                {
                    "kind": "requirement",
                    "path": str(requirement),
                    "sha256": _sha(requirement.read_text(encoding="utf-8")),
                },
            ),
            session_id=None,
        )
        run_dir = self.state_root / "boards" / "project-board" / "t_abc" / "jobs" / job["jobId"]
        written = write_job_document(job, run_dir)
        self.store.put_job(
            {
                "job_id": job["jobId"],
                "board": "project-board",
                "task_id": "t_abc",
                "stage": "plan",
                "business_attempt": 1,
                "transport_retry": 0,
                "idempotency_key": job["idempotencyKey"],
                "job_path": written["job_path"],
                "run_dir": written["run_dir"],
                "job_sha256": written["job_sha256"],
                "harness_pid": None,
                "process_identity": None,
                "status": "pending",
                "result_path": None,
                "started_at": None,
                "finished_at": None,
                "consumed_at": None,
            }
        )
        forged = json.loads(Path(written["job_path"]).read_text(encoding="utf-8"))
        forged["agent"]["model"] = "forged-model"
        Path(written["job_path"]).write_text(json.dumps(forged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        forged_sha = job_document_sha256(forged)
        self.assertNotEqual(forged_sha, written["job_sha256"])
        payload = {"schema": "plan.v1", "title": "ok"}
        plan_path = self.state_root / "plan.json"
        digest = _write_canonical_plan(
            plan_path, job=forged, job_sha256=forged_sha, session_id="sess_plan"
        )
        result = {
            "schema": RESULT_SCHEMA,
            "jobId": forged["jobId"],
            "idempotencyKey": forged["idempotencyKey"],
            "jobSha256": forged_sha,
            "taskId": "t_abc",
            "stage": "plan",
            "status": "completed",
            "adapter": "pi",
            "sessionId": "sess_plan",
            "startedAt": "2026-09-14T00:00:00Z",
            "finishedAt": "2026-09-14T00:01:00Z",
            "structuredOutput": {"kind": "plan", "payload": payload},
            "artifacts": [
                {
                    "kind": "plan",
                    "path": str(plan_path),
                    "sha256": digest,
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
        (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
        current = self.store.get_manifest("project-board", "t_abc")
        current["activeJobId"] = job["jobId"]
        current["revision"] = 2
        self.store.cas_update_manifest(
            "project-board", "t_abc", expected_revision=1, manifest=current
        )
        controller = WorkflowController(
            store=self.store,
            config=_config(self.state_root),
            dispatch_tool=self.kanban,
            agents=AGENTS,
            popen=Mock(side_effect=AssertionError("must not start harness")),
        )
        outcome = controller.advance(board="project-board", task_id="t_abc", run_id="7")
        self.assertEqual(outcome["workflowStatus"], "blocked")
        self.assertNotEqual(outcome["workflowStatus"], "plan_reviewing")
        self.assertNotEqual(outcome["workflowStatus"], "completed")
        self.assertIsNone(self.store.latest_artifact("project-board", "t_abc", "plan"))

    def test_protocol_failure_blocks_then_reconsumes_without_harness_after_unblock(self) -> None:
        planted = _plant_completed_plan(self.store, self.state_root, consumed=False)
        job = planted["job"]
        written = planted["written"]
        current = self.store.get_manifest("project-board", "t_abc")
        current["activeJobId"] = job["jobId"]
        current["revision"] = 2
        self.store.cas_update_manifest(
            "project-board", "t_abc", expected_revision=1, manifest=current
        )
        result_path = Path(written["run_dir"]) / "result.json"
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["artifacts"][0]["schema"] = "plan.v1"
        result_path.write_text(json.dumps(payload), encoding="utf-8")
        popen = Mock(side_effect=AssertionError("must not start harness"))
        controller = WorkflowController(
            store=self.store,
            config=_config(self.state_root),
            dispatch_tool=self.kanban,
            agents=AGENTS,
            popen=popen,
        )
        blocked = controller.advance(board="project-board", task_id="t_abc", run_id="7")
        self.assertEqual(blocked["workflowStatus"], "blocked")
        loaded = self.store.get_manifest("project-board", "t_abc")
        self.assertEqual(loaded["resumeStatus"], "planning")
        self.assertEqual(self.kanban.status, "blocked")
        still = controller.advance(board="project-board", task_id="t_abc", run_id="7")
        self.assertEqual(still["nextAction"], "noop")
        popen.assert_not_called()
        self.kanban.status = "running"
        resumed = controller.advance(board="project-board", task_id="t_abc", run_id="7")
        popen.assert_not_called()
        self.assertEqual(resumed["workflowStatus"], "blocked")
        job_row = self.store.get_job(job["jobId"])
        self.assertIsNotNone(job_row["consumed_at"])

    def test_legacy_blocked_without_resume_status_reconsumes_completed_job(self) -> None:
        planted = _plant_completed_plan(self.store, self.state_root, consumed=True)
        job = planted["job"]
        current = self.store.get_manifest("project-board", "t_abc")
        current["activeJobId"] = job["jobId"]
        current["workflowStatus"] = "blocked"
        current["resumeStatus"] = None
        current["lastConsumedJobId"] = job["jobId"]
        current["revision"] = 2
        self.store.cas_update_manifest(
            "project-board", "t_abc", expected_revision=1, manifest=current
        )
        self.kanban.status = "running"
        popen = Mock(side_effect=AssertionError("must not start harness"))
        controller = WorkflowController(
            store=self.store,
            config=_config(self.state_root),
            dispatch_tool=self.kanban,
            agents=AGENTS,
            popen=popen,
        )
        outcome = controller.advance(board="project-board", task_id="t_abc", run_id="7")
        popen.assert_not_called()
        self.assertEqual(outcome["workflowStatus"], "plan_reviewing")

    def test_apply_pending_rejects_old_run_without_dispatch(self) -> None:
        pending = make_pending_lifecycle(
            target_status="review_requested", run_id="1", workflow_revision=1
        )
        with self.assertRaises(WorkflowProtocolError):
            apply_pending_lifecycle(
                pending,
                current_run_id="2",
                task_id="t_abc",
                board="project-board",
                dispatch=self.kanban,
            )


class ProcessGoneRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-gone-")
        self.state_root = Path(self._tmp.name) / "state"
        self.state_root.mkdir()
        self.store = WorkflowStore(str(self.state_root))
        self.kanban = FakeKanban()
        requirement = self.state_root / "requirement.json"
        requirement.write_text('{"schema":"autonomous-development.requirement.v1"}', encoding="utf-8")
        self.store.put_manifest(
            _manifest(
                workflowStatus="queued",
                revision=1,
                activeJobId=None,
                lastConsumedJobId=None,
                pendingLifecycle=None,
            )
        )
        self.store.register_artifact(
            board="project-board",
            task_id="t_abc",
            job_id="intake:t_abc",
            kind="requirement",
            version=1,
            path=str(requirement),
            sha256=_sha(requirement.read_text(encoding="utf-8")),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_dead_pid_without_lock_or_result_retries_then_blocks(self) -> None:
        launches: list[list[str]] = []

        def fake_popen(argv, **kwargs):
            proc = Mock()
            proc.pid = 93000 + len(launches)
            proc.wait = Mock(return_value=2)
            launches.append(list(argv))
            return proc

        controller = WorkflowController(
            store=self.store,
            config=_config(self.state_root),
            dispatch_tool=self.kanban,
            agents=AGENTS,
            popen=fake_popen,
            identity_fn=lambda pid: None,
            sleep_fn=lambda seconds: None,
            monotonic_fn=lambda: 0.0,
        )
        first = controller.advance(board="project-board", task_id="t_abc", run_id="7", wait_seconds=1)
        self.assertEqual(len(launches), 1)
        jobs = self.store.list_jobs("project-board", "t_abc")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "unavailable")
        self.assertIsNotNone(jobs[0]["consumed_at"])
        first_job_id = jobs[0]["job_id"]
        first_out = jobs[0]["run_dir"]
        manifest = self.store.get_manifest("project-board", "t_abc")
        self.assertEqual(manifest["runFailureCounts"]["plan"], 1)
        self.assertNotEqual(first["workflowStatus"], "blocked")
        notes = [args.get("note", "") for name, args in self.kanban.calls if name == "kanban_heartbeat"]
        self.assertFalse(any("still running" in note for note in notes))

        second = controller.advance(board="project-board", task_id="t_abc", run_id="7", wait_seconds=1)
        self.assertEqual(len(launches), 2)
        jobs = self.store.list_jobs("project-board", "t_abc")
        self.assertEqual(len(jobs), 2)
        self.assertNotEqual(jobs[1]["job_id"], first_job_id)
        self.assertNotEqual(jobs[1]["run_dir"], first_out)
        self.assertEqual(second["workflowStatus"], "blocked")

        controller.advance(board="project-board", task_id="t_abc", run_id="7", wait_seconds=1)
        self.assertEqual(len(launches), 2)
        self.assertEqual(launches[0][launches[0].index("--out-dir") + 1], first_out)
        self.assertEqual(launches[1][launches[1].index("--out-dir") + 1], jobs[1]["run_dir"])


if __name__ == "__main__":
    unittest.main()
