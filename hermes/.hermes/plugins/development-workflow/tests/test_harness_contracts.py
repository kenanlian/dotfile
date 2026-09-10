"""Focused tests for harness contracts, decisions, evidence, and policy.

Runs with the installed Hermes interpreter so PyYAML matches the plugin
runtime. Kanban is not required for this file.

Bootstrap mirrors ``test_finalize_intent.py``: drop the plugin directory from
``sys.path`` (it contains ``tools.py``), then load the plugin package via
``spec_from_file_location`` so ``harness`` is a real subpackage.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

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
contracts = importlib.import_module(_MODULE_NAME + ".harness.contracts")
policy = importlib.import_module(_MODULE_NAME + ".harness.policy")
errors = importlib.import_module(_MODULE_NAME + ".harness.errors")

SHA256 = "a" * 64
SHA1 = "b" * 40
PLAN_PATH = "/tmp/accepted-plan.md"


def stage_body(
    *,
    schema: str = "development-stage.v2",
    feature_id: str = "ship-guard",
    stage: str = "direct",
    intent: str = "draft",
    ui_acceptance: str = "pending",
    coding_agent: str = "pi",
    manual_acceptance: str = "[]",
    accepted_plan: str = "null",
    extra_frontmatter: str = "",
    goal: str = "Ship the guard.",
    acceptance: str = "- doctor passes.",
    included_scope: str = "- the plugin",
    non_goals: str = "- Hermes Core changes",
    settled_decisions: str = "- reuse specify_triage_task()",
    open_decisions: str = "Which renderer?",
    repository_grounding: str = "- dotfile plugin path",
    authority_boundaries: str = "- no commits, no pushes",
    section_order: tuple[str, ...] | None = None,
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
    if section_order is not None:
        by_name = dict(names_and_content)
        names_and_content = [(name, by_name[name]) for name in section_order]
    body = "\n".join(frontmatter) + "\n---\n\n"
    body += "\n\n".join(f"# {name}\n\n{content}" for name, content in names_and_content)
    return body + "\n"


def execute_plan_identity() -> str:
    return (
        "\n"
        f"  card_id: t_writeplan\n"
        f"  path: {PLAN_PATH}\n"
        f"  sha256: {SHA256}"
    )


def valid_candidate(**overrides):
    data = {
        "schema": contracts.CANDIDATE_SCHEMA_ID,
        "board": "default",
        "card_id": "t_card",
        "feature_id": "ship-guard",
        "stage": "direct",
        "implement_run_id": 7,
        "attempt_number": 1,
        "candidate_commit": SHA1,
        "diff_base": "c" * 40,
        "diff_head": SHA1,
        "accepted_plan": None,
        "created_at": "2026-09-10T00:00:00Z",
    }
    data.update(overrides)
    return data


def valid_execute_review(**overrides):
    data = {
        "schema": contracts.EXECUTE_REVIEW_SCHEMA_ID,
        "card_id": "t_card",
        "review_run_id": 9,
        "round": 1,
        "candidate_commit": SHA1,
        "accepted_plan_sha256": SHA256,
        "patch_gate": {"verdict": "pass", "findings": []},
        "plan_conformance_gate": {"verdict": "pass", "findings": []},
        "overall": {"verdict": "pass"},
    }
    data.update(overrides)
    return data


def valid_ui_evidence(**overrides):
    data = {
        "schema": contracts.UI_EVIDENCE_SCHEMA_ID,
        "board": "default",
        "card_id": "t_card",
        "feature_id": "ship-guard",
        "stage": "direct",
        "run_id": 7,
        "attempt_number": 1,
        "candidate_commit": SHA1,
        "diff_base": "c" * 40,
        "diff_head": SHA1,
        "accepted_plan": None,
        "relay_session_id": "relay-1",
        "artifacts": [{"path": "/tmp/ui/shot.png", "sha256": SHA256}],
        "lease": {
            "resource": "obsidian:acceptance",
            "lease_id": "lease-1",
            "holder_run_id": 7,
            "acquired_at": "2026-09-10T00:00:00Z",
            "released_at": "2026-09-10T00:01:00Z",
        },
        "scenarios": [{"name": "open the note and confirm the heading", "verdict": "PASS"}],
        "verdict": "PASS",
        "automation_boundary": "obsidian renderer",
        "cleanup": "released",
        "created_at": "2026-09-10T00:00:00Z",
    }
    data.update(overrides)
    return data


def valid_plan_review(**overrides):
    data = {
        "schema": contracts.PLAN_REVIEW_SCHEMA_ID,
        "board": "default",
        "card_id": "t_card",
        "feature_id": "ship-guard",
        "review_run_id": 9,
        "round": 1,
        "plan": {"path": PLAN_PATH, "sha256": SHA256},
        "verdict": "pass",
        "summary": "Plan is ready to execute.",
        "required_revisions": [],
    }
    data.update(overrides)
    return data


class TestHarnessErrorEnvelope(unittest.TestCase):
    def test_to_payload_omits_none_fields(self) -> None:
        err = errors.HarnessError("RUN_OWNERSHIP_LOST", "lost")
        self.assertEqual(
            err.to_payload(),
            {"ok": False, "code": "RUN_OWNERSHIP_LOST", "message": "lost"},
        )

    def test_ok_and_error_json(self) -> None:
        ok = json.loads(errors.ok_result({"task_id": "t_1", "ok": False}))
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["task_id"], "t_1")
        err = errors.failure(
            errors.CARD_CONTRACT_INVALID,
            "bad",
            current_state={"role": "origin"},
            allowed_actions=["read"],
            remediation="fix the body",
            violations=["x"],
        )
        payload = json.loads(errors.error_result(err))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["details"], {"violations": ["x"]})


class TestStageCardParseValidate(unittest.TestCase):
    def test_draft_parse_and_validate_ok(self) -> None:
        card = contracts.parse_stage_body(stage_body())
        self.assertEqual(card.stage, "direct")
        self.assertEqual(card.intent, "draft")
        self.assertEqual(card.feature_id, "ship-guard")
        self.assertIsNone(card.accepted_plan)
        self.assertEqual(contracts.validate_stage_card(card, require="draft"), [])

    def test_converged_direct_ok(self) -> None:
        body = stage_body(
            intent="converged",
            ui_acceptance="not-required",
            open_decisions="None",
        )
        card = contracts.parse_stage_body(body)
        self.assertEqual(contracts.validate_stage_card(card, require="converged"), [])

    def test_converged_execute_plan_with_identity_ok(self) -> None:
        body = stage_body(
            stage="execute-plan",
            intent="converged",
            ui_acceptance="required",
            manual_acceptance='["click through the flow"]',
            accepted_plan=execute_plan_identity(),
            open_decisions="None",
        )
        card = contracts.parse_stage_body(body)
        self.assertEqual(card.accepted_plan["card_id"], "t_writeplan")
        self.assertEqual(card.accepted_plan["sha256"], SHA256)
        self.assertEqual(contracts.validate_stage_card(card, require="converged"), [])

    def test_execute_plan_draft_allows_null_accepted_plan(self) -> None:
        card = contracts.parse_stage_body(stage_body(stage="execute-plan"))
        self.assertEqual(contracts.validate_stage_card(card, require="draft"), [])

    def test_unknown_frontmatter_key_is_validator_not_parse(self) -> None:
        body = stage_body(extra_frontmatter="complexity: simple")
        card = contracts.parse_stage_body(body)
        violations = contracts.validate_stage_card(card, require="draft")
        self.assertTrue(any("complexity" in item for item in violations))

    def test_bad_feature_id(self) -> None:
        card = contracts.parse_stage_body(stage_body(feature_id="Not_Kebab"))
        violations = contracts.validate_stage_card(card, require="draft")
        self.assertTrue(any("feature_id" in item for item in violations))

    def test_manual_acceptance_without_required_ui(self) -> None:
        card = contracts.parse_stage_body(
            stage_body(
                intent="converged",
                ui_acceptance="not-required",
                manual_acceptance='["click through"]',
                open_decisions="None",
            )
        )
        violations = contracts.validate_stage_card(card, require="converged")
        self.assertTrue(any("manual_acceptance" in item for item in violations))

    def test_accepted_plan_non_null_on_direct(self) -> None:
        card = contracts.parse_stage_body(
            stage_body(
                intent="converged",
                ui_acceptance="not-required",
                accepted_plan=execute_plan_identity(),
                open_decisions="None",
            )
        )
        violations = contracts.validate_stage_card(card, require="converged")
        self.assertTrue(any("accepted_plan" in item for item in violations))

    def test_wrong_sections_order_raises(self) -> None:
        body = stage_body(
            section_order=(
                "Goal",
                "Included scope",
                "Observable acceptance",
                "Non-goals",
                "Settled decisions",
                "Open decisions",
                "Repository grounding",
                "Authority boundaries",
            )
        )
        with self.assertRaises(contracts.ContractError) as caught:
            contracts.parse_stage_body(body)
        self.assertIn("sections", str(caught.exception))

    def test_substantive_empty_rejected_when_converged(self) -> None:
        card = contracts.parse_stage_body(
            stage_body(
                intent="converged",
                ui_acceptance="not-required",
                included_scope="",
                open_decisions="None",
            )
        )
        violations = contracts.validate_stage_card(card, require="converged")
        self.assertTrue(any("Included scope" in item for item in violations))

    def test_open_decisions_not_none_rejected_when_converged(self) -> None:
        card = contracts.parse_stage_body(
            stage_body(
                intent="converged",
                ui_acceptance="not-required",
                open_decisions="- which renderer?",
            )
        )
        violations = contracts.validate_stage_card(card, require="converged")
        self.assertTrue(any("Open decisions" in item for item in violations))

    def test_bad_sha_hex(self) -> None:
        identity = execute_plan_identity().replace(SHA256, "zzzz")
        card = contracts.parse_stage_body(
            stage_body(
                stage="execute-plan",
                intent="converged",
                ui_acceptance="not-required",
                accepted_plan=identity,
                open_decisions="None",
            )
        )
        violations = contracts.validate_stage_card(card, require="converged")
        self.assertTrue(any("sha256" in item for item in violations))
        self.assertTrue(
            contracts.validate_accepted_plan_identity({"card_id": "t_x", "path": "rel", "sha256": "nope"})
        )


class TestDecisionComments(unittest.TestCase):
    def test_encode_parse_round_trip(self) -> None:
        body = contracts.encode_decision_comment(
            "intent-decision",
            card_id="t_card",
            feature_id="ship-guard",
            stage="direct",
            decision="use pi",
            decided_by="origin",
            created_note="session-1",
        )
        parsed = contracts.parse_decision_comment(body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["schema"], contracts.DECISION_SCHEMA_ID)
        self.assertEqual(parsed["kind"], "intent-decision")
        self.assertEqual(contracts.validate_decision(parsed), [])
        self.assertIsNone(contracts.parse_decision_comment("just a note"))
        self.assertIsNone(contracts.parse_decision_comment('{"schema":"other"}'))

    def test_card_schema_id_frontmatter_only(self) -> None:
        self.assertEqual(
            contracts.card_schema_id(stage_body()),
            "development-stage.v2",
        )
        self.assertEqual(
            contracts.card_schema_id(stage_body(schema="development-task.v1")),
            "development-task.v1",
        )
        self.assertIsNone(contracts.card_schema_id("no frontmatter"))
        self.assertIsNone(contracts.card_schema_id("---\nitems: [1]\n---\n"))
        self.assertIsNone(contracts.card_schema_id(""))

    def test_amendment_requires_boolean_flag(self) -> None:
        body = contracts.encode_decision_comment(
            "amendment",
            card_id="t_card",
            feature_id="ship-guard",
            stage="execute-plan",
            decision="drop the extra pane",
            decided_by="origin",
        )
        parsed = contracts.parse_decision_comment(body)
        violations = contracts.validate_decision(parsed)
        self.assertTrue(any("affects_accepted_plan" in item for item in violations))
        parsed["affects_accepted_plan"] = True
        self.assertEqual(contracts.validate_decision(parsed), [])

    def test_manual_verdict_requires_verdict_and_40_hex_commit(self) -> None:
        body = contracts.encode_decision_comment(
            "manual-verdict",
            card_id="t_card",
            feature_id="ship-guard",
            stage="direct",
            decision="PASS",
            decided_by="origin",
        )
        parsed = contracts.parse_decision_comment(body)
        violations = contracts.validate_decision(parsed)
        joined = " ".join(violations)
        self.assertIn("verdict", joined)
        self.assertIn("candidate_commit", joined)
        parsed["verdict"] = "PASS"
        parsed["candidate_commit"] = SHA1
        self.assertEqual(contracts.validate_decision(parsed), [])
        parsed["verdict"] = "pass"
        self.assertTrue(
            any("verdict" in item for item in contracts.validate_decision(parsed))
        )
        parsed["verdict"] = "PASS"
        parsed["candidate_commit"] = "B" * 40
        self.assertTrue(
            any("candidate_commit" in item for item in contracts.validate_decision(parsed))
        )

    def test_round_authorization_requires_round_and_commit(self) -> None:
        body = contracts.encode_decision_comment(
            "round-authorization",
            card_id="t_card",
            feature_id="ship-guard",
            stage="execute-plan",
            decision="authorize round 2",
            decided_by="origin",
            round=2,
            candidate_commit=SHA1,
        )
        parsed = contracts.parse_decision_comment(body)
        self.assertEqual(contracts.validate_decision(parsed), [])
        del parsed["round"]
        self.assertTrue(
            any("round" in item for item in contracts.validate_decision(parsed))
        )
        parsed["round"] = 0
        parsed["candidate_commit"] = SHA1
        self.assertTrue(
            any("round" in item for item in contracts.validate_decision(parsed))
        )

    def test_kind_specific_fields_must_be_absent_when_unused(self) -> None:
        parsed = contracts.parse_decision_comment(
            contracts.encode_decision_comment(
                "intent-decision",
                card_id="t_card",
                feature_id="ship-guard",
                stage="direct",
                decision="use pi",
                decided_by="origin",
                verdict="PASS",
                candidate_commit=SHA1,
                round=1,
            )
        )
        violations = contracts.validate_decision(parsed)
        joined = " ".join(violations)
        self.assertIn("verdict", joined)
        self.assertIn("candidate_commit", joined)
        self.assertIn("round", joined)

    def test_unknown_kind_invalid(self) -> None:
        parsed = {
            "schema": contracts.DECISION_SCHEMA_ID,
            "kind": "note",
            "card_id": "t_card",
            "feature_id": "ship-guard",
            "stage": "direct",
            "decision": "x",
            "decided_by": "origin",
        }
        violations = contracts.validate_decision(parsed)
        self.assertTrue(any("kind" in item for item in violations))


class TestCandidateManifest(unittest.TestCase):
    def test_valid_direct_candidate(self) -> None:
        self.assertEqual(contracts.validate_candidate_manifest(valid_candidate()), [])

    def test_diff_head_must_match_commit(self) -> None:
        violations = contracts.validate_candidate_manifest(
            valid_candidate(diff_head="d" * 40)
        )
        self.assertTrue(any("diff_head" in item for item in violations))

    def test_bad_sha_and_attempt(self) -> None:
        violations = contracts.validate_candidate_manifest(
            valid_candidate(candidate_commit="nope", diff_head="nope", attempt_number=0)
        )
        joined = " ".join(violations)
        self.assertIn("candidate_commit", joined)
        self.assertIn("attempt_number", joined)

    def test_accepted_plan_sha_rules(self) -> None:
        ok = valid_candidate(
            stage="execute-plan",
            accepted_plan={"path": PLAN_PATH, "sha256": SHA256},
        )
        self.assertEqual(contracts.validate_candidate_manifest(ok), [])
        bad = valid_candidate(
            stage="execute-plan",
            accepted_plan={"path": PLAN_PATH, "sha256": "nope"},
        )
        self.assertTrue(
            any("sha256" in item for item in contracts.validate_candidate_manifest(bad))
        )


class TestExecuteReviewAndUiEvidence(unittest.TestCase):
    def test_execute_review_ok(self) -> None:
        self.assertEqual(contracts.validate_execute_review(valid_execute_review()), [])

    def test_overall_must_revise_when_gate_fails(self) -> None:
        data = valid_execute_review(
            patch_gate={"verdict": "fail", "findings": ["missing test"]},
            overall={"verdict": "pass"},
        )
        violations = contracts.validate_execute_review(data)
        self.assertTrue(any("revise" in item for item in violations))
        data["overall"] = {"verdict": "revise"}
        self.assertEqual(contracts.validate_execute_review(data), [])

    def test_overall_pass_requires_both_gates_pass(self) -> None:
        data = valid_execute_review(
            patch_gate={"verdict": "pass", "findings": []},
            plan_conformance_gate={"verdict": "fail", "findings": ["drift"]},
            overall={"verdict": "pass"},
        )
        violations = contracts.validate_execute_review(data)
        self.assertTrue(any("pass" in item for item in violations))
        data["overall"] = {"verdict": "revise"}
        self.assertEqual(contracts.validate_execute_review(data), [])

    def test_plan_review_contract(self) -> None:
        self.assertEqual(contracts.validate_plan_review(valid_plan_review()), [])
        missing = valid_plan_review()
        del missing["required_revisions"]
        self.assertTrue(
            any("required_revisions" in item for item in contracts.validate_plan_review(missing))
        )
        bad_plan = valid_plan_review(plan={"path": "rel.md", "sha256": SHA256})
        self.assertTrue(
            any("path" in item for item in contracts.validate_plan_review(bad_plan))
        )
        bad_verdict = valid_plan_review(verdict="PASS")
        self.assertTrue(
            any("verdict" in item for item in contracts.validate_plan_review(bad_verdict))
        )

    def test_ui_evidence_v2_exact_keys(self) -> None:
        self.assertEqual(contracts.UI_EVIDENCE_SCHEMA_ID, "development-ui-evidence.v2")
        self.assertEqual(contracts.validate_ui_evidence(valid_ui_evidence()), [])
        violations = contracts.validate_ui_evidence(valid_ui_evidence(verdict="pass"))
        self.assertTrue(any("verdict" in item for item in violations))
        v1 = valid_ui_evidence()
        del v1["attempt_number"]
        del v1["lease"]
        v1["lease_resource"] = "obsidian:acceptance"
        v1["lease_id"] = "lease-1"
        v1["evidence_paths"] = ["/tmp/ui/shot.png"]
        v1_violations = contracts.validate_ui_evidence(v1)
        joined = " ".join(v1_violations)
        self.assertIn("attempt_number", joined)
        self.assertIn("lease", joined)
        mismatch = valid_ui_evidence(diff_head="d" * 40)
        self.assertTrue(
            any("diff_head" in item for item in contracts.validate_ui_evidence(mismatch))
        )
        bad_scenario = valid_ui_evidence(
            scenarios=[{"name": "open", "verdict": "pass"}]
        )
        self.assertTrue(
            any("verdict" in item for item in contracts.validate_ui_evidence(bad_scenario))
        )


class TestPolicyRegistry(unittest.TestCase):
    def test_table_matches_stage_rows(self) -> None:
        direct = policy.POLICIES["direct"]
        self.assertEqual(direct.implement_skill, "delegate-work")
        self.assertIsNone(direct.review_skill)
        self.assertFalse(direct.review_lane)
        self.assertEqual(direct.ui_execution, "implement")
        self.assertFalse(direct.auto_handoff)
        self.assertEqual(direct.completion_owner, "implement")
        self.assertEqual(direct.max_review_rounds, 3)

        write = policy.POLICIES["write-plan"]
        self.assertEqual(write.implement_skill, "write-plan")
        self.assertEqual(write.review_skill, "review-plan")
        self.assertTrue(write.review_lane)
        self.assertEqual(write.ui_execution, "none")
        self.assertFalse(write.auto_handoff)
        self.assertEqual(write.completion_owner, "review")

        execute = policy.POLICIES["execute-plan"]
        self.assertEqual(execute.implement_skill, "execute-plan")
        self.assertEqual(execute.review_skill, "review-execute-candidate")
        self.assertTrue(execute.review_lane)
        self.assertEqual(execute.ui_execution, "implement")
        self.assertTrue(execute.auto_handoff)
        self.assertEqual(execute.completion_owner, "review")
        self.assertEqual(policy.MAX_REVIEW_ROUNDS, 3)

    def test_relay_spec_derivation(self) -> None:
        direct = policy.resolve_relay_spec(
            stage="direct", operation="execution", coding_agent="pi"
        )
        self.assertEqual(direct.skill, "delegate-work")
        self.assertEqual(direct.mode, "write")
        self.assertEqual(direct.model, "zai-coding-cn/glm-5.3")
        self.assertIsNone(direct.fallback_model)
        self.assertEqual(direct.thinking, "high")
        self.assertFalse(direct.auto_handoff)
        self.assertFalse(direct.review)
        self.assertTrue(direct.resume_session_supported)

        write = policy.resolve_relay_spec(
            stage="write-plan", operation="planning", coding_agent="pi"
        )
        self.assertEqual(write.skill, "write-plan")
        self.assertEqual(write.model, "kimi-coding/k3")
        self.assertEqual(write.fallback_model, "zai-coding-cn/glm-5.3")
        self.assertFalse(write.auto_handoff)

        execute = policy.resolve_relay_spec(
            stage="execute-plan", operation="execution", coding_agent="pi"
        )
        self.assertEqual(execute.skill, "execute-plan")
        self.assertTrue(execute.auto_handoff)
        rework = policy.resolve_relay_spec(
            stage="execute-plan", operation="rework", coding_agent="pi"
        )
        self.assertTrue(rework.auto_handoff)
        planning = policy.resolve_relay_spec(
            stage="execute-plan", operation="planning", coding_agent="pi"
        )
        self.assertFalse(planning.auto_handoff)

        review = policy.resolve_relay_spec(
            stage="write-plan",
            operation="planning",
            coding_agent="pi",
            review=True,
        )
        self.assertEqual(review.skill, "review-plan")
        self.assertEqual(review.mode, "read")
        self.assertEqual(review.model, "zai-coding-cn/glm-5.3")
        self.assertIsNone(review.fallback_model)
        self.assertFalse(review.auto_handoff)
        self.assertTrue(review.review)

        execute_review = policy.resolve_relay_spec(
            stage="execute-plan",
            operation="execution",
            coding_agent="pi",
            review=True,
        )
        self.assertEqual(execute_review.skill, "review-execute-candidate")
        self.assertEqual(execute_review.mode, "read")
        self.assertFalse(execute_review.auto_handoff)

    def test_cursor_raises_adapter_capability_missing(self) -> None:
        with self.assertRaises(errors.HarnessError) as caught:
            policy.resolve_relay_spec(
                stage="direct", operation="execution", coding_agent="cursor"
            )
        self.assertEqual(caught.exception.code, errors.ADAPTER_CAPABILITY_MISSING)

    def test_check_adapter_capability_pi_and_auto_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / ".hermes"
            relay = home / policy.PI_RELAY_SCRIPT_RELPATH
            relay.parent.mkdir(parents=True)
            relay.write_text("// relay\n", encoding="utf-8")
            orig_home = Path.home
            env_backup = os.environ.get("PI_AUTO_HANDOFF_ROOT")
            Path.home = lambda: tmp_path  # type: ignore[assignment]
            os.environ.pop("PI_AUTO_HANDOFF_ROOT", None)
            try:
                missing = policy.check_adapter_capability(
                    "pi", hermes_home=home, auto_handoff_required=False
                )
                self.assertEqual(missing, [])
                needed = policy.check_adapter_capability(
                    "pi", hermes_home=home, auto_handoff_required=True
                )
                self.assertTrue(any("auto-handoff" in item for item in needed))
                root = tmp_path / "Secret-Projects" / "pi-auto-handoff"
                (root / "src").mkdir(parents=True)
                (root / "package.json").write_text("{}", encoding="utf-8")
                (root / "src" / "index.ts").write_text("export {}\n", encoding="utf-8")
                self.assertEqual(
                    policy.check_adapter_capability(
                        "pi", hermes_home=home, auto_handoff_required=True
                    ),
                    [],
                )
            finally:
                Path.home = orig_home
                if env_backup is None:
                    os.environ.pop("PI_AUTO_HANDOFF_ROOT", None)
                else:
                    os.environ["PI_AUTO_HANDOFF_ROOT"] = env_backup
            unsupported = policy.check_adapter_capability(
                "cursor", hermes_home=home, auto_handoff_required=False
            )
            self.assertTrue(any("unsupported" in item for item in unsupported))

    def test_adapter_skill_and_pinned_worker_skills(self) -> None:
        self.assertEqual(policy.adapter_skill("pi"), "pi-delegate")
        self.assertEqual(
            policy.pinned_worker_skills("pi"),
            ["development-orchestrator", "pi-delegate"],
        )
        with self.assertRaises(errors.HarnessError) as caught:
            policy.adapter_skill("cursor")
        self.assertEqual(caught.exception.code, errors.ADAPTER_CAPABILITY_MISSING)


if __name__ == "__main__":
    unittest.main(verbosity=2)
