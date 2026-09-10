"""Evidence, GuardClient, and UI-lease tests for the development-workflow harness.

Bootstrap mirrors ``test_harness_context.py``: drop the plugin directory from
``sys.path`` (it contains ``tools.py``), then load the plugin package via
``spec_from_file_location``. Git fixtures follow
``hermes/.hermes/tests/test_development_external_guard.py``.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_DIR = Path(__file__).resolve().parent.parent
GUARD_SCRIPT = PLUGIN_DIR.parent.parent / "scripts" / "development_external_guard.py"

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
errors = importlib.import_module(_MODULE_NAME + ".harness.errors")
contracts = importlib.import_module(_MODULE_NAME + ".harness.contracts")
guard_client = importlib.import_module(_MODULE_NAME + ".harness.guard_client")
evidence = importlib.import_module(_MODULE_NAME + ".harness.evidence")
ui_lease = importlib.import_module(_MODULE_NAME + ".harness.ui_lease")

GuardClient = guard_client.GuardClient
HarnessError = errors.HarnessError
UiLeaseManager = ui_lease.UiLeaseManager
LEASE_SCHEMA = ui_lease.LEASE_SCHEMA
parse_stage_body = contracts.parse_stage_body

SHA1_A = "a" * 40
SHA1_B = "b" * 40
SHA256 = "c" * 64
PLAN_PATH = "/tmp/accepted-plan.md"
RELAY_MODEL = "zai-coding-cn/glm-5.3"
RELAY_CWD = "/tmp/repo"
RELAY_THINKING = "high"

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


def valid_candidate(**overrides):
    data = {
        "schema": contracts.CANDIDATE_SCHEMA_ID,
        "board": "dotfile",
        "card_id": "t_evidence",
        "feature_id": "ship-guard",
        "stage": "direct",
        "implement_run_id": 7,
        "attempt_number": 1,
        "candidate_commit": SHA1_A,
        "diff_base": SHA1_B,
        "diff_head": SHA1_A,
        "accepted_plan": None,
        "created_at": "2026-09-10T00:00:00Z",
    }
    data.update(overrides)
    return data


def valid_execute_review(**overrides):
    data = {
        "schema": contracts.EXECUTE_REVIEW_SCHEMA_ID,
        "card_id": "t_evidence",
        "review_run_id": 9,
        "round": 1,
        "candidate_commit": SHA1_A,
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
        "board": "dotfile",
        "card_id": "t_evidence",
        "feature_id": "ship-guard",
        "stage": "direct",
        "run_id": 7,
        "attempt_number": 1,
        "candidate_commit": SHA1_A,
        "diff_base": SHA1_B,
        "diff_head": SHA1_A,
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
        "scenarios": [
            {"name": "open the note and confirm the heading", "verdict": "PASS"}
        ],
        "verdict": "PASS",
        "automation_boundary": "obsidian renderer",
        "cleanup": "released",
        "created_at": "2026-09-10T00:00:00Z",
    }
    data.update(overrides)
    return data


def valid_relay_result(**overrides):
    data = {
        "schema": evidence.RELAY_RESULT_SCHEMA,
        "status": "completed",
        "exitCode": 0,
        "sessionId": "sess-1",
        "cwd": RELAY_CWD,
        "mode": "write",
        "requestedModel": RELAY_MODEL,
        "resolvedModel": RELAY_MODEL,
        "thinking": RELAY_THINKING,
        "finalMessage": "review body",
    }
    data.update(overrides)
    return data


def _stage_body(
    *,
    feature_id: str = "ship-guard",
    stage: str = "direct",
    accepted_plan: str = "null",
) -> str:
    return (
        "---\n"
        "schema: development-stage.v2\n"
        f"feature_id: {feature_id}\n"
        f"stage: {stage}\n"
        "intent: draft\n"
        "ui_acceptance: pending\n"
        "manual_acceptance: []\n"
        "coding_agent: pi\n"
        f"accepted_plan: {accepted_plan}\n"
        "---\n\n"
        "# Goal\n\nShip it.\n\n"
        "# Observable acceptance\n\n- doctor passes.\n\n"
        "# Included scope\n\n- the plugin\n\n"
        "# Non-goals\n\n- Hermes Core\n\n"
        "# Settled decisions\n\n- reuse existing helpers\n\n"
        "# Open decisions\n\nNone\n\n"
        "# Repository grounding\n\n- plugin path\n\n"
        "# Authority boundaries\n\n- no pushes\n"
    )


def plan_review_yaml(**overrides) -> dict:
    data = {
        "schema": "development-plan-review.v1",
        "board": "dotfile",
        "card_id": "t_evidence",
        "feature_id": "ship-guard",
        "review_run_id": 9,
        "round": 1,
        "plan": {"path": PLAN_PATH, "sha256": SHA256},
        "verdict": "pass",
        "summary": "Plan is ready to execute.",
        "confidence": 0.9,
        "coverage": [],
        "required_revisions": [],
        "non_blocking_risks": [],
        "evidence_checked": [],
        "delegated_evidence": [],
        "evidence_limitations": [],
    }
    data.update(overrides)
    return data


def execute_review_yaml(**overrides) -> dict:
    data = {
        "schema": "development-execute-review.v1",
        "board": "dotfile",
        "card_id": "t_evidence",
        "feature_id": "ship-guard",
        "review_run_id": 9,
        "round": 1,
        "candidate_commit": SHA1_A,
        "diff_base": SHA1_B,
        "diff_head": SHA1_A,
        "accepted_plan": {"path": PLAN_PATH, "sha256": SHA256},
        "implementation_relay": {"session_id": "sess-impl"},
        "candidate_manifest": {"path": "/tmp/candidate.json", "sha256": SHA256},
        "patch_gate": {"verdict": "pass", "findings": [], "advisories": []},
        "plan_conformance_gate": {
            "verdict": "pass",
            "coverage": [],
            "findings": [],
            "accepted_deviations": [],
            "out_of_plan_changes": [],
        },
        "ui_evidence": {"verdict": "pass", "paths": [], "findings": []},
        "overall": {
            "verdict": "pass",
            "summary": "Candidate matches the accepted plan.",
            "confidence": 0.9,
        },
        "delegated_evidence": [],
        "evidence_limitations": [],
    }
    data.update(overrides)
    return data


class _Event:
    def __init__(self, kind: str) -> None:
        self.kind = kind


class _Run:
    def __init__(self, outcome: str, metadata=None) -> None:
        self.outcome = outcome
        self.metadata = metadata


class IsolatedEvidenceHome(unittest.TestCase):
    """Temp HERMES_HOME + artifacts root + disposable git repo per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / ".hermes"
        self.home.mkdir()
        self.artifacts = self.root / "development-artifacts"
        self.artifacts.mkdir()
        self.board = "dotfile"
        self.card_id = "t_evidence"
        self._env_backup = os.environ.copy()
        self.addCleanup(self._restore_env)
        os.environ["HERMES_HOME"] = str(self.home)
        os.environ["HERMES_DEVFLOW_ARTIFACTS_ROOT"] = str(self.artifacts)
        for var in _SCRUB_ENV_VARS:
            if var in ("HERMES_HOME", "HERMES_DEVFLOW_ARTIFACTS_ROOT"):
                continue
            os.environ.pop(var, None)
        self._orig_path_home = Path.home
        Path.home = lambda: self.root  # type: ignore[assignment]
        self.addCleanup(setattr, Path, "home", self._orig_path_home)
        self._pids: list[int] = []
        self.addCleanup(self._reap)
        self.repo = self.make_repo()
        self.task = evidence.task_dir(self.artifacts, self.board, self.card_id)

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _reap(self) -> None:
        for pid in self._pids:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(pid, signal.SIGKILL)

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        repo = cwd if cwd is not None else self.repo
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if check and proc.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout

    def make_repo(self) -> Path:
        repo = self.root / "repo"
        repo.mkdir()
        self.git("init", "-q", cwd=repo)
        self.git("config", "user.email", "dev@example.com", cwd=repo)
        self.git("config", "user.name", "Dev Test", cwd=repo)
        (repo / "file1.txt").write_text("one\n")
        self.git("add", ".", cwd=repo)
        self.git("commit", "-q", "-m", "initial", cwd=repo)
        (repo / "file1.txt").write_text("one changed\n")
        return repo

    def commit(self, message: str) -> str:
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def wait_until(self, predicate, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def client(self) -> GuardClient:
        return GuardClient(
            script_path=GUARD_SCRIPT,
            home=self.home,
            board=self.board,
            card_id=self.card_id,
            artifacts_root=self.artifacts,
        )


class TestGuardClient(IsolatedEvidenceHome):
    def test_guard_client_against_real_v2_script(self) -> None:
        self.assertTrue(GUARD_SCRIPT.is_file(), GUARD_SCRIPT)
        client = self.client()
        self.assertIsNone(client.read_state())

        rc, initialized = client.init(self.repo)
        self.assertEqual(rc, 0, initialized)
        self.assertTrue(initialized.get("ok"))
        state = client.read_state()
        self.assertIsNotNone(state)
        self.assertEqual(state["schema"], "development-external-execution.v2")
        self.assertEqual(state["attempts"], [])
        self.assertEqual(state["landings"], [])
        self.assertEqual(state["card_id"], self.card_id)
        self.assertTrue(state["baseline"]["head"])

        out_dir = self.root / "relay-out"
        result_path = out_dir / "result.json"
        session = "sess-evidence-1"
        result_body = {
            "schema": "delegate-relay.result.v1",
            "status": "completed",
            "exitCode": 0,
            "sessionId": session,
        }
        script = (
            f"sleep 2; printf '%s' {shlex.quote(json.dumps(result_body))} > "
            f"{shlex.quote(str(result_path))}"
        )
        rc, spawned = client.start_or_inspect(
            operation="execution",
            out_dir=out_dir,
            result_path=result_path,
            cmd_json=["/bin/sh", "-c", script],
        )
        self.assertEqual(rc, 0, spawned)
        self.assertEqual(spawned.get("outcome"), "spawned")
        pid = spawned["pid"]
        self._pids.append(pid)

        rc, live = client.inspect()
        self.assertEqual(rc, 0, live)
        self.assertEqual(live.get("outcome"), "attach")

        self.assertTrue(
            self.wait_until(lambda: not self.pid_alive(pid) and result_path.is_file()),
            "relay helper should exit and write the result file",
        )
        rc, terminal = client.inspect()
        self.assertEqual(rc, 0, terminal)
        self.assertEqual(terminal.get("outcome"), "terminal")

        rc, recorded = client.record_terminal(result_path, session_id=session)
        self.assertEqual(rc, 0, recorded)
        self.assertEqual(recorded.get("outcome"), "terminal")
        sealed = client.read_state()
        attempt = sealed["attempts"][-1]
        self.assertEqual(attempt["state"], "terminal")
        self.assertEqual(attempt["session_id"], session)
        self.assertEqual(attempt["terminal_status"], "completed")

        trailer = f"Kanban-Task: {self.card_id}"
        landing_sha = self.commit(f"land candidate\n\n{trailer}")
        rc, landing = client.record_commit(landing_sha)
        self.assertEqual(rc, 0, landing)
        self.assertEqual(landing.get("outcome"), "recorded")
        landings = client.read_state()["landings"]
        self.assertEqual(1, len(landings))
        self.assertEqual(landing_sha, landings[0]["commit"])
        self.assertEqual(1, landings[0]["attempt_number"])

        rc, check = client.check_run()
        self.assertEqual(rc, 5, check)
        self.assertFalse(check.get("ok"))
        self.assertEqual(check.get("reason"), "task-env-missing")


class TestEvidence(IsolatedEvidenceHome):
    def test_candidate_manifest_round_trip_and_invalid(self) -> None:
        first = valid_candidate(created_at="2026-09-10T00:00:00Z")
        second = valid_candidate(
            attempt_number=2,
            candidate_commit=SHA1_B,
            diff_head=SHA1_B,
            created_at="2026-09-10T01:00:00Z",
        )
        evidence.write_candidate_manifest(self.task, first)
        evidence.write_candidate_manifest(self.task, second)
        loaded = evidence.load_candidate_manifests(self.task)
        self.assertEqual([item["candidate_commit"] for item in loaded], [SHA1_B, SHA1_A])
        dest = evidence.candidate_dir(self.task, SHA1_A) / "candidate.json"
        self.assertEqual(evidence.load_json(dest)["schema"], contracts.CANDIDATE_SCHEMA_ID)

        with self.assertRaises(HarnessError) as ctx:
            evidence.write_candidate_manifest(self.task, {"schema": "nope"})
        self.assertEqual(ctx.exception.code, errors.CANDIDATE_NOT_FROZEN)
        self.assertTrue(ctx.exception.details.get("violations"))

    def test_verify_plan_identity_happy_missing_tampered(self) -> None:
        plan = self.root / "accepted-plan.md"
        plan.write_text("# plan\n", encoding="utf-8")
        digest = hashlib.sha256(plan.read_bytes()).hexdigest()
        identity = evidence.verify_plan_identity(
            {"path": str(plan), "sha256": digest, "card_id": self.card_id}
        )
        self.assertEqual(identity["path"], str(plan))
        self.assertEqual(identity["sha256"], digest)
        self.assertEqual(identity["size"], plan.stat().st_size)

        with self.assertRaises(HarnessError) as missing:
            evidence.verify_plan_identity({})
        self.assertEqual(missing.exception.code, errors.PLAN_IDENTITY_MISSING)

        with self.assertRaises(HarnessError) as gone:
            evidence.verify_plan_identity(
                {"path": str(self.root / "missing.md"), "sha256": digest}
            )
        self.assertEqual(gone.exception.code, errors.PLAN_IDENTITY_MISSING)

        plan.write_text("# plan tampered\n", encoding="utf-8")
        with self.assertRaises(HarnessError) as mismatch:
            evidence.verify_plan_identity({"path": str(plan), "sha256": digest})
        self.assertEqual(mismatch.exception.code, errors.PLAN_SHA_MISMATCH)
        self.assertEqual(mismatch.exception.details.get("expected"), digest)
        self.assertTrue(mismatch.exception.details.get("actual"))
        self.assertNotEqual(mismatch.exception.details.get("actual"), digest)

    def test_verify_landing_happy_trailer_missing_pre_baseline(self) -> None:
        trailer = f"Kanban-Task: {self.card_id}"
        pre = self.commit(f"pre-baseline\n\n{trailer}")
        baseline = self.commit("baseline")
        happy = self.commit(f"land it\n\n{trailer}")
        missing = self.commit("no trailer here")

        self.assertEqual(
            evidence.verify_landing(self.repo, happy, self.card_id, baseline),
            [],
        )
        self.assertIn(
            "trailer-missing",
            evidence.verify_landing(self.repo, missing, self.card_id, baseline),
        )
        self.assertIn(
            "commit-pre-baseline",
            evidence.verify_landing(self.repo, pre, self.card_id, baseline),
        )
        self.assertEqual(
            evidence.verify_landing(self.repo, "0" * 40, self.card_id, baseline),
            ["commit-unresolvable"],
        )

    def test_validate_relay_result_statuses_and_rejects(self) -> None:
        for status in evidence.RELAY_RESULT_STATUSES:
            payload = {"schema": evidence.RELAY_RESULT_SCHEMA, "status": status}
            self.assertEqual(evidence.validate_relay_result(payload), [], status)
        self.assertTrue(evidence.validate_relay_result({"schema": "nope", "status": "completed"}))
        self.assertTrue(
            evidence.validate_relay_result(
                {"schema": evidence.RELAY_RESULT_SCHEMA, "status": "done"}
            )
        )
        self.assertTrue(
            evidence.validate_relay_result(
                {
                    "schema": evidence.RELAY_RESULT_SCHEMA,
                    "status": "completed",
                    "exitCode": "0",
                }
            )
        )
        ok = {
            "schema": evidence.RELAY_RESULT_SCHEMA,
            "status": "completed",
            "exitCode": 0,
            "sessionId": "sess",
            "threadId": "thr",
            "autoHandoff": {"enabled": False},
        }
        self.assertEqual(evidence.validate_relay_result(ok), [])

    def test_verify_auto_handoff_result_happy_and_misses(self) -> None:
        plan = str(self.root / "plan.md")
        out_dir = str(self.root / "relay-out")
        happy = {
            "schema": evidence.RELAY_RESULT_SCHEMA,
            "status": "completed",
            "autoHandoff": {
                "enabled": True,
                "planFile": plan,
                "handoffDir": str(Path(out_dir) / "auto-handoff"),
                "extensionRoot": "/tmp/pi-auto-handoff",
            },
        }
        verified = evidence.verify_auto_handoff_result(
            happy, expected_plan_path=plan, out_dir=out_dir
        )
        self.assertEqual(verified["planFile"], plan)

        disabled = json.loads(json.dumps(happy))
        disabled["autoHandoff"]["enabled"] = False
        with self.assertRaises(HarnessError) as ctx:
            evidence.verify_auto_handoff_result(
                disabled, expected_plan_path=plan, out_dir=out_dir
            )
        self.assertEqual(ctx.exception.code, errors.AUTO_HANDOFF_INVALID)

        wrong_plan = json.loads(json.dumps(happy))
        wrong_plan["autoHandoff"]["planFile"] = str(self.root / "other.md")
        with self.assertRaises(HarnessError) as ctx:
            evidence.verify_auto_handoff_result(
                wrong_plan, expected_plan_path=plan, out_dir=out_dir
            )
        self.assertEqual(ctx.exception.code, errors.AUTO_HANDOFF_INVALID)

        wrong_dir = json.loads(json.dumps(happy))
        wrong_dir["autoHandoff"]["handoffDir"] = str(self.root / "elsewhere")
        with self.assertRaises(HarnessError) as ctx:
            evidence.verify_auto_handoff_result(
                wrong_dir, expected_plan_path=plan, out_dir=out_dir
            )
        self.assertEqual(ctx.exception.code, errors.AUTO_HANDOFF_INVALID)

    def test_load_reviews_and_ui_evidence_filters_invalid(self) -> None:
        round1 = evidence.review_round_run_dir(
            self.task, 1, 11, "review-execute-candidate"
        )
        round2 = evidence.review_round_run_dir(
            self.task, 2, 12, "review-execute-candidate"
        )
        evidence.write_json_atomic(
            round1 / "review.json", valid_execute_review(round=1, review_run_id=11)
        )
        evidence.write_json_atomic(
            round2 / "review.json", valid_execute_review(round=2, review_run_id=12)
        )
        evidence.write_json_atomic(round1 / "invalid.json", {"schema": "nope"})
        (round1 / "broken.json").write_text("{not json", encoding="utf-8")

        reviews = evidence.load_execute_reviews(self.task)
        self.assertEqual([item["round"] for item in reviews], [2, 1])
        self.assertTrue(all("_path" in item for item in reviews))

        ui_a = evidence.ui_dir(self.task, SHA1_A, 7)
        ui_b = evidence.ui_dir(self.task, SHA1_B, 8)
        evidence.write_json_atomic(
            ui_a / "evidence.json",
            valid_ui_evidence(candidate_commit=SHA1_A, created_at="2026-09-10T00:00:00Z"),
        )
        evidence.write_json_atomic(
            ui_a / "later.json",
            valid_ui_evidence(
                candidate_commit=SHA1_A,
                run_id=8,
                created_at="2026-09-10T02:00:00Z",
            ),
        )
        evidence.write_json_atomic(
            ui_b / "other.json",
            valid_ui_evidence(
                candidate_commit=SHA1_B,
                diff_head=SHA1_B,
                run_id=9,
            ),
        )
        evidence.write_json_atomic(ui_a / "bad.json", {"schema": "nope"})

        loaded = evidence.load_ui_evidence(self.task, SHA1_A)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["run_id"], 8)
        self.assertTrue(all(item["candidate_commit"] == SHA1_A for item in loaded))
        self.assertEqual(evidence.load_ui_evidence(self.task, SHA1_B)[0]["run_id"], 9)

    def test_review_round_and_handoff_metadata(self) -> None:
        self.assertEqual(evidence.review_round_from_events([]), 1)
        self.assertEqual(evidence.review_round_from_events([_Event("claimed")]), 1)
        self.assertEqual(
            evidence.review_round_from_events(
                [
                    _Event("claimed"),
                    _Event("changes_requested"),
                    _Event("claimed"),
                    _Event("changes_requested"),
                ]
            ),
            3,
        )
        runs = [
            _Run("completed", {"ignored": True}),
            _Run("review_requested", {"candidate": {"candidate_commit": SHA1_A}}),
            _Run("review_requested", None),
            _Run("review_requested", {"candidate": {"candidate_commit": SHA1_B}}),
        ]
        meta = evidence.handoff_metadata_from_runs(runs)
        self.assertEqual(len(meta), 3)
        self.assertEqual(meta[0]["candidate"]["candidate_commit"], SHA1_B)
        self.assertEqual(meta[1], {})
        self.assertEqual(meta[2]["candidate"]["candidate_commit"], SHA1_A)

    def test_load_ui_evidence_skips_v1(self) -> None:
        ui_a = evidence.ui_dir(self.task, SHA1_A, 7)
        v1 = {
            "schema": "development-ui-evidence.v1",
            "board": "dotfile",
            "card_id": self.card_id,
            "feature_id": "ship-guard",
            "stage": "direct",
            "run_id": 7,
            "candidate_commit": SHA1_A,
            "verdict": "PASS",
            "scenarios": ["open the note"],
            "automation_boundary": "obsidian renderer",
            "lease_resource": "obsidian:acceptance",
            "lease_id": "lease-1",
            "cleanup": "released",
            "evidence_paths": ["/tmp/ui/shot.png"],
            "created_at": "2026-09-10T00:00:00Z",
        }
        evidence.write_json_atomic(ui_a / "v1.json", v1)
        evidence.write_json_atomic(ui_a / "v2.json", valid_ui_evidence())
        loaded = evidence.load_ui_evidence(self.task, SHA1_A)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["schema"], contracts.UI_EVIDENCE_SCHEMA_ID)

    def test_require_successful_relay_result_happy_and_violations(self) -> None:
        happy = valid_relay_result()
        self.assertEqual(
            evidence.require_successful_relay_result(
                happy,
                expected_cwd=RELAY_CWD,
                expected_mode="write",
                expected_model=RELAY_MODEL,
                expected_thinking=RELAY_THINKING,
            ),
            [],
        )
        required = evidence.require_successful_relay_result(
            happy,
            expected_cwd=RELAY_CWD,
            expected_mode="write",
            expected_model=RELAY_MODEL,
            expected_thinking=RELAY_THINKING,
            require_final_message=True,
        )
        self.assertEqual(required, [])

        cases = [
            (valid_relay_result(cwd="/other"), "cwd"),
            (valid_relay_result(mode="read-only"), "mode"),
            (valid_relay_result(requestedModel=None), "requestedModel"),
            (valid_relay_result(requestedModel="other/model"), "requestedModel"),
            (valid_relay_result(resolvedModel=""), "resolvedModel"),
            (valid_relay_result(thinking="low"), "thinking"),
            (valid_relay_result(exitCode=1), "exitCode"),
            (valid_relay_result(status="failed", exitCode=1), "status"),
        ]
        for payload, needle in cases:
            violations = evidence.require_successful_relay_result(
                payload,
                expected_cwd=RELAY_CWD,
                expected_mode="write",
                expected_model=RELAY_MODEL,
                expected_thinking=RELAY_THINKING,
            )
            self.assertTrue(violations, needle)
            self.assertTrue(
                any(needle in item for item in violations),
                (needle, violations),
            )

        missing_final = evidence.require_successful_relay_result(
            valid_relay_result(finalMessage=""),
            expected_cwd=RELAY_CWD,
            expected_mode="write",
            expected_model=RELAY_MODEL,
            expected_thinking=RELAY_THINKING,
            require_final_message=True,
        )
        self.assertTrue(any("finalMessage" in item for item in missing_final))

    def test_fallback_eligible(self) -> None:
        self.assertTrue(
            evidence.fallback_eligible(
                valid_relay_result(
                    status="failed",
                    exitCode=1,
                    error="provider rate limit 429",
                    stderrTail="",
                )
            )
        )
        self.assertFalse(
            evidence.fallback_eligible(
                valid_relay_result(
                    status="failed",
                    exitCode=1,
                    error="model crashed during decode",
                    stderrTail="stack trace",
                )
            )
        )
        self.assertFalse(
            evidence.fallback_eligible(
                valid_relay_result(
                    status="unavailable",
                    exitCode=127,
                    sourceStatus="pi_unavailable",
                    error="pi binary missing",
                )
            )
        )
        self.assertFalse(evidence.fallback_eligible(valid_relay_result()))

    def test_extract_review_report_formats(self) -> None:
        payload = {"verdict": "pass", "summary": "ok"}
        raw_json = json.dumps(payload)
        self.assertEqual(evidence.extract_review_report(raw_json), payload)
        fenced_json = "```json\n" + raw_json + "\n```"
        self.assertEqual(evidence.extract_review_report(fenced_json), payload)

        raw_yaml = "verdict: pass\nsummary: ok\n"
        self.assertEqual(
            evidence.extract_review_report(raw_yaml),
            {"verdict": "pass", "summary": "ok"},
        )
        fenced_yaml = "```yaml\n" + raw_yaml + "```"
        self.assertEqual(
            evidence.extract_review_report(fenced_yaml),
            {"verdict": "pass", "summary": "ok"},
        )

        with self.assertRaises(ValueError):
            evidence.extract_review_report("a: 1\na: 2\n")
        with self.assertRaises(ValueError):
            evidence.extract_review_report("this is not a review document")

    def test_normalize_plan_and_execute_review(self) -> None:
        plan_report = plan_review_yaml()
        normalized_plan = evidence.normalize_plan_review(
            plan_report,
            board="dotfile",
            card_id=self.card_id,
            feature_id="ship-guard",
            review_run_id=9,
            round=1,
        )
        self.assertEqual(contracts.validate_plan_review(normalized_plan), [])
        self.assertEqual(normalized_plan["schema"], contracts.PLAN_REVIEW_SCHEMA_ID)
        self.assertEqual(normalized_plan["plan"]["sha256"], SHA256)
        self.assertEqual(normalized_plan["required_revisions"], [])
        self.assertNotIn("confidence", normalized_plan)

        omitted = plan_review_yaml()
        del omitted["required_revisions"]
        del omitted["card_id"]
        still_ok = evidence.normalize_plan_review(
            omitted,
            board="dotfile",
            card_id=self.card_id,
            feature_id="ship-guard",
            review_run_id=9,
            round=1,
        )
        self.assertEqual(still_ok["card_id"], self.card_id)
        self.assertEqual(still_ok["required_revisions"], [])

        with self.assertRaises(ValueError) as plan_mismatch:
            evidence.normalize_plan_review(
                plan_review_yaml(card_id="t_other"),
                board="dotfile",
                card_id=self.card_id,
                feature_id="ship-guard",
                review_run_id=9,
                round=1,
            )
        self.assertIn("identity mismatch", str(plan_mismatch.exception))

        exec_report = execute_review_yaml()
        normalized_exec = evidence.normalize_execute_review(
            exec_report,
            board="dotfile",
            card_id=self.card_id,
            feature_id="ship-guard",
            review_run_id=9,
            round=1,
        )
        self.assertEqual(contracts.validate_execute_review(normalized_exec), [])
        self.assertEqual(
            set(normalized_exec),
            set(contracts.EXECUTE_REVIEW_KEYS),
        )
        self.assertEqual(normalized_exec["accepted_plan_sha256"], SHA256)
        self.assertEqual(normalized_exec["patch_gate"], {"verdict": "pass", "findings": []})
        self.assertEqual(
            normalized_exec["plan_conformance_gate"],
            {"verdict": "pass", "findings": []},
        )
        self.assertEqual(normalized_exec["overall"], {"verdict": "pass"})

        with self.assertRaises(ValueError) as exec_mismatch:
            evidence.normalize_execute_review(
                execute_review_yaml(card_id="t_other"),
                board="dotfile",
                card_id=self.card_id,
                feature_id="ship-guard",
                review_run_id=9,
                round=1,
            )
        self.assertIn("identity mismatch", str(exec_mismatch.exception))

        with self.assertRaises(ValueError) as gate_fail:
            evidence.normalize_execute_review(
                execute_review_yaml(
                    patch_gate={"verdict": "fail", "findings": ["bug"], "advisories": []},
                    overall={"verdict": "pass", "summary": "nope", "confidence": 0.1},
                ),
                board="dotfile",
                card_id=self.card_id,
                feature_id="ship-guard",
                review_run_id=9,
                round=1,
            )
        self.assertIn("pass", str(gate_fail.exception))

        unsafe = execute_review_yaml(
            patch_gate={
                "verdict": "pass",
                "findings": [{"id": "RE-P01", "note": "ok"}, {"set": {1, 2}}],
                "advisories": [],
            }
        )
        coerced = evidence.normalize_execute_review(
            unsafe,
            board="dotfile",
            card_id=self.card_id,
            feature_id="ship-guard",
            review_run_id=9,
            round=1,
        )
        self.assertEqual(coerced["patch_gate"]["findings"][0], {"id": "RE-P01", "note": "ok"})
        self.assertIsInstance(coerced["patch_gate"]["findings"][1], str)

    def test_write_review_evidence_immutable(self) -> None:
        run_dir = evidence.review_round_run_dir(
            self.task, 1, 11, "review-plan"
        )
        payload = evidence.normalize_plan_review(
            plan_review_yaml(),
            board="dotfile",
            card_id=self.card_id,
            feature_id="ship-guard",
            review_run_id=9,
            round=1,
        )
        first = evidence.write_review_evidence(run_dir, payload)
        again = evidence.write_review_evidence(run_dir, dict(payload))
        self.assertEqual(first, again)
        loaded = evidence.load_review_evidence(
            self.task, round=1, run_id=11, skill="review-plan"
        )
        self.assertEqual(loaded["verdict"], "pass")

        changed = dict(payload)
        changed["summary"] = "different summary"
        with self.assertRaises(HarnessError) as ctx:
            evidence.write_review_evidence(run_dir, changed)
        self.assertEqual(ctx.exception.code, errors.EVIDENCE_IDENTITY_MISMATCH)
        self.assertEqual(
            evidence.load_review_evidence(
                self.task, round=1, run_id=11, skill="review-plan"
            )["summary"],
            payload["summary"],
        )

    def test_write_candidate_manifest_immutable(self) -> None:
        first = valid_candidate()
        evidence.write_candidate_manifest(self.task, first)
        reused = evidence.write_candidate_manifest(self.task, dict(first))
        self.assertEqual(reused["diff_base"], SHA1_B)

        changed = valid_candidate(diff_base=SHA1_A)
        with self.assertRaises(HarnessError) as ctx:
            evidence.write_candidate_manifest(self.task, changed)
        self.assertEqual(ctx.exception.code, errors.CANDIDATE_CHANGED)
        dest = evidence.candidate_dir(self.task, SHA1_A) / "candidate.json"
        self.assertEqual(evidence.load_json(dest)["diff_base"], SHA1_B)

    def test_verify_ui_evidence_binding(self) -> None:
        card = parse_stage_body(_stage_body())
        manifest = valid_candidate()
        lease_row = {
            "resource": "obsidian:acceptance",
            "lease_id": "lease-1",
            "holder_run_id": 7,
            "card_id": self.card_id,
            "candidate_commit": SHA1_A,
            "acquired_at": "2026-09-10T00:00:00Z",
            "released_at": "2026-09-10T00:01:00Z",
        }
        happy = valid_ui_evidence()
        self.assertEqual(
            evidence.verify_ui_evidence_binding(
                happy,
                manifest=manifest,
                card=card,
                run_id=7,
                attempt_number=1,
                plan=None,
                relay_session_id="relay-1",
                lease_records=[lease_row],
            ),
            [],
        )
        released_ok = evidence.verify_ui_evidence_binding(
            happy,
            manifest=manifest,
            card=card,
            run_id=7,
            attempt_number=1,
            plan=None,
            lease_records=[lease_row],
        )
        self.assertEqual(released_ok, [])

        candidate_mismatch = valid_ui_evidence(
            candidate_commit=SHA1_B, diff_head=SHA1_B
        )
        self.assertTrue(
            any(
                "candidate_commit" in item
                for item in evidence.verify_ui_evidence_binding(
                    candidate_mismatch,
                    manifest=manifest,
                    card=card,
                    run_id=7,
                    attempt_number=1,
                    plan=None,
                    lease_records=None,
                )
            )
        )

        execute_card = parse_stage_body(
            _stage_body(
                stage="execute-plan",
                accepted_plan=(
                    "{card_id: t_evidence, path: "
                    f"{PLAN_PATH}, sha256: {SHA256}}}"
                ),
            )
        )
        execute_manifest = valid_candidate(
            stage="execute-plan",
            accepted_plan={"path": PLAN_PATH, "sha256": SHA256},
        )
        plan_mismatch = valid_ui_evidence(
            stage="execute-plan",
            accepted_plan={"path": PLAN_PATH, "sha256": "d" * 64},
        )
        self.assertTrue(
            any(
                "accepted_plan" in item
                for item in evidence.verify_ui_evidence_binding(
                    plan_mismatch,
                    manifest=execute_manifest,
                    card=execute_card,
                    run_id=7,
                    attempt_number=1,
                    plan={"path": PLAN_PATH, "sha256": SHA256},
                    lease_records=None,
                )
            )
        )

        self.assertTrue(
            any(
                "run_id" in item
                for item in evidence.verify_ui_evidence_binding(
                    valid_ui_evidence(run_id=8),
                    manifest=manifest,
                    card=card,
                    run_id=7,
                    attempt_number=1,
                    plan=None,
                    lease_records=None,
                )
            )
        )
        self.assertTrue(
            any(
                "attempt_number" in item
                for item in evidence.verify_ui_evidence_binding(
                    valid_ui_evidence(attempt_number=2),
                    manifest=manifest,
                    card=card,
                    run_id=7,
                    attempt_number=1,
                    plan=None,
                    lease_records=None,
                )
            )
        )

        unknown_lease = evidence.verify_ui_evidence_binding(
            happy,
            manifest=manifest,
            card=card,
            run_id=7,
            attempt_number=1,
            plan=None,
            lease_records=[{"lease_id": "other", "holder_run_id": 7}],
        )
        self.assertTrue(any("lease_id" in item for item in unknown_lease))

        holder_differs = evidence.verify_ui_evidence_binding(
            happy,
            manifest=manifest,
            card=card,
            run_id=7,
            attempt_number=1,
            plan=None,
            lease_records=[{"lease_id": "lease-1", "holder_run_id": 99}],
        )
        self.assertTrue(any("holder_run_id" in item for item in holder_differs))


