"""Focused tests for Origin-side Development Workflow operations and tools.

Bootstrap mirrors ``test_harness_context.py``: drop the plugin directory from
``sys.path``, load the plugin package via ``spec_from_file_location``, and run
against an isolated temporary ``HERMES_HOME``.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parent.parent

for _entry in list(sys.path):
    try:
        if Path(_entry).resolve() == PLUGIN_DIR:
            sys.path.remove(_entry)
    except OSError:
        continue

try:
    import hermes_cli.kanban_db  # noqa: F401
except ImportError:
    _runtime_candidates = [
        Path.home() / ".hermes" / "hermes-agent",
        Path("/Users/kenan/.hermes/hermes-agent"),
    ]
    for _candidate in _runtime_candidates:
        if (_candidate / "hermes_cli" / "kanban_db.py").exists():
            sys.path.insert(0, str(_candidate))
            break
    import hermes_cli.kanban_db  # noqa: F401

from hermes_cli import kanban_db as kb

_MODULE_NAME = "devwf_test_development_workflow"


def _load_plugin_package():
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    init_file = PLUGIN_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, init_file, submodule_search_locations=[str(PLUGIN_DIR)]
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load plugin package from {init_file}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _MODULE_NAME
    module.__path__ = [str(PLUGIN_DIR)]
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_plugin = _load_plugin_package()
hermes_adapter = importlib.import_module(_MODULE_NAME + ".harness.hermes_adapter")
contracts = importlib.import_module(_MODULE_NAME + ".harness.contracts")
errors = importlib.import_module(_MODULE_NAME + ".harness.errors")
policy = importlib.import_module(_MODULE_NAME + ".harness.policy")
operations_origin = importlib.import_module(_MODULE_NAME + ".harness.operations_origin")
tools_origin = importlib.import_module(_MODULE_NAME + ".harness.tools_origin")

HermesAdapter = hermes_adapter.HermesAdapter
HarnessError = errors.HarnessError
parse_stage_body = contracts.parse_stage_body
validate_stage_card = contracts.validate_stage_card
parse_decision_comment = contracts.parse_decision_comment

_SCRUB_ENV_VARS = (
    "HERMES_KANBAN_DB",
    "HERMES_KANBAN_BOARD",
    "HERMES_KANBAN_HOME",
    "HERMES_KANBAN_WORKSPACES_ROOT",
    "HERMES_KANBAN_WORKSPACE",
    "HERMES_KANBAN_TASK",
    "HERMES_KANBAN_RUN_ID",
    "HERMES_KANBAN_CLAIM_LOCK",
    "HERMES_DELEGATED_CHILD_CONTEXT",
    "HERMES_KANBAN_STOP_NUDGE",
    "HERMES_DEVFLOW_ARTIFACTS_ROOT",
    "HERMES_HOME",
)

SHA1 = "b" * 40
PINNED_SKILLS = ["development-orchestrator", "pi-delegate"]


def v2_body(
    *,
    schema: str = "development-stage.v2",
    feature_id: str = "ship-guard",
    stage: str = "direct",
    intent: str = "converged",
    ui_acceptance: str = "not-required",
    coding_agent: str = "pi",
    manual_acceptance: str = "[]",
    accepted_plan: str = "null",
    extra_frontmatter: str = "",
    goal: str = "Ship the guard.",
    acceptance: str = "- doctor passes.",
    included_scope: str = "- the plugin",
    non_goals: str = "- Hermes Core changes",
    settled_decisions: str = "- reuse specify_triage_task()",
    open_decisions: str = "None",
    repository_grounding: str = "- dotfile plugin path",
    authority_boundaries: str = "- no commits, no pushes",
) -> str:
    frontmatter = [
        "---",
        f"schema: {schema}",
        f"feature_id: {feature_id}",
        f"stage: {stage}",
        f"intent: {intent}",
        f"ui_acceptance: {ui_acceptance}",
        f"manual_acceptance: {manual_acceptance}",
        f"coding_agent: {coding_agent}",
        f"accepted_plan: {accepted_plan}",
    ]
    if extra_frontmatter:
        frontmatter.append(extra_frontmatter.rstrip("\n"))
    names_and_content = [
        ("Goal", goal),
        ("Observable acceptance", acceptance),
        ("Included scope", included_scope),
        ("Non-goals", non_goals),
        ("Settled decisions", settled_decisions),
        ("Open decisions", open_decisions),
        ("Repository grounding", repository_grounding),
        ("Authority boundaries", authority_boundaries),
    ]
    body = "\n".join(frontmatter) + "\n---\n\n"
    body += "\n\n".join(f"# {name}\n\n{content}" for name, content in names_and_content)
    return body + "\n"


def accepted_plan_yaml(*, card_id: str, path: str, sha256: str) -> str:
    return (
        "\n"
        f"  card_id: {card_id}\n"
        f"  path: {path}\n"
        f"  sha256: {sha256}"
    )


class IsolatedOriginHome(unittest.TestCase):
    """Fresh HERMES_HOME, compatible kanban config, and pi adapter stubs."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / ".hermes"
        self.home.mkdir()
        self._env_backup = os.environ.copy()
        self.addCleanup(self._restore_env)
        os.environ["HERMES_HOME"] = str(self.home)
        for var in _SCRUB_ENV_VARS:
            if var == "HERMES_HOME":
                continue
            os.environ.pop(var, None)
        self._orig_path_home = Path.home
        Path.home = lambda: Path(self._tmp.name)  # type: ignore[assignment]
        self.addCleanup(setattr, Path, "home", self._orig_path_home)

        (self.home / "config.yaml").write_text(
            "kanban:\n"
            "  max_in_progress: 1\n"
            "  max_in_progress_per_profile: 1\n"
            "  review_dispatch: true\n",
            encoding="utf-8",
        )
        relay = self.home / policy.PI_RELAY_SCRIPT_RELPATH
        relay.parent.mkdir(parents=True, exist_ok=True)
        relay.write_text("// relay stub\n", encoding="utf-8")
        handoff = Path(self._tmp.name) / "Secret-Projects" / "pi-auto-handoff"
        (handoff / "src").mkdir(parents=True, exist_ok=True)
        (handoff / "package.json").write_text("{}", encoding="utf-8")
        (handoff / "src" / "index.ts").write_text("export {}\n", encoding="utf-8")

        kb.init_db()
        self.adapter = HermesAdapter(home=self.home)
        self.repo = (Path(self._tmp.name) / "feature-repo").resolve()
        self.repo.mkdir()
        init = subprocess.run(
            ["git", "init"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(init.returncode, 0, init.stderr)

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def payload(self, op, **kwargs) -> dict:
        try:
            result = op(self.adapter, **kwargs)
        except HarnessError as err:
            return err.to_payload()
        self.assertIsInstance(result, dict)
        return result

    def create_feature(self, **kwargs) -> dict:
        defaults = dict(
            route="direct",
            feature_id="ship-guard",
            title="Ship the guard",
            goal="Ship the external execution guard.",
            repo=str(self.repo),
            coding_agent="pi",
        )
        defaults.update(kwargs)
        return self.payload(operations_origin.op_create_feature, **defaults)

    def _bind_worker_env(self, task) -> None:
        os.environ["HERMES_KANBAN_TASK"] = task.id
        os.environ["HERMES_KANBAN_RUN_ID"] = str(task.current_run_id)
        os.environ["HERMES_KANBAN_CLAIM_LOCK"] = task.claim_lock

    def _complete_ready_card(self, task_id: str, metadata: dict | None = None) -> None:
        conn = self.adapter.connect()
        try:
            claimed = self.adapter.claim_task(conn, task_id)
            self.assertIsNotNone(claimed)
            ok = self.adapter.complete_task(
                conn,
                task_id,
                result="done",
                expected_run_id=claimed.current_run_id,
                metadata=metadata,
            )
            self.assertTrue(ok)
        finally:
            self.adapter.close(conn)

    def _pass_write_plan_review(self, task_id: str, accepted_plan: dict) -> None:
        """Claim implement, request review, then review-complete with PASS metadata."""
        conn = self.adapter.connect()
        try:
            claimed = self.adapter.claim_task(conn, task_id)
            self.assertIsNotNone(claimed)
            requested = self.adapter.request_review(
                conn,
                task_id,
                expected_run_id=claimed.current_run_id,
                metadata={"accepted_plan": accepted_plan},
            )
            self.assertTrue(requested)
            reviewed = self.adapter.claim_review_task(conn, task_id)
            self.assertIsNotNone(reviewed)
            completed = self.adapter.complete_task(
                conn,
                task_id,
                result="PASS",
                expected_run_id=reviewed.current_run_id,
                metadata={"accepted_plan": accepted_plan},
            )
            self.assertTrue(completed)
        finally:
            self.adapter.close(conn)

    def _feature_task_ids(self, feature_id: str) -> list[str]:
        conn = self.adapter.connect()
        try:
            ids: list[str] = []
            for task in self.adapter.list_tasks(conn, include_archived=False) or []:
                try:
                    card = parse_stage_body(task.body or "")
                except Exception:
                    continue
                if card.feature_id == feature_id:
                    ids.append(task.id)
            return ids
        finally:
            self.adapter.close(conn)

    def _write_plan_file(self, name: str = "accepted-plan.md") -> tuple[Path, str]:
        path = Path(self._tmp.name) / "plans" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Accepted plan\n\nDo the work.\n", encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return path, digest

    def _plan_identity(self, card_id: str, path: Path, digest: str) -> dict:
        return {"card_id": card_id, "path": str(path), "sha256": digest}

    def _assert_created_workspace(self, result: dict, *, stages: list[str]) -> None:
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("repo"), str(self.repo))
        self.assertEqual(result.get("workspace_kind"), "dir")
        self.assertEqual(result.get("skills"), PINNED_SKILLS)
        cards = result.get("cards") or []
        self.assertEqual([item["stage"] for item in cards], stages)
        conn = self.adapter.connect()
        try:
            for item in cards:
                task = self.adapter.get_task(conn, item["task_id"])
                self.assertIsNotNone(task)
                self.assertEqual(task.assignee, "default")
                self.assertEqual(task.workspace_kind, "dir")
                self.assertEqual(task.workspace_path, str(self.repo))
                self.assertEqual(sorted(task.skills or []), sorted(PINNED_SKILLS))
                self.assertEqual(task.status, "triage")
                self.assertEqual(item.get("assignee"), "default")
                self.assertEqual(item.get("workspace_kind"), "dir")
                self.assertEqual(item.get("workspace_path"), str(self.repo))
                self.assertEqual(sorted(item.get("skills") or []), sorted(PINNED_SKILLS))
        finally:
            self.adapter.close(conn)


class TestCreateFeature(IsolatedOriginHome):
    def test_create_direct_draft(self) -> None:
        result = self.create_feature(route="direct")
        self._assert_created_workspace(result, stages=["direct"])
        self.assertEqual(result.get("route"), "direct")
        self.assertEqual(result.get("feature_id"), "ship-guard")
        cards = result.get("cards") or []
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["status"], "triage")
        conn = self.adapter.connect()
        try:
            task = self.adapter.get_task(conn, cards[0]["task_id"])
            card = parse_stage_body(task.body)
            self.assertEqual(validate_stage_card(card, require="draft"), [])
            self.assertEqual(card.feature_id, "ship-guard")
            self.assertEqual(card.stage, "direct")
        finally:
            self.adapter.close(conn)

    def test_create_two_stage_pair(self) -> None:
        result = self.create_feature(route="two-stage", feature_id="obsidian-ui")
        self._assert_created_workspace(
            result, stages=["write-plan", "execute-plan"]
        )
        cards = result.get("cards") or []
        self.assertEqual(cards[0]["status"], "triage")
        self.assertEqual(cards[1]["status"], "triage")
        self.assertNotEqual(cards[1]["status"], "ready")
        wp_id = cards[0]["task_id"]
        ex_id = cards[1]["task_id"]
        conn = self.adapter.connect()
        try:
            wp = self.adapter.get_task(conn, wp_id)
            ex = self.adapter.get_task(conn, ex_id)
            wp_card = parse_stage_body(wp.body)
            ex_card = parse_stage_body(ex.body)
            self.assertEqual(wp_card.feature_id, "obsidian-ui")
            self.assertEqual(ex_card.feature_id, "obsidian-ui")
            self.assertEqual(wp_card.stage, "write-plan")
            self.assertEqual(ex_card.stage, "execute-plan")
            self.assertEqual(self.adapter.parent_ids(conn, ex_id), [wp_id])
            self.assertEqual(ex.status, "triage")
        finally:
            self.adapter.close(conn)

    def test_duplicate_feature_stage_conflict(self) -> None:
        first = self.create_feature(feature_id="ship-guard")
        self.assertTrue(first.get("ok"), first)
        second = self.create_feature(feature_id="ship-guard")
        self.assertFalse(second.get("ok"))
        self.assertEqual(second.get("code"), errors.FEATURE_STAGE_CONFLICT)
        details = second.get("details") or {}
        self.assertIn("existing_task_ids", details)
        self.assertEqual(
            details["existing_task_ids"],
            [first["cards"][0]["task_id"]],
        )

    def test_same_feature_different_stages_ok(self) -> None:
        result = self.create_feature(route="two-stage", feature_id="shared-feat")
        self.assertTrue(result.get("ok"), result)
        stages = [item["stage"] for item in (result.get("cards") or [])]
        self.assertEqual(stages, ["write-plan", "execute-plan"])
        self.assertEqual(len(self._feature_task_ids("shared-feat")), 2)

    def test_two_stage_duplicate_conflicts(self) -> None:
        first = self.create_feature(route="two-stage", feature_id="dup-pair")
        self.assertTrue(first.get("ok"), first)
        second = self.create_feature(route="two-stage", feature_id="dup-pair")
        self.assertFalse(second.get("ok"))
        self.assertEqual(second.get("code"), errors.FEATURE_STAGE_CONFLICT)

    def test_repo_relative_path_rejected(self) -> None:
        result = self.create_feature(repo="relative/repo")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.WORKSPACE_INVALID)

    def test_repo_missing_dir_rejected(self) -> None:
        missing = Path(self._tmp.name) / "no-such-repo"
        result = self.create_feature(repo=str(missing))
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.WORKSPACE_INVALID)

    def test_repo_non_git_dir_rejected(self) -> None:
        plain = (Path(self._tmp.name) / "not-git").resolve()
        plain.mkdir()
        result = self.create_feature(repo=str(plain))
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.WORKSPACE_INVALID)

    def test_two_stage_second_card_readback_rolls_back_pair(self) -> None:
        real_create = self.adapter.create_task
        real_get = self.adapter.get_task
        created_ids: list[str] = []

        def create_wrapper(conn, **kwargs):
            task_id = real_create(conn, **kwargs)
            created_ids.append(task_id)
            return task_id

        def get_wrapper(conn, task_id):
            task = real_get(conn, task_id)
            if created_ids and task_id == created_ids[-1] and len(created_ids) >= 2:
                return None
            return task

        with patch.object(self.adapter, "create_task", side_effect=create_wrapper):
            with patch.object(self.adapter, "get_task", side_effect=get_wrapper):
                result = self.create_feature(
                    route="two-stage", feature_id="atomic-fail"
                )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.HARNESS_STATE_UNAVAILABLE)
        self.assertEqual(self._feature_task_ids("atomic-fail"), [])

    def test_bad_route_rejected(self) -> None:
        result = self.create_feature(route="plan-driven")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)

    def test_bad_feature_id_rejected(self) -> None:
        result = self.create_feature(feature_id="Not_Kebab")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)

    def test_non_origin_role_rejected(self) -> None:
        with patch.object(self.adapter, "active_profile_name", return_value="coder"):
            result = self.create_feature()
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.ORIGIN_ROLE_REQUIRED)
        self.assertEqual((result.get("current_state") or {}).get("role"), "unmanaged")

    def test_kanban_config_precondition_failure(self) -> None:
        with patch.object(
            self.adapter,
            "kanban_config",
            return_value={
                "max_in_progress": 2,
                "max_in_progress_per_profile": 1,
                "review_dispatch": True,
            },
        ):
            result = self.create_feature()
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.HARNESS_INCOMPATIBLE)
        self.assertIn("max_in_progress", result.get("details") or {})
        self.assertEqual((result.get("details") or {}).get("max_in_progress"), 2)


