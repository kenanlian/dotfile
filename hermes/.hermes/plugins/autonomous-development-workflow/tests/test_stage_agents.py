"""Per-Stage agent routing: stage_agents config, frozen lineage bindings, and
adapter-bound Result consumption."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from helpers import AGENTS, SmokeEnv, _patched_env
from plugin_imports import import_plugin

_config = import_plugin("config")
_jobs = import_plugin("controller.jobs")
_protocol = import_plugin("controller.protocol")
_types = import_plugin("controller.types")

load_plugin_config = _config.load_plugin_config
build_job = _jobs.build_job
consume_result = _jobs.consume_result
resolve_agent_selection = _jobs.resolve_agent_selection
write_job_document = _jobs.write_job_document
job_document_sha256 = _protocol.job_document_sha256
WorkflowProtocolError = _types.WorkflowProtocolError
WorkflowStatus = _types.WorkflowStatus
STAGE_PROFILES = _types.STAGE_PROFILES
ARTIFACT_SCHEMA = _types.ARTIFACT_SCHEMA
RESULT_SCHEMA = _types.RESULT_SCHEMA

REQUIREMENT_STAGE_AGENTS = {
    "plan": {"adapter": "cursor", "model": "claude-opus-5-thinking-high", "thinking": "high"},
    "plan_review": {"adapter": "pi", "model": "zai-coding-cn/glm-5.3", "thinking": "high"},
    "implement": {"adapter": "cursor", "model": "gpt-5.6-sol-high", "thinking": "high"},
    "execute_review": {"adapter": "pi", "model": "zai-coding-cn/glm-5.3", "thinking": "high"},
    "direct_implement": {"adapter": "cursor", "model": "cursor-grok-4.6-high", "thinking": "high"},
}

BASE_CONFIG = {
    "state_root": "/abs/state",
    "harness_command": ["node", "/abs/harness.mjs"],
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _artifact(kind: str, directory: Path) -> dict:
    path = directory / f"{kind}.json"
    path.write_text(json.dumps({"kind": kind}), encoding="utf-8")
    return {"kind": kind, "path": str(path), "sha256": _sha(json.dumps({"kind": kind}))}


def _workspace() -> dict:
    return {
        "repoRoot": "/abs/repo",
        "branch": "main",
        "expectedHead": "a" * 40,
        "requireCleanAtStart": True,
    }


_PLAN_CHECK = {
    "id": "unit",
    "argv": ["node", "--test"],
    "cwd": "/abs/repo",
    "timeoutSeconds": 30,
    "expectedExitCode": 0,
}

STAGE_INPUTS: dict[str, tuple[str, ...]] = {
    "plan": ("requirement",),
    "plan_review": ("requirement", "plan"),
    "implement": ("plan",),
    "execute_review": ("requirement", "plan", "implementation"),
    "direct_implement": ("requirement",),
}


def _build(stage: str, root: Path, **overrides) -> dict:
    kwargs: dict[str, Any] = {
        "board": "project-board",
        "task_id": "t_abc",
        "stage": stage,
        "business_attempt": 1,
        "transport_retry": 0,
        "workspace": _workspace(),
        "agents": AGENTS,
        "inputs": tuple(_artifact(kind, root) for kind in STAGE_INPUTS[stage]),
        "session_id": None,
    }
    if stage in {"implement", "direct_implement"}:
        kwargs["verification"] = (_PLAN_CHECK,)
    kwargs.update(overrides)
    return build_job(**kwargs)


def _write_canonical_artifact(
    path: Path,
    *,
    kind: str,
    job: dict,
    job_sha256: str,
    session_id: str | None,
    payload: dict,
) -> str:
    wrapper = {
        "schema": ARTIFACT_SCHEMA,
        "kind": kind,
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


class StageAgentsConfigTests(unittest.TestCase):
    def test_requirement_example_parses(self) -> None:
        config = load_plugin_config({**BASE_CONFIG, "stage_agents": REQUIREMENT_STAGE_AGENTS})
        self.assertEqual(dict(config.stage_agents), REQUIREMENT_STAGE_AGENTS)

    def test_absent_stage_agents_defaults_to_empty(self) -> None:
        config = load_plugin_config(dict(BASE_CONFIG))
        self.assertEqual(dict(config.stage_agents), {})

    def test_unknown_stage_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(WorkflowProtocolError, "unknown keys \\['deploy'\\]"):
            load_plugin_config(
                {**BASE_CONFIG, "stage_agents": {"deploy": {"adapter": "pi", "model": "m", "thinking": "high"}}}
            )

    def test_profile_keyed_stage_agents_is_rejected(self) -> None:
        with self.assertRaisesRegex(WorkflowProtocolError, "unknown keys \\['implementer'\\]"):
            load_plugin_config(
                {
                    **BASE_CONFIG,
                    "stage_agents": {"implementer": {"adapter": "cursor", "model": "m", "thinking": "high"}},
                }
            )

    def test_invalid_adapter_is_rejected(self) -> None:
        with self.assertRaisesRegex(WorkflowProtocolError, "adapter"):
            load_plugin_config(
                {
                    **BASE_CONFIG,
                    "stage_agents": {"plan": {"adapter": "codex", "model": "m", "thinking": "high"}},
                }
            )

    def test_missing_or_empty_model_is_rejected(self) -> None:
        for model in (None, "", "   "):
            with self.assertRaisesRegex(WorkflowProtocolError, "model"):
                load_plugin_config(
                    {
                        **BASE_CONFIG,
                        "stage_agents": {"plan": {"adapter": "cursor", "model": model, "thinking": "high"}},
                    }
                )

    def test_invalid_thinking_is_rejected(self) -> None:
        with self.assertRaisesRegex(WorkflowProtocolError, "thinking"):
            load_plugin_config(
                {
                    **BASE_CONFIG,
                    "stage_agents": {"plan": {"adapter": "cursor", "model": "m", "thinking": "ultra"}},
                }
            )

    def test_unknown_entry_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(WorkflowProtocolError, "unknown fields"):
            load_plugin_config(
                {
                    **BASE_CONFIG,
                    "stage_agents": {
                        "plan": {"adapter": "cursor", "model": "m", "thinking": "high", "profile": "planner"}
                    },
                }
            )

    def test_non_mapping_shapes_are_rejected(self) -> None:
        with self.assertRaisesRegex(WorkflowProtocolError, "stage_agents"):
            load_plugin_config({**BASE_CONFIG, "stage_agents": ["plan"]})
        with self.assertRaisesRegex(WorkflowProtocolError, "stage_agents\\[plan\\]"):
            load_plugin_config({**BASE_CONFIG, "stage_agents": {"plan": "cursor"}})


class BuildJobSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-stage-agents-")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_stage_agents_win_for_every_stage(self) -> None:
        for stage, selection in REQUIREMENT_STAGE_AGENTS.items():
            job = _build(stage, self.root, stage_agents=REQUIREMENT_STAGE_AGENTS)
            self.assertEqual(job["agent"]["adapter"], selection["adapter"], stage)
            self.assertEqual(job["agent"]["model"], selection["model"], stage)
            self.assertEqual(job["agent"]["thinking"], selection["thinking"], stage)

    def test_implement_and_direct_implement_select_independently(self) -> None:
        stage_agents = {
            "implement": {"adapter": "cursor", "model": "cursor-opus-4.6", "thinking": "high"},
            "direct_implement": {"adapter": "pi", "model": "zai-coding-cn/glm-5.3", "thinking": "medium"},
        }
        impl = _build("implement", self.root, stage_agents=stage_agents)
        direct = _build("direct_implement", self.root, stage_agents=stage_agents)
        self.assertEqual(impl["agent"]["adapter"], "cursor")
        self.assertEqual(impl["agent"]["model"], "cursor-opus-4.6")
        self.assertEqual(direct["agent"]["adapter"], "pi")
        self.assertEqual(direct["agent"]["model"], "zai-coding-cn/glm-5.3")

    def test_missing_stage_entry_falls_back_to_legacy_pi_profile(self) -> None:
        for stage in STAGE_INPUTS:
            job = _build(stage, self.root, stage_agents={"plan": REQUIREMENT_STAGE_AGENTS["plan"]})
            if stage == "plan":
                continue
            profile = STAGE_PROFILES[stage]
            self.assertEqual(job["agent"]["adapter"], "pi", stage)
            self.assertEqual(job["agent"]["model"], AGENTS[profile]["model"], stage)
            self.assertEqual(job["agent"]["thinking"], AGENTS[profile]["thinking"], stage)

    def test_legacy_fallback_uses_profile_model_and_default_pi(self) -> None:
        job = _build("execute_review", self.root)
        self.assertEqual(job["agent"]["adapter"], "pi")
        self.assertEqual(job["agent"]["model"], "review-model")
        self.assertEqual(job["agent"]["thinking"], "medium")

    def test_legacy_spec_adapter_is_honored(self) -> None:
        agents = {**AGENTS, "planner": {"adapter": "cursor", "model": "cursor-opus-4.6", "thinking": "high"}}
        job = _build("plan", self.root, agents=agents)
        self.assertEqual(job["agent"]["adapter"], "cursor")
        self.assertEqual(job["agent"]["model"], "cursor-opus-4.6")

    def test_frozen_selection_overrides_stage_agents(self) -> None:
        job = _build(
            "plan",
            self.root,
            stage_agents=REQUIREMENT_STAGE_AGENTS,
            agent_selection={"adapter": "pi", "model": "zai-coding-cn/glm-5.3", "thinking": "low"},
        )
        self.assertEqual(job["agent"]["adapter"], "pi")
        self.assertEqual(job["agent"]["model"], "zai-coding-cn/glm-5.3")
        self.assertEqual(job["agent"]["thinking"], "low")

    def test_invalid_stage_agents_selection_is_rejected_by_build_job(self) -> None:
        with self.assertRaisesRegex(WorkflowProtocolError, "stage_agents\\[plan\\].adapter"):
            _build("plan", self.root, stage_agents={"plan": {"adapter": "codex", "model": "m", "thinking": "high"}})
        with self.assertRaisesRegex(WorkflowProtocolError, "stage_agents\\[plan\\].thinking"):
            _build("plan", self.root, stage_agents={"plan": {"adapter": "cursor", "model": "m", "thinking": "ultra"}})
        with self.assertRaisesRegex(WorkflowProtocolError, "stage_agents\\[plan\\].model"):
            _build("plan", self.root, stage_agents={"plan": {"adapter": "cursor", "model": "", "thinking": "high"}})

    def test_invalid_frozen_selection_is_rejected(self) -> None:
        with self.assertRaisesRegex(WorkflowProtocolError, "agent_selection.adapter"):
            _build("plan", self.root, agent_selection={"adapter": "codex", "model": "m", "thinking": "high"})
        with self.assertRaisesRegex(WorkflowProtocolError, "agent_selection.model"):
            _build("plan", self.root, agent_selection={"adapter": "cursor", "model": "", "thinking": "high"})

    def test_invalid_legacy_adapter_is_rejected(self) -> None:
        agents = {**AGENTS, "planner": {"adapter": "codex", "model": "m", "thinking": "high"}}
        with self.assertRaisesRegex(WorkflowProtocolError, "agents\\[planner\\].adapter"):
            _build("plan", self.root, agents=agents)

    def test_cursor_job_document_passes_validation(self) -> None:
        job = _build("plan", self.root, stage_agents=REQUIREMENT_STAGE_AGENTS)
        run_dir = self.root / "run"
        written = write_job_document(job, run_dir)
        self.assertEqual(written["job_sha256"], job_document_sha256(job))


class ResolveSelectionTests(unittest.TestCase):
    def test_unknown_stage_is_rejected(self) -> None:
        with self.assertRaisesRegex(WorkflowProtocolError, "unknown job stage"):
            resolve_agent_selection(stage="deploy", agents=AGENTS)


class ResultAdapterBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-adapter-bind-")
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
            stage_agents=REQUIREMENT_STAGE_AGENTS,
            inputs=(requirement,),
            session_id=None,
        )
        self.assertEqual(self.job["agent"]["adapter"], "cursor")
        self.job_sha = write_job_document(self.job, self.root / "run")["job_sha256"]
        self.plan_path = self.root / "plan.json"
        self.plan_payload = {"schema": "plan.v1", "title": "ok"}
        self.plan_sha = _write_canonical_artifact(
            self.plan_path,
            kind="plan",
            job=self.job,
            job_sha256=self.job_sha,
            session_id="sess_plan",
            payload=self.plan_payload,
        )

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
            "adapter": "cursor",
            "sessionId": "sess_plan",
            "startedAt": "2026-09-14T00:00:00Z",
            "finishedAt": "2026-09-14T00:01:00Z",
            "structuredOutput": {"kind": "plan", "payload": self.plan_payload},
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

    def test_matching_adapter_consumes(self) -> None:
        outcome = consume_result(self.job, self._result())
        self.assertEqual(outcome.kind, "consumed")
        self.assertEqual(outcome.next_status, WorkflowStatus.PLAN_REVIEWING)

    def test_adapter_mismatch_is_protocol_failure(self) -> None:
        outcome = consume_result(self.job, self._result(adapter="pi"))
        self.assertEqual(outcome.kind, "protocol_failure")
        self.assertIn("adapter", outcome.reason)

    def test_missing_adapter_is_protocol_failure(self) -> None:
        result = self._result()
        del result["adapter"]
        outcome = consume_result(self.job, result)
        self.assertEqual(outcome.kind, "protocol_failure")
        self.assertIn("adapter", outcome.reason)

    def test_transport_failure_result_still_requires_matching_adapter(self) -> None:
        outcome = consume_result(
            self.job,
            self._result(status="failed", sessionId=None, adapter="pi", structuredOutput=None, artifacts=[]),
        )
        self.assertEqual(outcome.kind, "protocol_failure")
        self.assertIn("adapter", outcome.reason)
        retried = consume_result(
            self.job,
            self._result(status="failed", sessionId=None, structuredOutput=None, artifacts=[]),
        )
        self.assertEqual(retried.kind, "transport_failure")


class MixedAdapterWorkflowTests(unittest.TestCase):
    """Controller-level: one workflow routes different Stages to Pi and Cursor."""

    def setUp(self) -> None:
        self.env = SmokeEnv()
        self.env.stage_agents = REQUIREMENT_STAGE_AGENTS

    def tearDown(self) -> None:
        self.env.close()

    def _job_docs(self, task_id: str, stage: str) -> list[dict]:
        rows = [row for row in self.env.store.list_jobs("project-board", task_id) if row["stage"] == stage]
        return [json.loads(Path(row["job_path"]).read_text(encoding="utf-8")) for row in rows]

    def test_stages_route_to_configured_adapters_and_results_bind(self) -> None:
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        manifest = self.env.store.get_manifest("project-board", task_id)
        # implementer-side stages exist after the ready lane; execute_review is
        # created only once the review lane advances.
        for stage in ("plan", "plan_review", "implement"):
            selection = REQUIREMENT_STAGE_AGENTS[stage]
            docs = self._job_docs(task_id, stage)
            self.assertEqual(len(docs), 1, stage)
            self.assertEqual(docs[0]["agent"]["adapter"], selection["adapter"], stage)
            self.assertEqual(docs[0]["agent"]["model"], selection["model"], stage)
            self.assertEqual(docs[0]["agent"]["thinking"], selection["thinking"], stage)
            self.assertIsNone(docs[0]["agent"]["sessionId"], stage)
            self.assertEqual(
                manifest["stageAgents"][stage],
                {"adapter": selection["adapter"], "model": selection["model"], "thinking": selection["thinking"]},
                stage,
            )
        self.env.kanban.claim_review(task_id, run_id="2")
        result = self.env.advance_until(task_id=task_id, run_id="2", outcomes={"acceptance_required"})
        self.assertEqual(result["outcome"], "acceptance_required")
        review = self._job_docs(task_id, "execute_review")[0]
        self.assertEqual(review["agent"]["adapter"], "pi")
        self.assertEqual(review["agent"]["model"], "zai-coding-cn/glm-5.3")
        self.assertIsNone(review["agent"]["sessionId"])

    def test_implement_rework_reuses_frozen_cursor_adapter_and_session(self) -> None:
        self.env.set_script(
            {
                "plan:1:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:1:0": {"status": "completed", "verdict": "approved"},
                "implement:1:0": {"status": "completed", "checks": "passed", "sessionId": "sess_impl_1"},
                "execute_review:1:0": {"status": "completed", "verdict": "request_changes"},
                "implement:2:0": {"status": "completed", "checks": "passed", "sessionId": "sess_impl_1"},
                "execute_review:2:0": {"status": "completed", "verdict": "approved"},
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        self.env.kanban.claim_review(task_id, run_id="2")
        self.env.advance_until(task_id=task_id, run_id="2", statuses={"implement_rework"})
        self.env.kanban.claim_ready(task_id, run_id="3")
        self.env.advance_until(task_id=task_id, run_id="3", statuses={"review_requested"})
        impl_docs = self._job_docs(task_id, "implement")
        self.assertEqual(len(impl_docs), 2)
        for doc in impl_docs:
            self.assertEqual(doc["agent"]["adapter"], "cursor")
            self.assertEqual(doc["agent"]["model"], "gpt-5.6-sol-high")
        self.assertIsNone(impl_docs[0]["agent"]["sessionId"])
        self.assertEqual(impl_docs[1]["agent"]["sessionId"], "sess_impl_1")
        # The second review round still runs fresh Pi reviewers.
        self.env.kanban.claim_review(task_id, run_id="4")
        self.env.advance_until(task_id=task_id, run_id="4", outcomes={"acceptance_required"})
        review_docs = self._job_docs(task_id, "execute_review")
        self.assertEqual(len(review_docs), 2)
        for doc in review_docs:
            self.assertEqual(doc["agent"]["adapter"], "pi")
            self.assertEqual(doc["agent"]["model"], "zai-coding-cn/glm-5.3")
            self.assertIsNone(doc["agent"]["sessionId"])


    def test_direct_implement_routes_to_cursor_and_completes(self) -> None:
        self.env.stage_agents = {"direct_implement": REQUIREMENT_STAGE_AGENTS["direct_implement"]}
        verification = self.env.root / "verification.json"
        verification.write_text(
            json.dumps(
                {
                    "schema": "autodev.verification.v1",
                    "checks": [
                        {
                            "id": "unit",
                            "argv": ["true"],
                            "cwd": ".",
                            "timeoutSeconds": 30,
                            "expectedExitCode": 0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        created = self.env.enqueue(flow="direct", verification=str(verification))
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        result = self.env.advance_until(task_id=task_id, statuses={"completed"})
        self.assertEqual(result["workflowStatus"], "completed")
        doc = self._job_docs(task_id, "direct_implement")[0]
        self.assertEqual(doc["agent"]["adapter"], "cursor")
        self.assertEqual(doc["agent"]["model"], "cursor-grok-4.6-high")
        self.assertEqual(doc["agent"]["profile"], "implementer")
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["stageAgents"]["direct_implement"]["adapter"], "cursor")


class FrozenLineageTests(unittest.TestCase):
    """Frozen selections survive rework, transport retry, restarts, and config edits."""

    def setUp(self) -> None:
        self.env = SmokeEnv()

    def tearDown(self) -> None:
        self.env.close()

    def _job_docs(self, task_id: str, stage: str) -> list[dict]:
        rows = [row for row in self.env.store.list_jobs("project-board", task_id) if row["stage"] == stage]
        return [json.loads(Path(row["job_path"]).read_text(encoding="utf-8")) for row in rows]

    def _advance_once(self, task_id: str, run_id: str = "1") -> dict:
        controller = self.env.controller()
        with _patched_env(self.env.harness_env()):
            return controller.advance(
                board="project-board",
                task_id=task_id,
                run_id=run_id,
                wait_seconds=8,
            )

    def test_mid_run_config_change_does_not_reroute_plan_lineage(self) -> None:
        self.env.set_script(
            {
                "plan:1:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:1:0": {"status": "completed", "verdict": "request_changes"},
                "plan:2:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:2:0": {"status": "completed", "verdict": "approved"},
                "implement:1:0": {"status": "completed", "checks": "passed", "sessionId": "sess_impl_1"},
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        # One advance runs plan:1 and plan_review:1 (request_changes) and creates
        # the plan rework job plan:2 under the legacy Pi routing.
        self._advance_once(task_id)
        first = self._job_docs(task_id, "plan")[0]
        self.assertEqual(first["agent"]["adapter"], "pi")
        self.assertEqual(first["agent"]["model"], "planner-model")
        # ...then the operator rewrites config mid-run: the frozen plan lineage
        # must keep its original selection and session.
        self.env.stage_agents = REQUIREMENT_STAGE_AGENTS
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        docs = self._job_docs(task_id, "plan")
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[1]["agent"]["adapter"], "pi")
        self.assertEqual(docs[1]["agent"]["model"], "planner-model")
        self.assertEqual(docs[1]["agent"]["sessionId"], "sess_plan_1")
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["stageAgents"]["plan"]["adapter"], "pi")
        # Stages created only after the edit use the new config.
        impl = self._job_docs(task_id, "implement")[0]
        self.assertEqual(impl["agent"]["adapter"], "cursor")
        self.assertEqual(impl["agent"]["model"], "gpt-5.6-sol-high")

    def test_transport_retry_reuses_frozen_cursor_selection(self) -> None:
        self.env.stage_agents = {"plan": REQUIREMENT_STAGE_AGENTS["plan"]}
        self.env.set_script(
            {
                "plan:1:0": {"status": "failed", "error": "adapter unavailable"},
                "plan:1:1": {"status": "completed", "sessionId": "sess_plan_retry"},
                "plan_review:1:0": {"status": "completed", "verdict": "approved"},
                "implement:1:0": {"status": "completed", "checks": "passed", "sessionId": "sess_impl_1"},
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        docs = self._job_docs(task_id, "plan")
        self.assertEqual(len(docs), 2)
        self.assertEqual(
            [doc["idempotencyKey"].split(":")[4] for doc in docs],
            ["0", "1"],
        )
        for doc in docs:
            self.assertEqual(doc["agent"]["adapter"], "cursor")
            self.assertEqual(doc["agent"]["model"], "claude-opus-5-thinking-high")
        # Reviewer Stage without a stage_agents entry stays on legacy Pi.
        self.assertEqual(self._job_docs(task_id, "plan_review")[0]["agent"]["adapter"], "pi")

    def test_restart_recovers_frozen_selection_from_manifest_not_config(self) -> None:
        self.env.set_script(
            {
                "plan:1:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:1:0": {"status": "completed", "verdict": "request_changes"},
                "plan:2:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:2:0": {"status": "completed", "verdict": "approved"},
                "implement:1:0": {"status": "completed", "checks": "passed", "sessionId": "sess_impl_1"},
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self._advance_once(task_id)
        self._advance_once(task_id)
        # plan:2 (rework) now exists and is frozen as Pi in the manifest.
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["stageAgents"]["plan"]["adapter"], "pi")
        # Simulate a process restart under a completely different config: the
        # frozen manifest binding must win over re-derived config.
        self.env.stage_agents = {"plan": {"adapter": "cursor", "model": "cursor-opus-4.6", "thinking": "high"}}
        self.env.agents = {
            key: {"adapter": "cursor", "model": "cursor-opus-4.6", "thinking": "high"}
            for key in AGENTS
        }
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        docs = self._job_docs(task_id, "plan")
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[1]["agent"]["adapter"], "pi")
        self.assertEqual(docs[1]["agent"]["model"], "planner-model")
        self.assertEqual(docs[1]["agent"]["sessionId"], "sess_plan_1")

    def test_restart_recovers_frozen_selection_from_prior_job_without_binding(self) -> None:
        """Legacy manifests without stageAgents recover from the prior Job doc."""
        self.env.set_script(
            {
                "plan:1:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:1:0": {"status": "completed", "verdict": "request_changes"},
                "plan:2:0": {"status": "completed", "sessionId": "sess_plan_1"},
                "plan_review:2:0": {"status": "completed", "verdict": "approved"},
                "implement:1:0": {"status": "completed", "checks": "passed", "sessionId": "sess_impl_1"},
            }
        )
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        # Stop after plan:1 is consumed: only plan:1 and plan_review:1 exist.
        self._advance_once(task_id)
        manifest = self.env.store.get_manifest("project-board", task_id)
        stripped = dict(manifest)
        stripped.pop("stageAgents", None)
        stripped["revision"] = int(manifest["revision"]) + 1
        self.env.store.cas_update_manifest(
            "project-board",
            task_id,
            expected_revision=int(manifest["revision"]),
            manifest=stripped,
        )
        # plan:2 must adopt plan:1's persisted selection instead of the new config.
        self.env.stage_agents = {"plan": {"adapter": "cursor", "model": "cursor-opus-4.6", "thinking": "high"}}
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        docs = self._job_docs(task_id, "plan")
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[1]["agent"]["adapter"], "pi")
        self.assertEqual(docs[1]["agent"]["model"], "planner-model")
        self.assertEqual(docs[1]["agent"]["sessionId"], "sess_plan_1")
        manifest = self.env.store.get_manifest("project-board", task_id)
        self.assertEqual(manifest["stageAgents"]["plan"]["adapter"], "pi")

    def test_default_config_keeps_current_pi_behavior(self) -> None:
        created = self.env.enqueue()
        task_id = created["task_id"]
        self.env.kanban.claim_ready(task_id)
        self.env.advance_until(task_id=task_id, statuses={"review_requested"})
        self.env.kanban.claim_review(task_id, run_id="2")
        self.env.advance_until(task_id=task_id, run_id="2", outcomes={"acceptance_required"})
        manifest = self.env.store.get_manifest("project-board", task_id)
        for stage in ("plan", "plan_review", "implement", "execute_review"):
            doc = self._job_docs(task_id, stage)[0]
            self.assertEqual(doc["agent"]["adapter"], "pi", stage)
            self.assertEqual(manifest["stageAgents"][stage]["adapter"], "pi", stage)


if __name__ == "__main__":
    unittest.main()
