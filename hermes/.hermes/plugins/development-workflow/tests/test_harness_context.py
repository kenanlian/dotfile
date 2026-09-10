"""Focused tests for HermesAdapter and session-role classification.

Runs against the real Hermes Kanban DB API with an isolated temporary
``HERMES_HOME`` per test. Bootstrap mirrors ``test_finalize_intent.py``.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
context = importlib.import_module(_MODULE_NAME + ".harness.context")
errors = importlib.import_module(_MODULE_NAME + ".harness.errors")

HermesAdapter = hermes_adapter.HermesAdapter
classify_session = context.classify_session
apply_non_owning_quarantine = context.apply_non_owning_quarantine
allowed_actions_for = context.allowed_actions_for
managed_card = context.managed_card
require_worker_card = context.require_worker_card
review_authority = context.review_authority
SessionContext = context.SessionContext

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
    "HERMES_CRON_SESSION",
)


class IsolatedKanbanHome(unittest.TestCase):
    """Fresh HERMES_HOME + empty board DB per test."""

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
        kb.init_db()
        self.adapter = HermesAdapter(home=self.home)

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _bind_worker_env(self, task) -> None:
        os.environ["HERMES_KANBAN_TASK"] = task.id
        os.environ["HERMES_KANBAN_RUN_ID"] = str(task.current_run_id)
        os.environ["HERMES_KANBAN_CLAIM_LOCK"] = task.claim_lock


class TestAdapterProbe(unittest.TestCase):
    def test_probe_against_real_runtime(self) -> None:
        result = HermesAdapter().probe()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["missing"], [])
        self.assertTrue(result["capabilities"].get("create_task"))
        self.assertTrue(result["capabilities"].get("specify_triage_task"))
        self.assertTrue(result["capabilities"].get("claim_review_task"))
        self.assertTrue(result["capabilities"].get("connect"))
        self.assertTrue(result["capabilities"].get("gateway_session_context"))
        self.assertTrue(result["capabilities"].get("delegation_dispatcher_owned"))


class TestAdapterKanban(IsolatedKanbanHome):
    def test_connect_create_specify_and_claims(self) -> None:
        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn, title="Draft card", triage=True, assignee="default"
            )
            draft = self.adapter.get_task(conn, tid)
            self.assertEqual(draft.status, "triage")
            specified = self.adapter.specify_triage_task(
                conn, tid, body="specified body", assignee="default"
            )
            self.assertTrue(specified)
            fresh = self.adapter.get_task(conn, tid)
            self.assertEqual(fresh.body, "specified body")
            self.assertIn(fresh.status, ("todo", "ready"))

            ready_id = self.adapter.create_task(
                conn, title="Ready card", assignee="default"
            )
            claimed = self.adapter.claim_task(conn, ready_id)
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.status, "running")
            runs = self.adapter.list_runs(conn, ready_id)
            self.assertTrue(runs)
            self.assertIsNone(
                self.adapter.claimed_source_status(
                    conn, ready_id, claimed.current_run_id
                )
            )

            reviewed_ok = self.adapter.request_review(
                conn, ready_id, expected_run_id=claimed.current_run_id
            )
            self.assertTrue(reviewed_ok)
            reviewed = self.adapter.claim_review_task(conn, ready_id)
            self.assertIsNotNone(reviewed)
            self.assertEqual(
                self.adapter.claimed_source_status(
                    conn, ready_id, reviewed.current_run_id
                ),
                "review",
            )
            cfg = self.adapter.kanban_config()
            self.assertIsInstance(cfg, dict)
        finally:
            self.adapter.close(conn)


class TestClassifySession(IsolatedKanbanHome):
    def test_scrubbed_env_is_origin_when_profile_default(self) -> None:
        """Path.home is patched to the temp dir, so HERMES_HOME == ~/.hermes
        from the resolver's point of view and get_active_profile_name returns
        'default'. Origin is therefore classified without monkeypatching.
        """
        ctx = classify_session(self.adapter)
        self.assertEqual(ctx.role, "origin")
        self.assertFalse(ctx.is_worker())
        self.assertEqual(
            allowed_actions_for("origin"),
            [
                "devflow_inspect",
                "devflow_create_feature",
                "devflow_record_decision",
                "devflow_finalize_stage",
                "read",
                "exit",
            ],
        )

    def test_non_default_profile_is_unmanaged(self) -> None:
        with patch.object(self.adapter, "active_profile_name", return_value="coder"):
            ctx = classify_session(self.adapter)
        self.assertEqual(ctx.role, "unmanaged")
        self.assertIn("read", allowed_actions_for(ctx.role))

    def test_delegated_child_is_unmanaged(self) -> None:
        os.environ["HERMES_DELEGATED_CHILD_CONTEXT"] = "1"
        ctx = classify_session(self.adapter)
        self.assertEqual(ctx.role, "unmanaged")

    def test_claimed_card_is_implement_worker(self) -> None:
        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn, title="Implement me", assignee="default"
            )
            claimed = self.adapter.claim_task(conn, tid)
            self._bind_worker_env(claimed)
        finally:
            self.adapter.close(conn)
        ctx = classify_session(self.adapter)
        self.assertEqual(ctx.role, "implement-worker")
        self.assertTrue(ctx.is_worker())
        self.assertTrue(ctx.is_owning())
        self.assertEqual(ctx.env_task_id, claimed.id)
        self.assertIn("devflow_implement_handoff", allowed_actions_for(ctx.role))

    def test_review_claim_is_review_worker(self) -> None:
        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn, title="Review me", assignee="default"
            )
            claimed = self.adapter.claim_task(conn, tid)
            self.assertTrue(
                self.adapter.request_review(
                    conn, tid, expected_run_id=claimed.current_run_id
                )
            )
            reviewed = self.adapter.claim_review_task(conn, tid)
            self.assertIsNotNone(reviewed)
            self._bind_worker_env(reviewed)
        finally:
            self.adapter.close(conn)
        ctx = classify_session(self.adapter)
        self.assertEqual(ctx.role, "review-worker")
        self.assertEqual(ctx.source_status, "review")
        self.assertIn("devflow_review_verdict", allowed_actions_for(ctx.role))

    def test_mismatched_run_id_is_non_owning_and_quarantine(self) -> None:
        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn, title="Stale session", assignee="default"
            )
            claimed = self.adapter.claim_task(conn, tid)
            self._bind_worker_env(claimed)
            os.environ["HERMES_KANBAN_RUN_ID"] = str(int(claimed.current_run_id) + 99)
        finally:
            self.adapter.close(conn)
        ctx = classify_session(self.adapter)
        self.assertEqual(ctx.role, "non-owning-worker")
        self.assertTrue(ctx.is_worker())
        self.assertFalse(ctx.is_owning())
        self.assertTrue(any("session run" in item for item in ctx.reasons))
        self.assertEqual(
            ctx.current_state()["role"],
            "non-owning-worker",
        )
        apply_non_owning_quarantine()
        self.assertEqual(os.environ.get("HERMES_KANBAN_STOP_NUDGE"), "0")
        self.assertEqual(
            allowed_actions_for("non-owning-worker"),
            ["devflow_inspect", "read", "exit"],
        )

    def test_cron_context_is_not_origin(self) -> None:
        with patch.object(self.adapter, "is_cron_context", return_value=True):
            ctx = classify_session(self.adapter)
        self.assertEqual(ctx.role, "unmanaged")
        self.assertTrue(any("cron-owned" in item for item in ctx.reasons))

    def test_non_dispatcher_owned_worker_is_non_owning(self) -> None:
        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn, title="Implement me", assignee="default"
            )
            claimed = self.adapter.claim_task(conn, tid)
            self._bind_worker_env(claimed)
        finally:
            self.adapter.close(conn)
        with patch.object(
            self.adapter, "is_dispatcher_owned_worker", return_value=False
        ):
            ctx = classify_session(self.adapter)
        self.assertEqual(ctx.role, "non-owning-worker")
        self.assertTrue(
            any("dispatcher-owned" in item for item in ctx.reasons)
        )


def _stage_body(
    *,
    schema: str = "development-stage.v2",
    feature_id: str = "ship-guard",
    stage: str = "direct",
    intent: str = "draft",
    ui_acceptance: str = "pending",
    coding_agent: str = "pi",
    accepted_plan: str = "null",
    open_decisions: str = "Which renderer?",
    extra_section_break: bool = False,
) -> str:
    body = "\n".join(
        [
            "---",
            f"schema: {schema}",
            f"feature_id: {feature_id}",
            f"stage: {stage}",
            f"intent: {intent}",
            f"ui_acceptance: {ui_acceptance}",
            "manual_acceptance: []",
            f"coding_agent: {coding_agent}",
            f"accepted_plan: {accepted_plan}",
            "---",
            "",
            "# Goal",
            "",
            "Ship the guard.",
            "",
            "# Observable acceptance",
            "",
            "- doctor passes.",
            "",
            "# Included scope",
            "",
            "- the plugin",
            "",
            "# Non-goals",
            "",
            "- Hermes Core changes",
            "",
            "# Settled decisions",
            "",
            "- reuse specify_triage_task()",
            "",
            "# Open decisions",
            "",
            open_decisions,
            "",
            "# Repository grounding",
            "",
            "- dotfile plugin path",
            "",
            "# Authority boundaries",
            "",
            "- no commits, no pushes",
            "",
        ]
    )
    if extra_section_break:
        body = body.replace("# Goal\n", "# Extra\n\n# Goal\n")
    return body


def _converged_body(**kwargs) -> str:
    kwargs.setdefault("intent", "converged")
    kwargs.setdefault("ui_acceptance", "not-required")
    kwargs.setdefault("open_decisions", "None")
    return _stage_body(**kwargs)


class TestManagedCard(unittest.TestCase):
    def test_v2_is_managed_regardless_of_intent(self) -> None:
        draft = managed_card(SimpleNamespace(body=_stage_body()))
        self.assertIsNotNone(draft)
        self.assertEqual(draft.intent, "draft")
        self.assertEqual(draft.feature_id, "ship-guard")
        converged = managed_card(SimpleNamespace(body=_converged_body()))
        self.assertIsNotNone(converged)
        self.assertEqual(converged.intent, "converged")

    def test_legacy_v1_and_lookalike_are_not_managed(self) -> None:
        v1 = managed_card(
            SimpleNamespace(body=_stage_body(schema="development-task.v1"))
        )
        self.assertIsNone(v1)
        lookalike = managed_card(
            SimpleNamespace(body=_stage_body(schema="other-workflow.v9"))
        )
        self.assertIsNone(lookalike)
        self.assertIsNone(managed_card(SimpleNamespace(body="plain text")))
        self.assertIsNone(managed_card(SimpleNamespace(body=None)))
        broken = managed_card(
            SimpleNamespace(body=_stage_body(extra_section_break=True))
        )
        self.assertIsNone(broken)


class TestRequireWorkerCard(IsolatedKanbanHome):
    def _claim(
        self,
        *,
        body: str,
        assignee: str = "default",
        workspace_kind: str = "dir",
        workspace_path: str | None = None,
    ):
        if workspace_path is None:
            workspace_path = str(self._tmp.name)
        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn,
                title="Managed card",
                body=body,
                assignee=assignee,
                workspace_kind=workspace_kind,
                workspace_path=workspace_path,
            )
            claimed = self.adapter.claim_task(conn, tid)
            self.assertIsNotNone(claimed)
            self._bind_worker_env(claimed)
        finally:
            self.adapter.close(conn)
        return classify_session(self.adapter)

    def test_happy_converged_dir_workspace(self) -> None:
        ctx = self._claim(body=_converged_body())
        card = require_worker_card(self.adapter, ctx)
        self.assertEqual(card.intent, "converged")
        self.assertEqual(card.coding_agent, "pi")

    def test_not_managed_v2_is_card_contract_invalid(self) -> None:
        ctx = self._claim(body="plain card")
        with self.assertRaises(errors.HarnessError) as caught:
            require_worker_card(self.adapter, ctx)
        self.assertEqual(caught.exception.code, errors.CARD_CONTRACT_INVALID)
        self.assertIsNone(caught.exception.details.get("violations"))

    def test_draft_intent_is_card_contract_invalid_with_violations(self) -> None:
        ctx = self._claim(body=_stage_body())
        with self.assertRaises(errors.HarnessError) as caught:
            require_worker_card(self.adapter, ctx)
        self.assertEqual(caught.exception.code, errors.CARD_CONTRACT_INVALID)
        violations = caught.exception.details.get("violations") or []
        self.assertTrue(any("intent" in item for item in violations))

    def test_parse_failure_is_card_contract_invalid_with_violations(self) -> None:
        ctx = self._claim(
            body=_converged_body(extra_section_break=True)
        )
        # extra heading still has schema v2, so parse fails after schema match
        with self.assertRaises(errors.HarnessError) as caught:
            require_worker_card(self.adapter, ctx)
        self.assertEqual(caught.exception.code, errors.CARD_CONTRACT_INVALID)
        self.assertTrue(caught.exception.details.get("violations"))

    def test_foreign_assignee_is_run_not_owned(self) -> None:
        ctx = self._claim(body=_converged_body(), assignee="coder")
        with self.assertRaises(errors.HarnessError) as caught:
            require_worker_card(self.adapter, ctx)
        self.assertEqual(caught.exception.code, errors.RUN_NOT_OWNED)

    def test_unknown_coding_agent_is_adapter_capability_missing(self) -> None:
        ctx = self._claim(body=_converged_body(coding_agent="unknown-agent"))
        with patch.object(context, "validate_stage_card", return_value=[]):
            with self.assertRaises(errors.HarnessError) as caught:
                require_worker_card(self.adapter, ctx)
        self.assertEqual(caught.exception.code, errors.ADAPTER_CAPABILITY_MISSING)

    def test_scratch_workspace_is_invalid(self) -> None:
        ctx = self._claim(body=_converged_body(), workspace_kind="scratch")
        with self.assertRaises(errors.HarnessError) as caught:
            require_worker_card(self.adapter, ctx)
        self.assertEqual(caught.exception.code, errors.WORKSPACE_INVALID)

    def test_missing_workspace_directory_is_invalid(self) -> None:
        ctx = self._claim(
            body=_converged_body(),
            workspace_kind="dir",
            workspace_path=str(Path(self._tmp.name) / "missing-workspace"),
        )
        with self.assertRaises(errors.HarnessError) as caught:
            require_worker_card(self.adapter, ctx)
        self.assertEqual(caught.exception.code, errors.WORKSPACE_INVALID)


class TestReviewAuthority(IsolatedKanbanHome):
    def test_happy_live_handoff(self) -> None:
        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn, title="Review me", body=_converged_body(), assignee="default"
            )
            claimed = self.adapter.claim_task(conn, tid)
            self.assertTrue(
                self.adapter.request_review(
                    conn, tid, expected_run_id=claimed.current_run_id
                )
            )
            reviewed = self.adapter.claim_review_task(conn, tid)
            self._bind_worker_env(reviewed)
        finally:
            self.adapter.close(conn)
        ctx = classify_session(self.adapter)
        self.assertEqual(ctx.role, "review-worker")
        ok, reasons = review_authority(self.adapter, ctx)
        self.assertTrue(ok, reasons)
        self.assertEqual(reasons, [])

    def test_no_handoff(self) -> None:
        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn, title="No handoff", body=_converged_body(), assignee="default"
            )
            claimed = self.adapter.claim_task(conn, tid)
            self._bind_worker_env(claimed)
        finally:
            self.adapter.close(conn)
        implement = classify_session(self.adapter)
        ctx = SessionContext(
            role="review-worker",
            env_task_id=implement.env_task_id,
            env_run_id=implement.env_run_id,
            env_claim_lock=implement.env_claim_lock,
            board=implement.board,
            card=implement.card,
            current_run=implement.current_run,
            source_status="review",
        )
        ok, reasons = review_authority(self.adapter, ctx)
        self.assertFalse(ok)
        self.assertTrue(any("handoff" in item for item in reasons))

    def test_stale_metadata_binding_mismatch(self) -> None:
        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn, title="Stale binding", body=_converged_body(), assignee="default"
            )
            claimed = self.adapter.claim_task(conn, tid)
            self.assertTrue(
                self.adapter.request_review(
                    conn,
                    tid,
                    expected_run_id=claimed.current_run_id,
                    metadata={
                        "accepted_plan_sha256": "e" * 64,
                        "candidate": {"commit": "a" * 40},
                    },
                )
            )
            reviewed = self.adapter.claim_review_task(conn, tid)
            self._bind_worker_env(reviewed)
        finally:
            self.adapter.close(conn)
        ctx = classify_session(self.adapter)
        ok, reasons = review_authority(self.adapter, ctx)
        self.assertFalse(ok)
        joined = " ".join(reasons)
        self.assertTrue(
            "accepted_plan_sha256" in joined or "guard" in joined,
            reasons,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