class TestRecordDecision(IsolatedOriginHome):
    def test_intent_decision_persists_and_round_trips(self) -> None:
        created = self.create_feature()
        task_id = created["cards"][0]["task_id"]
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=task_id,
            kind="intent-decision",
            decision="use pi as the coding agent",
        )
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("task_id"), task_id)
        self.assertIsInstance(result.get("comment_id"), int)
        echoed = result.get("decision") or {}
        self.assertEqual(echoed.get("kind"), "intent-decision")
        self.assertEqual(echoed.get("decided_by"), "origin")
        conn = self.adapter.connect()
        try:
            comments = self.adapter.list_comments(conn, task_id)
            self.assertTrue(comments)
            parsed = parse_decision_comment(comments[-1].body)
            self.assertEqual(parsed, echoed)
        finally:
            self.adapter.close(conn)

    def test_manual_verdict_without_commit_rejected(self) -> None:
        created = self.create_feature()
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=created["cards"][0]["task_id"],
            kind="manual-verdict",
            decision="PASS",
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        violations = (result.get("details") or {}).get("violations") or []
        self.assertTrue(any("candidate_commit" in item for item in violations))

    def test_amendment_on_triage_refused(self) -> None:
        created = self.create_feature()
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=created["cards"][0]["task_id"],
            kind="amendment",
            decision="drop the extra pane",
            affects_accepted_plan=True,
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        self.assertIn("after finalization", result.get("message") or "")

    def test_amendment_without_affects_flag_rejected(self) -> None:
        created = self.create_feature()
        task_id = created["cards"][0]["task_id"]
        finalized = self.payload(
            operations_origin.op_finalize_stage, task_id=task_id, body=v2_body()
        )
        self.assertTrue(finalized.get("ok"), finalized)
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=task_id,
            kind="amendment",
            decision="drop the extra pane",
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        violations = (result.get("details") or {}).get("violations") or []
        self.assertTrue(any("affects_accepted_plan" in item for item in violations))

    def test_intent_decision_on_ready_card_refused(self) -> None:
        created = self.create_feature()
        task_id = created["cards"][0]["task_id"]
        finalized = self.payload(
            operations_origin.op_finalize_stage, task_id=task_id, body=v2_body()
        )
        self.assertTrue(finalized.get("ok"), finalized)
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=task_id,
            kind="intent-decision",
            decision="too late for draft intent",
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        self.assertIn("draft convergence", result.get("message") or "")

    def test_manual_verdict_without_verdict_rejected(self) -> None:
        created = self.create_feature()
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=created["cards"][0]["task_id"],
            kind="manual-verdict",
            decision="human pass",
            candidate_commit=SHA1,
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        violations = (result.get("details") or {}).get("violations") or []
        self.assertTrue(any("verdict" in item for item in violations))

    def test_manual_verdict_with_verdict_and_commit_ok(self) -> None:
        created = self.create_feature()
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=created["cards"][0]["task_id"],
            kind="manual-verdict",
            decision="human pass",
            verdict="PASS",
            candidate_commit=SHA1,
        )
        self.assertTrue(result.get("ok"), result)
        echoed = result.get("decision") or {}
        self.assertEqual(echoed.get("verdict"), "PASS")
        self.assertEqual(echoed.get("candidate_commit"), SHA1)

    def test_round_authorization_on_triage_refused(self) -> None:
        created = self.create_feature()
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=created["cards"][0]["task_id"],
            kind="round-authorization",
            decision="authorize round 1",
            round=1,
            candidate_commit=SHA1,
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        self.assertIn("after finalization", result.get("message") or "")

    def test_round_authorization_after_finalize(self) -> None:
        created = self.create_feature()
        task_id = created["cards"][0]["task_id"]
        finalized = self.payload(
            operations_origin.op_finalize_stage, task_id=task_id, body=v2_body()
        )
        self.assertTrue(finalized.get("ok"), finalized)
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=task_id,
            kind="round-authorization",
            decision="authorize round 2",
            round=2,
            candidate_commit=SHA1,
        )
        self.assertTrue(result.get("ok"), result)
        echoed = result.get("decision") or {}
        self.assertEqual(echoed.get("kind"), "round-authorization")
        self.assertEqual(echoed.get("round"), 2)
        self.assertEqual(echoed.get("candidate_commit"), SHA1)

    def test_round_authorization_invalid_round_rejected(self) -> None:
        created = self.create_feature()
        task_id = created["cards"][0]["task_id"]
        finalized = self.payload(
            operations_origin.op_finalize_stage, task_id=task_id, body=v2_body()
        )
        self.assertTrue(finalized.get("ok"), finalized)
        result = self.payload(
            operations_origin.op_record_decision,
            task_id=task_id,
            kind="round-authorization",
            decision="bad round",
            round=0,
            candidate_commit=SHA1,
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        violations = (result.get("details") or {}).get("violations") or []
        self.assertTrue(any("round" in item for item in violations))

    def test_non_origin_role_rejected(self) -> None:
        created = self.create_feature()
        with patch.object(self.adapter, "active_profile_name", return_value="coder"):
            result = self.payload(
                operations_origin.op_record_decision,
                task_id=created["cards"][0]["task_id"],
                kind="intent-decision",
                decision="use pi",
            )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.ORIGIN_ROLE_REQUIRED)