class TestUiLease(IsolatedEvidenceHome):
    def _manager(self) -> UiLeaseManager:
        return UiLeaseManager(hermes_home=self.home)

    def _dead_pid(self) -> int:
        proc = subprocess.Popen(["true"])
        proc.wait()
        return proc.pid

    def test_acquire_inspect_release_and_owner(self) -> None:
        manager = self._manager()
        resource = "obsidian:my-vault"
        lease = manager.acquire(
            resource,
            board=self.board,
            card_id=self.card_id,
            run_id=7,
            candidate_commit=SHA1_A,
        )
        self.assertEqual(lease["schema"], LEASE_SCHEMA)
        self.assertEqual(lease["resource"], resource)
        self.assertEqual(lease["pid"], os.getpid())
        self.assertTrue(lease["lease_id"])
        self.assertRegex(lease["lease_id"], r"^[0-9a-f]{32}$")
        inspected = manager.inspect(resource)
        self.assertIsNotNone(inspected)
        self.assertTrue(inspected["holder_alive"])
        self.assertEqual(inspected["lease"]["run_id"], 7)
        self.assertEqual(inspected["lease"]["lease_id"], lease["lease_id"])

        with self.assertRaises(HarnessError) as busy:
            manager.acquire(
                resource,
                board=self.board,
                card_id=self.card_id,
                run_id=8,
                candidate_commit=SHA1_A,
            )
        self.assertEqual(busy.exception.code, errors.UI_RESOURCE_BUSY)

        with self.assertRaises(HarnessError) as not_owner:
            manager.release(resource, run_id=8)
        self.assertEqual(not_owner.exception.code, errors.UI_RESOURCE_BUSY)
        self.assertEqual(not_owner.exception.details.get("reason"), "not-owner")

        released = manager.release(resource, run_id=7)
        self.assertTrue(released["released"])
        self.assertIsNone(manager.inspect(resource))
        history = ui_lease.load_release_history(self.home)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["lease_id"], lease["lease_id"])
        self.assertEqual(history[0]["holder_run_id"], 7)
        self.assertEqual(history[0]["candidate_commit"], SHA1_A)
        self.assertFalse(manager.lease_path(resource).exists())
        again = manager.release(resource, run_id=7)
        self.assertTrue(again["released"])
        self.assertTrue(again["already_gone"])
        self.assertEqual(len(ui_lease.load_release_history(self.home)), 1)

    def test_reclaim_dead_holder_and_current_run_busy(self) -> None:
        manager = self._manager()
        dead = self._dead_pid()
        reclaim_id = "obsidian:reclaim"
        path = manager.lease_path(reclaim_id)
        evidence.write_json_atomic(
            path,
            {
                "schema": LEASE_SCHEMA,
                "resource": reclaim_id,
                "board": self.board,
                "card_id": self.card_id,
                "run_id": 99,
                "pid": dead,
                "process_start": None,
                "candidate_commit": SHA1_A,
                "acquired_at": "2026-01-01T00:00:00+00:00",
            },
        )
        reclaimed = manager.acquire(
            reclaim_id,
            board=self.board,
            card_id=self.card_id,
            run_id=2,
            candidate_commit=SHA1_A,
            holder_run_is_current=lambda rid: False,
        )
        self.assertEqual(reclaimed["run_id"], 2)
        self.assertEqual(reclaimed["pid"], os.getpid())
        manager.release(reclaim_id, run_id=2)

        busy_id = "obsidian:still-current"
        evidence.write_json_atomic(
            manager.lease_path(busy_id),
            {
                "schema": LEASE_SCHEMA,
                "resource": busy_id,
                "board": self.board,
                "card_id": self.card_id,
                "run_id": 44,
                "pid": dead,
                "process_start": None,
                "candidate_commit": SHA1_A,
                "acquired_at": "2026-01-01T00:00:00+00:00",
            },
        )
        with self.assertRaises(HarnessError) as ctx:
            manager.acquire(
                busy_id,
                board=self.board,
                card_id=self.card_id,
                run_id=3,
                candidate_commit=SHA1_A,
                holder_run_is_current=lambda rid: True,
            )
        self.assertEqual(ctx.exception.code, errors.UI_RESOURCE_BUSY)

    def test_invalid_resource_id(self) -> None:
        manager = self._manager()
        with self.assertRaises(HarnessError) as ctx:
            manager.acquire(
                "obsidian:My Vault",
                board=self.board,
                card_id=self.card_id,
                run_id=1,
                candidate_commit=SHA1_A,
            )
        self.assertEqual(ctx.exception.code, errors.WORKSPACE_INVALID)

    def test_release_readback_failure_and_lease_records(self) -> None:
        manager = self._manager()
        first = manager.acquire(
            "obsidian:history",
            board=self.board,
            card_id=self.card_id,
            run_id=7,
            candidate_commit=SHA1_A,
        )
        manager.release("obsidian:history", run_id=7)
        second = manager.acquire(
            "obsidian:live",
            board=self.board,
            card_id=self.card_id,
            run_id=8,
            candidate_commit=SHA1_B,
        )
        merged = ui_lease.lease_records(self.home)
        active = ui_lease.active_leases(self.home)
        released = ui_lease.load_release_history(self.home)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["lease_id"], second["lease_id"])
        self.assertEqual(len(released), 1)
        self.assertEqual(released[0]["lease_id"], first["lease_id"])
        self.assertEqual(len(merged), 2)
        self.assertEqual(
            {item["lease_id"] for item in merged},
            {first["lease_id"], second["lease_id"]},
        )
        manager.release("obsidian:live", run_id=8)

        resource = "obsidian:stuck"
        lease = manager.acquire(
            resource,
            board=self.board,
            card_id=self.card_id,
            run_id=3,
            candidate_commit=SHA1_A,
        )
        self.assertTrue(lease["lease_id"])
        with mock.patch.object(ui_lease.os, "remove", lambda *_a, **_k: None):
            with self.assertRaises(HarnessError) as noop:
                manager.release(resource, run_id=3)
            self.assertEqual(noop.exception.code, errors.HARNESS_STATE_UNAVAILABLE)
        self.assertTrue(manager.lease_path(resource).exists())

        def boom(*_a, **_k):
            raise OSError("refused")

        with mock.patch.object(ui_lease.os, "remove", boom):
            with self.assertRaises(HarnessError) as raised:
                manager.release(resource, run_id=3)
            self.assertEqual(raised.exception.code, errors.HARNESS_STATE_UNAVAILABLE)
        os.remove(str(manager.lease_path(resource)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