class TestFinalizeStage(IsolatedOriginHome):
    def test_finalize_direct_lands_ready(self) -> None:
        created = self.create_feature()
        task_id = created["cards"][0]["task_id"]
        body = v2_body()
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=task_id,
            body=body,
            title="Ship the guard (converged)",
        )
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("status"), "ready")
        self.assertFalse(result.get("parent_gated"))
        self.assertEqual(
            result.get("verified"),
            {
                "body": True,
                "assignee": True,
                "status": True,
                "specified_event": True,
            },
        )
        conn = self.adapter.connect()
        try:
            task = self.adapter.get_task(conn, task_id)
            self.assertEqual(task.status, "ready")
            self.assertEqual(task.body, body)
            self.assertEqual(task.assignee, "default")
        finally:
            self.adapter.close(conn)

    def test_open_decisions_not_none_rejected(self) -> None:
        created = self.create_feature()
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=created["cards"][0]["task_id"],
            body=v2_body(open_decisions="- which renderer?"),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        violations = (result.get("details") or {}).get("violations") or []
        self.assertTrue(any("Open decisions" in item for item in violations))

    def test_manual_acceptance_with_ui_not_required_rejected(self) -> None:
        created = self.create_feature()
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=created["cards"][0]["task_id"],
            body=v2_body(
                ui_acceptance="not-required",
                manual_acceptance='["click through the flow"]',
            ),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        violations = (result.get("details") or {}).get("violations") or []
        self.assertTrue(any("manual_acceptance" in item for item in violations))

    def test_unknown_frontmatter_key_rejected(self) -> None:
        created = self.create_feature()
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=created["cards"][0]["task_id"],
            body=v2_body(extra_frontmatter="complexity: simple"),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        violations = (result.get("details") or {}).get("violations") or []
        self.assertTrue(any("complexity" in item for item in violations))

    def test_finalize_rejects_changed_feature_id(self) -> None:
        created = self.create_feature(feature_id="ship-guard")
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=created["cards"][0]["task_id"],
            body=v2_body(feature_id="other-feature"),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        self.assertIn(
            "feature_id", (result.get("details") or {}).get("changed_fields") or []
        )

    def test_finalize_rejects_changed_stage(self) -> None:
        created = self.create_feature(feature_id="ship-guard")
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=created["cards"][0]["task_id"],
            body=v2_body(feature_id="ship-guard", stage="write-plan"),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        self.assertIn("stage", (result.get("details") or {}).get("changed_fields") or [])

    def test_finalize_rejects_changed_coding_agent(self) -> None:
        created = self.create_feature(feature_id="ship-guard")
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=created["cards"][0]["task_id"],
            body=v2_body(coding_agent="cursor"),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        self.assertIn(
            "coding_agent", (result.get("details") or {}).get("changed_fields") or []
        )

    def test_non_triage_refused(self) -> None:
        conn = self.adapter.connect()
        try:
            ready_id = self.adapter.create_task(
                conn, title="Already ready", assignee="default"
            )
        finally:
            self.adapter.close(conn)
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=ready_id,
            body=v2_body(),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        self.assertEqual((result.get("details") or {}).get("status"), "ready")

    def test_finalize_execute_after_write_plan_done(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="two-stage-ship")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        wp_result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=wp_id,
            body=v2_body(feature_id="two-stage-ship", stage="write-plan"),
        )
        self.assertTrue(wp_result.get("ok"), wp_result)
        self.assertEqual(wp_result.get("status"), "ready")
        plan_path, digest = self._write_plan_file()
        identity = self._plan_identity(wp_id, plan_path, digest)
        self._pass_write_plan_review(wp_id, identity)

        ex_body = v2_body(
            feature_id="two-stage-ship",
            stage="execute-plan",
            accepted_plan=accepted_plan_yaml(
                card_id=wp_id, path=str(plan_path), sha256=digest
            ),
        )
        ex_result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=ex_id,
            body=ex_body,
        )
        self.assertTrue(ex_result.get("ok"), ex_result)
        self.assertEqual(ex_result.get("status"), "ready")
        self.assertFalse(ex_result.get("parent_gated"))

    def test_execute_pass_metadata_sha_mismatch_rejected(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="pass-meta")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="pass-meta", stage="write-plan"),
            ).get("ok")
        )
        plan_path, digest = self._write_plan_file("live-plan.md")
        other_path = Path(self._tmp.name) / "plans" / "other-plan.md"
        other_path.write_text("# Other plan\n\nDifferent contents.\n", encoding="utf-8")
        other_digest = hashlib.sha256(other_path.read_bytes()).hexdigest()
        self.assertNotEqual(digest, other_digest)
        mismatched = self._plan_identity(wp_id, other_path, other_digest)
        self._pass_write_plan_review(wp_id, mismatched)
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=ex_id,
            body=v2_body(
                feature_id="pass-meta",
                stage="execute-plan",
                accepted_plan=accepted_plan_yaml(
                    card_id=wp_id, path=str(plan_path), sha256=digest
                ),
            ),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        self.assertIn("PASS handoff", result.get("message") or "")
        details = result.get("details") or {}
        self.assertEqual((details.get("expected") or {}).get("sha256"), digest)
        self.assertEqual((details.get("actual") or {}).get("sha256"), other_digest)

    def test_execute_sha_mismatch(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="sha-miss")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="sha-miss", stage="write-plan"),
            ).get("ok")
        )
        self._complete_ready_card(wp_id)
        plan_path, _digest = self._write_plan_file()
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=ex_id,
            body=v2_body(
                feature_id="sha-miss",
                stage="execute-plan",
                accepted_plan=accepted_plan_yaml(
                    card_id=wp_id, path=str(plan_path), sha256="a" * 64
                ),
            ),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.PLAN_SHA_MISMATCH)

    def test_execute_missing_plan_file(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="no-plan")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="no-plan", stage="write-plan"),
            ).get("ok")
        )
        self._complete_ready_card(wp_id)
        missing = Path(self._tmp.name) / "plans" / "missing.md"
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=ex_id,
            body=v2_body(
                feature_id="no-plan",
                stage="execute-plan",
                accepted_plan=accepted_plan_yaml(
                    card_id=wp_id, path=str(missing), sha256="a" * 64
                ),
            ),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.PLAN_IDENTITY_MISSING)

    def test_execute_card_id_not_a_parent(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="not-parent")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="not-parent", stage="write-plan"),
            ).get("ok")
        )
        self._complete_ready_card(wp_id)
        conn = self.adapter.connect()
        try:
            decoy_id = self.adapter.create_task(
                conn, title="Decoy", assignee="default"
            )
        finally:
            self.adapter.close(conn)
        plan_path, digest = self._write_plan_file()
        result = self.payload(
            operations_origin.op_finalize_stage,
            task_id=ex_id,
            body=v2_body(
                feature_id="not-parent",
                stage="execute-plan",
                accepted_plan=accepted_plan_yaml(
                    card_id=decoy_id, path=str(plan_path), sha256=digest
                ),
            ),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)


class TestInspect(IsolatedOriginHome):
    def test_inspect_by_task_id_origin(self) -> None:
        created = self.create_feature()
        task_id = created["cards"][0]["task_id"]
        result = self.payload(
            operations_origin.op_inspect, task_id=task_id
        )
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("role"), "origin")
        self.assertEqual(result.get("task_id"), task_id)
        card = result.get("card") or {}
        self.assertEqual(card.get("stage"), "direct")
        self.assertEqual(card.get("intent"), "draft")
        self.assertIn("Open decisions not None", card.get("unmet_requirements") or [])
        self.assertEqual(
            result.get("recovery_advice"),
            "converge via devflow_record_decision then devflow_finalize_stage",
        )

    def test_inspect_by_feature_id_both_stages(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="pair-inspect")
        result = self.payload(
            operations_origin.op_inspect, feature_id="pair-inspect"
        )
        self.assertTrue(result.get("ok"), result)
        cards = result.get("cards") or []
        self.assertEqual(len(cards), 2)
        stages = [item.get("stage") for item in cards]
        self.assertEqual(stages, ["write-plan", "execute-plan"])
        self.assertEqual(
            {item["task_id"] for item in cards},
            {created["cards"][0]["task_id"], created["cards"][1]["task_id"]},
        )

    def test_inspect_duplicate_stage_refuses(self) -> None:
        created = self.create_feature(feature_id="dup-stage")
        original_id = created["cards"][0]["task_id"]
        conn = self.adapter.connect()
        try:
            original = self.adapter.get_task(conn, original_id)
            clone_id = self.adapter.create_task(
                conn,
                title="Clone",
                body=original.body,
                triage=True,
                assignee="default",
            )
        finally:
            self.adapter.close(conn)
        result = self.payload(
            operations_origin.op_inspect, feature_id="dup-stage"
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.HARNESS_STATE_UNAVAILABLE)
        candidates = (result.get("details") or {}).get("candidates") or []
        ids = {item.get("task_id") for item in candidates}
        self.assertEqual(ids, {original_id, clone_id})

    def test_worker_env_inspect_resolves_env_task(self) -> None:
        created = self.create_feature()
        task_id = created["cards"][0]["task_id"]
        body = v2_body()
        finalized = self.payload(
            operations_origin.op_finalize_stage, task_id=task_id, body=body
        )
        self.assertTrue(finalized.get("ok"), finalized)
        conn = self.adapter.connect()
        try:
            claimed = self.adapter.claim_task(conn, task_id)
            self.assertIsNotNone(claimed)
            self._bind_worker_env(claimed)
        finally:
            self.adapter.close(conn)
        result = self.payload(operations_origin.op_inspect)
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("role"), "implement-worker")
        self.assertEqual(result.get("task_id"), task_id)

    def test_unknown_card_clean_error(self) -> None:
        result = self.payload(
            operations_origin.op_inspect, task_id="t_missing"
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.HARNESS_STATE_UNAVAILABLE)
        self.assertIn("not found", result.get("message") or "")


class TestOriginToolsSurface(IsolatedOriginHome):
    def test_tools_export_and_visibility(self) -> None:
        names = [item["name"] for item in tools_origin.TOOLS]
        self.assertEqual(
            names,
            [
                "devflow_create_feature",
                "devflow_record_decision",
                "devflow_finalize_stage",
                "devflow_inspect",
            ],
        )
        for item in tools_origin.TOOLS:
            self.assertEqual(item["toolset"], "kanban")
            self.assertTrue(callable(item["handler"]))
            self.assertTrue(callable(item["check_fn"]))
        self.assertIn(
            "repo",
            tools_origin.DEVFLOW_CREATE_FEATURE_SCHEMA["parameters"]["required"],
        )
        self.assertIn(
            "round-authorization",
            tools_origin.DEVFLOW_RECORD_DECISION_SCHEMA["parameters"]["properties"]["kind"]["enum"],
        )
        self.assertTrue(tools_origin.check_origin_tools_available())
        self.assertTrue(tools_origin.check_inspect_available())

        os.environ["HERMES_KANBAN_TASK"] = "t_worker"
        self.assertFalse(tools_origin.check_origin_tools_available())
        self.assertTrue(tools_origin.check_inspect_available())
        os.environ.pop("HERMES_KANBAN_TASK", None)

        os.environ["HERMES_DELEGATED_CHILD_CONTEXT"] = "1"
        self.assertFalse(tools_origin.check_origin_tools_available())
        self.assertFalse(tools_origin.check_inspect_available())

    def test_handler_create_feature_envelope(self) -> None:
        raw = tools_origin.handle_create_feature(
            {
                "route": "direct",
                "feature_id": "via-handler",
                "title": "Via handler",
                "goal": "Prove the thin handler dispatches.",
                "repo": str(self.repo),
            }
        )
        result = json.loads(raw)
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("feature_id"), "via-handler")
        self.assertEqual(len(result.get("cards") or []), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
