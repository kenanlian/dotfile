"""Focused tests for Worker-side Development Workflow operations and tools.

Bootstrap mirrors ``test_devflow_origin.py``: drop the plugin directory from
``sys.path``, load the plugin package via ``spec_from_file_location``, and run
against an isolated temporary ``HERMES_HOME``. Git/guard fixtures follow
``test_devflow_evidence.py``.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

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
evidence = importlib.import_module(_MODULE_NAME + ".harness.evidence")
guard_client = importlib.import_module(_MODULE_NAME + ".harness.guard_client")
operations_origin = importlib.import_module(_MODULE_NAME + ".harness.operations_origin")
operations_worker = importlib.import_module(_MODULE_NAME + ".harness.operations_worker")
tools_worker = importlib.import_module(_MODULE_NAME + ".harness.tools_worker")

HermesAdapter = hermes_adapter.HermesAdapter
HarnessError = errors.HarnessError
GuardClient = guard_client.GuardClient

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


SHA256_A = "a" * 64
SHA1_A = "a" * 40


def valid_ui_evidence(**overrides):
    data = {
        "schema": contracts.UI_EVIDENCE_SCHEMA_ID,
        "board": "default",
        "card_id": "t_card",
        "feature_id": "ship-guard",
        "stage": "direct",
        "run_id": 1,
        "attempt_number": 1,
        "candidate_commit": SHA1_A,
        "diff_base": "c" * 40,
        "diff_head": SHA1_A,
        "accepted_plan": None,
        "relay_session_id": "sess-worker-1",
        "artifacts": [{"path": "/tmp/ui/shot.png", "sha256": SHA256_A}],
        "lease": {
            "resource": "obsidian:acceptance",
            "lease_id": "lease-1",
            "holder_run_id": 1,
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


def valid_plan_review(**overrides):
    data = {
        "schema": contracts.PLAN_REVIEW_SCHEMA_ID,
        "board": "default",
        "card_id": "t_card",
        "feature_id": "ship-guard",
        "review_run_id": 1,
        "round": 1,
        "plan": {"path": "/tmp/plan.md", "sha256": SHA256_A},
        "verdict": "pass",
        "summary": "Plan is ready to execute.",
        "required_revisions": [],
    }
    data.update(overrides)
    return data


def valid_execute_review(**overrides):
    data = {
        "schema": contracts.EXECUTE_REVIEW_SCHEMA_ID,
        "card_id": "t_card",
        "review_run_id": 1,
        "round": 1,
        "candidate_commit": "a" * 40,
        "accepted_plan_sha256": "c" * 64,
        "patch_gate": {"verdict": "pass", "findings": []},
        "plan_conformance_gate": {"verdict": "pass", "findings": []},
        "overall": {"verdict": "pass"},
    }
    data.update(overrides)
    return data


class IsolatedWorkerHome(unittest.TestCase):
    """Fresh HERMES_HOME, git repo, guard script, and fake relay argv."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / ".hermes"
        self.home.mkdir()
        self.artifacts = self.root / "development-artifacts"
        self.artifacts.mkdir()
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
        handoff = self.root / "Secret-Projects" / "pi-auto-handoff"
        (handoff / "src").mkdir(parents=True, exist_ok=True)
        (handoff / "package.json").write_text("{}", encoding="utf-8")
        (handoff / "src" / "index.ts").write_text("export {}\n", encoding="utf-8")

        dest_guard = self.home / "scripts" / "development_external_guard.py"
        dest_guard.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(GUARD_SCRIPT, dest_guard)
        real_agent = Path("/Users/kenan/.hermes/hermes-agent")
        if real_agent.is_dir():
            link = self.home / "hermes-agent"
            if not link.exists():
                link.symlink_to(real_agent)

        kb.init_db()
        self.adapter = HermesAdapter(home=self.home)
        self.board = str(self.adapter.get_current_board())
        self._pids: list[int] = []
        self.addCleanup(self._reap)
        self.repo = self.make_repo()
        self.plan_path, self.plan_digest = self._write_plan("default-plan.md")
        self._relay_sleep = 0.05
        self._relay_session = "sess-worker-1"
        self._omit_auto_handoff = False
        self._relay_status = "completed"
        self._relay_error = None
        self._relay_source_status = None
        self._relay_cwd = None
        self._relay_mode = None
        self._final_message = None
        self._review_report = None
        self._review_candidate = None
        self._relay_overrides = {}
        self._relay_argvs: list[list[str]] = []
        self._orig_build_relay_argv = operations_worker.build_relay_argv
        self._argv_patch = patch.object(
            operations_worker, "build_relay_argv", self._fake_argv
        )
        self._argv_patch.start()
        self.addCleanup(self._argv_patch.stop)

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _reap(self) -> None:
        for pid in self._pids:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(pid, signal.SIGKILL)
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGKILL)

    def _default_final_message(self, spec) -> str:
        if self._final_message is not None:
            return self._final_message
        if not getattr(spec, "review", False):
            return "done"
        if spec.skill == "review-plan":
            report = {
                "verdict": "pass",
                "summary": "Plan is ready to execute.",
                "plan": {
                    "path": str(self.plan_path),
                    "sha256": self.plan_digest,
                },
                "required_revisions": [],
            }
        else:
            report = {
                "candidate_commit": self._review_candidate or SHA1_A,
                "accepted_plan": {
                    "path": str(self.plan_path),
                    "sha256": self.plan_digest,
                },
                "patch_gate": {"verdict": "pass", "findings": []},
                "plan_conformance_gate": {"verdict": "pass", "findings": []},
                "overall": {"verdict": "pass"},
            }
        if self._review_report:
            report.update(self._review_report)
        return yaml.safe_dump(report, sort_keys=False)

    def _fake_argv(
        self,
        spec,
        *,
        relay_script,
        brief_path,
        repo,
        out_dir,
        result_path,
        resume_session,
        plan_path,
        model,
    ):
        captured = self._orig_build_relay_argv(
            spec,
            relay_script=relay_script,
            brief_path=brief_path,
            repo=repo,
            out_dir=out_dir,
            result_path=result_path,
            resume_session=resume_session,
            plan_path=plan_path,
            model=model,
        )
        self._relay_argvs.append(list(captured))
        mode = "read-only" if spec.mode == "read" else "write"
        status = self._relay_status
        result = {
            "schema": "delegate-relay.result.v1",
            "status": status,
            "exitCode": 0 if status == "completed" else 1,
            "sessionId": self._relay_session,
            "cwd": self._relay_cwd if self._relay_cwd is not None else str(repo),
            "mode": self._relay_mode if self._relay_mode is not None else mode,
            "requestedModel": model,
            "resolvedModel": model,
            "thinking": spec.thinking or "high",
            "finalMessage": self._default_final_message(spec),
        }
        if status == "unavailable":
            result["sourceStatus"] = self._relay_source_status or "pi_unavailable"
        if self._relay_error:
            result["error"] = self._relay_error
        if spec.auto_handoff and not self._omit_auto_handoff:
            result["autoHandoff"] = {
                "enabled": True,
                "planFile": plan_path,
                "handoffDir": str(Path(out_dir) / "auto-handoff"),
                "extensionRoot": "/tmp/pi-auto-handoff",
            }
        result.update(self._relay_overrides)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        script = (
            f"printf '%s' {shlex.quote(json.dumps(result))} > "
            f"{shlex.quote(str(result_path))}; sleep {self._relay_sleep}"
        )
        return ["/bin/sh", "-c", script]

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
        return repo

    def commit(self, message: str) -> str:
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def pid_alive(self, pid: int) -> bool:
        try:
            waited, _status = os.waitpid(pid, os.WNOHANG)
            if waited == pid:
                return False
        except (ChildProcessError, OSError):
            pass
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        proc = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        state = (proc.stdout or "").strip()
        if proc.returncode == 0 and state.upper().startswith("Z"):
            return False
        return True

    def wait_until(self, predicate, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def payload(self, op, **kwargs) -> dict:
        try:
            result = op(self.adapter, **kwargs)
        except HarnessError as err:
            return err.to_payload()
        self.assertIsInstance(result, dict)
        return result

    def create_feature(self, **kwargs) -> dict:
        self._clear_worker_env()
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

    @contextlib.contextmanager
    def _as_origin(self):
        saved = {
            key: os.environ.get(key)
            for key in (
                "HERMES_KANBAN_TASK",
                "HERMES_KANBAN_RUN_ID",
                "HERMES_KANBAN_CLAIM_LOCK",
            )
        }
        self._clear_worker_env()
        try:
            yield
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def _store_review_evidence(
        self,
        task_id: str,
        data: dict,
        *,
        round_n: int = 1,
        run_id: int | None = None,
        skill: str,
    ) -> Path:
        run_id = int(run_id if run_id is not None else os.environ["HERMES_KANBAN_RUN_ID"])
        dest = evidence.review_round_run_dir(
            evidence.task_dir(self.adapter.artifacts_root, self.board, task_id),
            round_n,
            run_id,
            skill,
        )
        evidence.write_review_evidence(dest, data)
        return dest / evidence.REVIEW_EVIDENCE_FILENAME

    def _write_bound_ui_evidence(
        self,
        task_id: str,
        sha: str,
        *,
        verdict: str = "PASS",
        lease: dict | None = None,
        **overrides,
    ) -> Path:
        run_id = int(os.environ["HERMES_KANBAN_RUN_ID"])
        state = self._guard(task_id).read_state() or {}
        baseline = str((state.get("baseline") or {}).get("head") or ("c" * 40))
        landings = state.get("landings") or []
        attempt_number = 1
        if landings and isinstance(landings[-1], dict):
            attempt_number = int(landings[-1].get("attempt_number") or 1)
        conn = self.adapter.connect()
        try:
            task = self.adapter.get_task(conn, task_id)
            card = contracts.parse_stage_body(task.body)
        finally:
            self.adapter.close(conn)
        accepted = None
        if card.stage == "execute-plan" and isinstance(card.accepted_plan, dict):
            accepted = {
                "path": card.accepted_plan.get("path"),
                "sha256": card.accepted_plan.get("sha256"),
            }
        lease_block = lease or {
            "resource": "obsidian:acceptance",
            "lease_id": "lease-1",
            "holder_run_id": run_id,
            "acquired_at": "2026-09-10T00:00:00Z",
            "released_at": "2026-09-10T00:01:00Z",
        }
        data = valid_ui_evidence(
            board=self.board,
            card_id=task_id,
            feature_id=card.feature_id,
            stage=card.stage,
            run_id=run_id,
            attempt_number=attempt_number,
            candidate_commit=sha,
            diff_base=baseline,
            diff_head=sha,
            accepted_plan=accepted,
            relay_session_id=self._relay_session,
            lease=lease_block,
            verdict=verdict,
            scenarios=[{"name": "open the note and confirm the heading", "verdict": verdict}],
        )
        data.update(overrides)
        path = (
            evidence.ui_dir(
                evidence.task_dir(self.adapter.artifacts_root, self.board, task_id),
                sha,
                run_id,
            )
            / "evidence.json"
        )
        evidence.write_json_atomic(path, data)
        return path

    def _clear_worker_env(self) -> None:
        for var in (
            "HERMES_KANBAN_TASK",
            "HERMES_KANBAN_RUN_ID",
            "HERMES_KANBAN_CLAIM_LOCK",
        ):
            os.environ.pop(var, None)

    def _bind_worker_env(self, task) -> None:
        os.environ["HERMES_KANBAN_TASK"] = task.id
        os.environ["HERMES_KANBAN_RUN_ID"] = str(task.current_run_id)
        os.environ["HERMES_KANBAN_CLAIM_LOCK"] = task.claim_lock

    def _claim_implement(self, task_id: str):
        self._clear_worker_env()
        conn = self.adapter.connect()
        try:
            claimed = self.adapter.claim_task(conn, task_id)
            self.assertIsNotNone(claimed, "claim_task returned None")
            self._bind_worker_env(claimed)
            return claimed
        finally:
            self.adapter.close(conn)

    def _claim_review(self, task_id: str):
        self._clear_worker_env()
        conn = self.adapter.connect()
        try:
            claimed = self.adapter.claim_review_task(conn, task_id)
            self.assertIsNotNone(claimed, "claim_review_task returned None")
            self._bind_worker_env(claimed)
            return claimed
        finally:
            self.adapter.close(conn)

    def _track(self, result: dict) -> None:
        pid = result.get("pid")
        if isinstance(pid, int):
            self._pids.append(pid)

    def _kill(self, pid: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, signal.SIGKILL)

    def _write_brief(self, card_id: str, text: str | None = None) -> Path:
        path = self.root / "briefs" / f"{card_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text is not None else f"Work on card {card_id}\n")
        return path

    def _write_plan(self, name: str = "accepted-plan.md") -> tuple[Path, str]:
        path = self.root / "plans" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Accepted plan\n\nDo the work.\n")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _guard(self, card_id: str) -> GuardClient:
        return GuardClient(
            script_path=self.adapter.guard_script_path,
            home=self.home,
            board=self.board,
            card_id=card_id,
            artifacts_root=self.adapter.artifacts_root,
        )

    def _land(self, card_id: str, message: str = "land candidate") -> str:
        trailer = f"Kanban-Task: {card_id}"
        sha = self.commit(f"{message}\n\n{trailer}")
        rc, payload = self._guard(card_id).record_commit(sha)
        self.assertEqual(rc, 0, payload)
        return sha

    def _consume_relay(self, brief: Path, repo: Path | None = None) -> dict:
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(repo or self.repo),
        )
        self.assertTrue(spawned.get("ok"), spawned)
        self.assertEqual(spawned.get("outcome"), "spawned", spawned)
        self._track(spawned)
        pid = spawned["pid"]
        result_path = Path(spawned["result_path"])
        self.assertTrue(
            self.wait_until(lambda: result_path.is_file()),
            "fake relay should write result.json",
        )
        self._kill(pid)
        self.assertTrue(
            self.wait_until(lambda: not self.pid_alive(pid)),
            "fake relay should exit after kill",
        )
        consumed = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(repo or self.repo),
        )
        self.assertTrue(consumed.get("ok"), consumed)
        self.assertEqual(consumed.get("outcome"), "terminal", consumed)
        return consumed

    def _ensure_terminal_relay(self, brief: Path, repo: Path | None = None) -> dict:
        first = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(repo or self.repo),
        )
        if first.get("outcome") == "terminal":
            return first
        self.assertTrue(first.get("ok"), first)
        self.assertEqual(first.get("outcome"), "spawned", first)
        self._track(first)
        pid = first["pid"]
        result_path = Path(first["result_path"])
        self.assertTrue(
            self.wait_until(lambda: result_path.is_file()),
            "fake relay should write result.json",
        )
        self._kill(pid)
        self.assertTrue(
            self.wait_until(lambda: not self.pid_alive(pid)),
            "fake relay should exit after kill",
        )
        consumed = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(repo or self.repo),
        )
        self.assertTrue(consumed.get("ok"), consumed)
        self.assertEqual(consumed.get("outcome"), "terminal", consumed)
        return consumed

    def _complete_in_review(
        self, task_id: str, plan_path: Path | None = None, digest: str | None = None
    ) -> None:
        """Complete a write-plan card the way the real review PASS does.

        The harness review-pass path records the accepted-plan identity on
        the completed run; execute finalization verifies it, so fixtures must
        write the same metadata.
        """
        claimed = self._claim_review(task_id)
        metadata = None
        if plan_path is not None and digest is not None:
            metadata = {
                "accepted_plan": {
                    "card_id": task_id,
                    "path": str(plan_path),
                    "sha256": digest,
                }
            }
        conn = self.adapter.connect()
        try:
            ok = self.adapter.complete_task(
                conn,
                task_id,
                summary="approved",
                metadata=metadata,
                expected_run_id=claimed.current_run_id,
            )
            self.assertTrue(ok)
        finally:
            self.adapter.close(conn)
        self._clear_worker_env()


class TestStartOrInspectWriteMode(IsolatedWorkerHome):
    def test_origin_refusal(self) -> None:
        created = self.create_feature()
        task_id = created["cards"][0]["task_id"]
        brief = self._write_brief(task_id)
        result = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.IMPLEMENT_ROLE_REQUIRED)
        self.assertIn("Origin commissions workers", result.get("message") or "")

    def test_spawn_attach_terminal_and_refusals(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="relay-happy")
        wp_id = created["cards"][0]["task_id"]
        finalized = self.payload(
            operations_origin.op_finalize_stage,
            task_id=wp_id,
            body=v2_body(feature_id="relay-happy", stage="write-plan"),
        )
        self.assertTrue(finalized.get("ok"), finalized)
        self._claim_implement(wp_id)
        brief = self._write_brief(wp_id)

        self._relay_sleep = 20
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertTrue(spawned.get("ok"), spawned)
        self.assertEqual(spawned.get("outcome"), "spawned")
        self.assertEqual(spawned.get("attempt_number"), 1)
        self.assertEqual(spawned.get("skill"), "write-plan")
        self.assertEqual(spawned.get("mode"), "write")
        self._track(spawned)
        state = self._guard(wp_id).read_state()
        self.assertIsNotNone(state)
        self.assertEqual(state["schema"], "development-external-execution.v2")
        self.assertEqual(len(state["attempts"]), 1)
        self.assertEqual(state["attempts"][0]["operation"], "planning")

        attached = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(attached.get("outcome"), "attach", attached)
        self.assertEqual(attached.get("pid"), spawned.get("pid"))

        result_path = Path(spawned["result_path"])
        self.assertTrue(self.wait_until(lambda: result_path.is_file()))
        self._kill(spawned["pid"])
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(spawned["pid"])))
        consumed = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(consumed.get("outcome"), "terminal", consumed)
        self.assertEqual(consumed.get("session_id"), self._relay_session)
        sealed = self._guard(wp_id).read_state()
        self.assertEqual(sealed["attempts"][0]["state"], "terminal")
        self.assertEqual(sealed["attempts"][0]["session_id"], self._relay_session)

        plan_path, _digest = self._write_plan()
        handoff = self.payload(
            operations_worker.op_implement_handoff,
            summary="plan ready",
            plan_path=str(plan_path),
        )
        self.assertTrue(handoff.get("ok"), handoff)
        self.assertEqual(handoff.get("status"), "review")

        self._claim_review(wp_id)
        review_spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertTrue(review_spawned.get("ok"), review_spawned)
        self.assertEqual(review_spawned.get("outcome"), "spawned")
        self.assertEqual(review_spawned.get("mode"), "read")
        self.assertEqual(review_spawned.get("skill"), "review-plan")
        self._track(review_spawned)
        self.assertEqual(len(self._guard(wp_id).read_state()["attempts"]), 1)
        refused = self.payload(
            operations_worker.op_implement_handoff, summary="nope"
        )
        self.assertEqual(refused.get("code"), errors.IMPLEMENT_ROLE_REQUIRED)

    def test_brief_missing_and_card_id(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="brief-miss")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="brief-miss", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        missing = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(self.root / "no-such-brief.md"),
            repo=str(self.repo),
        )
        self.assertEqual(missing.get("code"), errors.BRIEF_MISSING)
        empty = self.root / "briefs" / "empty.md"
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_text("   \n")
        self.assertEqual(
            self.payload(
                operations_worker.op_start_or_inspect_relay,
                brief_path=str(empty),
                repo=str(self.repo),
            ).get("code"),
            errors.BRIEF_MISSING,
        )
        wrong = self._write_brief(wp_id, "no card identity here\n")
        result = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(wrong),
            repo=str(self.repo),
        )
        self.assertEqual(result.get("code"), errors.BRIEF_MISSING)
        self.assertEqual((result.get("details") or {}).get("rule"), "card-id")

    def test_non_dev_card(self) -> None:
        conn = self.adapter.connect()
        try:
            task_id = self.adapter.create_task(
                conn, title="Plain card", assignee="default"
            )
        finally:
            self.adapter.close(conn)
        claimed = self._claim_implement(task_id)
        brief = self._write_brief(claimed.id)
        result = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(result.get("code"), errors.CARD_CONTRACT_INVALID)
        self.assertIn("not a managed", result.get("message") or "")

    def test_uncertain_reserved_attempt(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="uncertain")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="uncertain", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        client = self._guard(wp_id)
        rc, initialized = client.init(self.repo)
        self.assertEqual(rc, 0, initialized)
        head = self.git("rev-parse", "HEAD").strip()
        out_dir = str(self.artifacts / "reserved-out")
        state = {
            "schema": "development-external-execution.v2",
            "card_id": wp_id,
            "repo": str(self.repo),
            "baseline": {"head": head, "porcelain": []},
            "attempts": [
                {
                    "number": 1,
                    "operation": "planning",
                    "state": "reserved",
                    "pid": None,
                    "process_start": None,
                    "out_dir": out_dir,
                    "result_path": str(Path(out_dir) / "result.json"),
                    "session_id": None,
                    "terminal_status": None,
                }
            ],
            "landings": [],
            "updated_at": "2026-09-10T00:00:00Z",
        }
        client.state_path().write_text(json.dumps(state) + "\n", encoding="utf-8")
        brief = self._write_brief(wp_id)
        result = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(result.get("code"), errors.RELAY_ATTEMPT_UNCERTAIN)
        self.assertIn("never retry", result.get("remediation") or "")


class TestExecutePlanHandoff(IsolatedWorkerHome):
    def _write_plan_done(self, feature_id: str) -> tuple[str, str, Path, str]:
        created = self.create_feature(route="two-stage", feature_id=feature_id)
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id=feature_id, stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        brief = self._write_brief(wp_id)
        self._consume_relay(brief)
        plan_path, digest = self._write_plan(f"{feature_id}.md")
        handoff = self.payload(
            operations_worker.op_implement_handoff,
            summary="plan ready",
            plan_path=str(plan_path),
        )
        self.assertTrue(handoff.get("ok"), handoff)
        self._complete_in_review(wp_id, plan_path, digest)
        return wp_id, ex_id, plan_path, digest

    def test_execute_handoff_manifest_and_failures(self) -> None:
        wp_id, ex_id, plan_path, digest = self._write_plan_done("exec-happy")
        ex_body = v2_body(
            feature_id="exec-happy",
            stage="execute-plan",
            accepted_plan=accepted_plan_yaml(
                card_id=wp_id, path=str(plan_path), sha256=digest
            ),
        )
        finalized = self.payload(
            operations_origin.op_finalize_stage, task_id=ex_id, body=ex_body
        )
        self.assertTrue(finalized.get("ok"), finalized)
        claimed = self._claim_implement(ex_id)
        brief = self._write_brief(ex_id)
        self._consume_relay(brief)

        missing_land = self.payload(
            operations_worker.op_implement_handoff, summary="no landing"
        )
        self.assertEqual(missing_land.get("code"), errors.CANDIDATE_NOT_FROZEN)

        sha = self._land(ex_id)
        handoff = self.payload(
            operations_worker.op_implement_handoff, summary="candidate ready"
        )
        self.assertTrue(handoff.get("ok"), handoff)
        self.assertEqual(handoff.get("status"), "review")
        self.assertEqual(handoff.get("candidate_commit"), sha)
        manifest_path = Path(handoff["manifest_path"])
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], contracts.CANDIDATE_SCHEMA_ID)
        self.assertEqual(manifest["stage"], "execute-plan")
        self.assertEqual(manifest["candidate_commit"], sha)
        self.assertEqual(manifest["implement_run_id"], claimed.current_run_id)

    def _complete_ready_via_claim(
        self, task_id: str, plan_path: Path | None = None, digest: str | None = None
    ) -> None:
        claimed = self._claim_implement(task_id)
        metadata = None
        if plan_path is not None and digest is not None:
            metadata = {
                "accepted_plan": {
                    "card_id": task_id,
                    "path": str(plan_path),
                    "sha256": digest,
                }
            }
        conn = self.adapter.connect()
        try:
            ok = self.adapter.complete_task(
                conn,
                task_id,
                summary="done",
                metadata=metadata,
                expected_run_id=claimed.current_run_id,
            )
            self.assertTrue(ok)
        finally:
            self.adapter.close(conn)
        self._clear_worker_env()

    def test_auto_handoff_invalid_on_consume(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="no-handoff")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="no-handoff", stage="write-plan"),
            ).get("ok")
        )
        plan_path, digest = self._write_plan("no-handoff.md")
        self._complete_ready_via_claim(wp_id, plan_path, digest)
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=ex_id,
                body=v2_body(
                    feature_id="no-handoff",
                    stage="execute-plan",
                    accepted_plan=accepted_plan_yaml(
                        card_id=wp_id, path=str(plan_path), sha256=digest
                    ),
                ),
            ).get("ok")
        )
        self._claim_implement(ex_id)
        self._omit_auto_handoff = True
        brief = self._write_brief(ex_id)
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(spawned.get("outcome"), "spawned", spawned)
        self._track(spawned)
        self._kill(spawned["pid"])
        self.wait_until(lambda: not self.pid_alive(spawned["pid"]))
        bad = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(bad.get("code"), errors.AUTO_HANDOFF_INVALID)

    def test_direct_ui_required_gate(self) -> None:
        created = self.create_feature(feature_id="ui-direct")
        task_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=task_id,
                body=v2_body(
                    feature_id="ui-direct",
                    stage="direct",
                    ui_acceptance="required",
                    manual_acceptance="[]",
                ),
            ).get("ok")
        )
        claimed = self._claim_implement(task_id)
        brief = self._write_brief(task_id)
        self._consume_relay(brief)
        sha = self._land(task_id)
        missing = self.payload(
            operations_worker.op_implement_handoff, summary="needs ui"
        )
        self.assertEqual(missing.get("code"), errors.UI_ACCEPTANCE_INCOMPLETE)

        acquired = self.payload(
            operations_worker.op_ui_lease,
            action="acquire",
            resource_id="obsidian:acceptance",
        )
        self.assertTrue(acquired.get("ok"), acquired)
        lease = acquired.get("lease") or {}
        self._write_bound_ui_evidence(
            task_id,
            sha,
            lease={
                "resource": "obsidian:acceptance",
                "lease_id": lease.get("lease_id"),
                "holder_run_id": claimed.current_run_id,
                "acquired_at": lease.get("acquired_at") or "2026-09-10T00:00:00Z",
                "released_at": "2026-09-10T00:01:00Z",
            },
        )
        done = self.payload(
            operations_worker.op_implement_handoff, summary="ui pass"
        )
        self.assertTrue(done.get("ok"), done)
        self.assertEqual(done.get("status"), "done")
        self.assertEqual(done.get("handoff"), "complete")


class TestReviewRelay(IsolatedWorkerHome):
    def test_review_spawn_attach_terminal_no_new_guard_attempt(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="review-relay")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="review-relay", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        brief_wp = self._write_brief(wp_id)
        self._consume_relay(brief_wp)
        plan_path, digest = self._write_plan("review-relay.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        self._complete_in_review(wp_id, plan_path, digest)
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=ex_id,
                body=v2_body(
                    feature_id="review-relay",
                    stage="execute-plan",
                    accepted_plan=accepted_plan_yaml(
                        card_id=wp_id, path=str(plan_path), sha256=digest
                    ),
                ),
            ).get("ok")
        )
        self._claim_implement(ex_id)
        brief_ex = self._write_brief(ex_id)
        self._consume_relay(brief_ex)
        self._land(ex_id)
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff, summary="candidate ready"
            ).get("ok")
        )
        attempts_before = len(self._guard(ex_id).read_state()["attempts"])
        claimed = self._claim_review(ex_id)
        self._relay_sleep = 20
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief_ex),
            repo=str(self.repo),
        )
        self.assertTrue(spawned.get("ok"), spawned)
        self.assertEqual(spawned.get("outcome"), "spawned")
        self.assertEqual(spawned.get("mode"), "read")
        self.assertEqual(spawned.get("skill"), "review-execute-candidate")
        self._track(spawned)
        relay_json = Path(spawned["out_dir"]) / "relay.json"
        self.assertTrue(relay_json.is_file())
        record = json.loads(relay_json.read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], "devflow-review-relay.v1")
        self.assertEqual(
            len(self._guard(ex_id).read_state()["attempts"]), attempts_before
        )

        attached = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief_ex),
            repo=str(self.repo),
        )
        self.assertEqual(attached.get("outcome"), "attach", attached)
        self._kill(spawned["pid"])
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(spawned["pid"])))
        consumed = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief_ex),
            repo=str(self.repo),
        )
        self.assertEqual(consumed.get("outcome"), "terminal", consumed)
        self.assertEqual(consumed.get("session_id"), self._relay_session)
        self.assertEqual(
            len(self._guard(ex_id).read_state()["attempts"]), attempts_before
        )
        self.assertEqual(claimed.status, "running")


class TestReviewVerdict(IsolatedWorkerHome):
    def _execute_in_review(self, feature_id: str):
        created = self.create_feature(route="two-stage", feature_id=feature_id)
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id=feature_id, stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        self._consume_relay(self._write_brief(wp_id))
        plan_path, digest = self._write_plan(f"{feature_id}.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        self._complete_in_review(wp_id, plan_path, digest)
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=ex_id,
                body=v2_body(
                    feature_id=feature_id,
                    stage="execute-plan",
                    accepted_plan=accepted_plan_yaml(
                        card_id=wp_id, path=str(plan_path), sha256=digest
                    ),
                ),
            ).get("ok")
        )
        claimed = self._claim_implement(ex_id)
        self._consume_relay(self._write_brief(ex_id))
        sha = self._land(ex_id)
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff, summary="candidate ready"
            ).get("ok")
        )
        review = self._claim_review(ex_id)
        return ex_id, sha, digest, review, claimed

    def _write_execute_review(self, **overrides) -> Path:
        path = self.root / "reviews" / f"{overrides.get('card_id', 'r')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_json_atomic(path, valid_execute_review(**overrides))
        return path

    def test_execute_pass_and_identity_mismatch(self) -> None:
        ex_id, sha, digest, review, _impl = self._execute_in_review("verdict-exec")
        self._store_review_evidence(
            ex_id,
            valid_execute_review(
                card_id=ex_id,
                review_run_id=review.current_run_id,
                round=1,
                candidate_commit="0" * 40,
                accepted_plan_sha256=digest,
            ),
            run_id=review.current_run_id,
            skill="review-execute-candidate",
        )
        mismatch = self.payload(
            operations_worker.op_review_verdict,
            verdict="pass",
        )
        self.assertEqual(mismatch.get("code"), errors.EVIDENCE_IDENTITY_MISMATCH)

        dest = evidence.review_round_run_dir(
            evidence.task_dir(self.adapter.artifacts_root, self.board, ex_id),
            1,
            review.current_run_id,
            "review-execute-candidate",
        )
        (dest / evidence.REVIEW_EVIDENCE_FILENAME).unlink(missing_ok=True)
        self._store_review_evidence(
            ex_id,
            valid_execute_review(
                card_id=ex_id,
                review_run_id=review.current_run_id,
                round=1,
                candidate_commit=sha,
                accepted_plan_sha256=digest,
            ),
            run_id=review.current_run_id,
            skill="review-execute-candidate",
        )
        passed = self.payload(
            operations_worker.op_review_verdict,
            verdict="pass",
        )
        self.assertTrue(passed.get("ok"), passed)
        self.assertEqual(passed.get("status"), "done")

    def test_execute_revise_requests_changes(self) -> None:
        ex_id, sha, digest, review, _ = self._execute_in_review("verdict-revise")
        self._store_review_evidence(
            ex_id,
            valid_execute_review(
                card_id=ex_id,
                review_run_id=review.current_run_id,
                round=1,
                candidate_commit=sha,
                accepted_plan_sha256=digest,
                patch_gate={"verdict": "fail", "findings": ["diff too wide"]},
                plan_conformance_gate={"verdict": "pass", "findings": []},
                overall={"verdict": "revise"},
            ),
            run_id=review.current_run_id,
            skill="review-execute-candidate",
        )
        revised = self.payload(
            operations_worker.op_review_verdict,
            verdict="revise",
            reason="patch gate failed",
        )
        self.assertTrue(revised.get("ok"), revised)
        self.assertEqual(revised.get("verdict"), "revise")
        conn = self.adapter.connect()
        try:
            task = self.adapter.get_task(conn, ex_id)
            kinds = [e.kind for e in self.adapter.list_events(conn, ex_id)]
        finally:
            self.adapter.close(conn)
        self.assertEqual(task.status, "ready")
        self.assertIn("changes_requested", kinds)

    def test_execute_blocked(self) -> None:
        ex_id, _sha, _digest, _review, _ = self._execute_in_review("verdict-block")
        blocked = self.payload(
            operations_worker.op_review_verdict,
            verdict="blocked",
            block_kind="needs_input",
            reason="needs a human decision on scope",
        )
        self.assertTrue(blocked.get("ok"), blocked)
        self.assertEqual(blocked.get("verdict"), "blocked")
        conn = self.adapter.connect()
        try:
            task = self.adapter.get_task(conn, ex_id)
            kinds = [e.kind for e in self.adapter.list_events(conn, ex_id)]
        finally:
            self.adapter.close(conn)
        self.assertEqual(task.status, "blocked")
        self.assertIn("blocked", kinds)

    def test_write_plan_pass_and_round_limit(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="plan-pass")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="plan-pass", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        self._consume_relay(self._write_brief(wp_id))
        plan_path, digest = self._write_plan("plan-pass.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        review = self._claim_review(wp_id)
        self._store_review_evidence(
            wp_id,
            valid_plan_review(
                board=self.board,
                card_id=wp_id,
                feature_id="plan-pass",
                review_run_id=review.current_run_id,
                round=1,
                plan={"path": str(plan_path), "sha256": digest},
            ),
            run_id=review.current_run_id,
            skill="review-plan",
        )
        passed = self.payload(
            operations_worker.op_review_verdict,
            verdict="pass",
        )
        self.assertTrue(passed.get("ok"), passed)
        self.assertEqual(passed.get("status"), "done")
        self.assertEqual(passed.get("accepted_plan")["sha256"], digest)
        self.assertEqual(review.status, "running")

        created = self.create_feature(route="two-stage", feature_id="round-limit")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="round-limit", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        self._consume_relay(self._write_brief(wp_id))
        plan_path, _digest = self._write_plan("round-limit.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        for index in range(3):
            claimed_r = self._claim_review(wp_id)
            conn = self.adapter.connect()
            try:
                ok, _info = self.adapter.request_changes(
                    conn,
                    wp_id,
                    reason=f"revise round {index + 1}",
                    expected_run_id=claimed_r.current_run_id,
                )
                self.assertTrue(ok)
            finally:
                self.adapter.close(conn)
            claimed_i = self._claim_implement(wp_id)
            conn = self.adapter.connect()
            try:
                requested = self.adapter.request_review(
                    conn,
                    wp_id,
                    summary=f"re-review {index + 1}",
                    expected_run_id=claimed_i.current_run_id,
                )
                self.assertTrue(requested)
            finally:
                self.adapter.close(conn)
        self._claim_review(wp_id)
        limited = self.payload(
            operations_worker.op_review_verdict,
            verdict="pass",
        )
        self.assertEqual(limited.get("code"), errors.ROUND_LIMIT_REACHED)


class TestUiLease(IsolatedWorkerHome):
    def test_acquire_busy_release_and_not_required(self) -> None:
        created = self.create_feature(feature_id="lease-ui")
        task_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=task_id,
                body=v2_body(
                    feature_id="lease-ui",
                    stage="direct",
                    ui_acceptance="required",
                    manual_acceptance="[]",
                ),
            ).get("ok")
        )
        self._claim_implement(task_id)
        brief = self._write_brief(task_id)
        self._consume_relay(brief)
        self._land(task_id)
        acquired = self.payload(
            operations_worker.op_ui_lease,
            action="acquire",
            resource_id="obsidian:acceptance",
        )
        self.assertTrue(acquired.get("ok"), acquired)
        lease = acquired.get("lease") or {}
        self.assertEqual(lease.get("schema"), "development-ui-lease.v1")
        self.assertTrue(acquired.get("lease_id") or lease.get("lease_id"))
        lease_path = (
            self.home
            / "runtime"
            / "development-workflow"
            / "ui-leases"
            / "obsidian:acceptance.json"
        )
        self.assertTrue(lease_path.is_file())

        busy = self.payload(
            operations_worker.op_ui_lease,
            action="acquire",
            resource_id="obsidian:acceptance",
        )
        self.assertEqual(busy.get("code"), errors.UI_RESOURCE_BUSY)

        released = self.payload(
            operations_worker.op_ui_lease,
            action="release",
            resource_id="obsidian:acceptance",
        )
        self.assertTrue(released.get("ok"), released)
        self.assertTrue(released.get("released"))

        conn = self.adapter.connect()
        try:
            ok = self.adapter.complete_task(
                conn,
                task_id,
                summary="done for next card",
                expected_run_id=int(os.environ["HERMES_KANBAN_RUN_ID"]),
            )
            self.assertTrue(ok)
        finally:
            self.adapter.close(conn)

        created2 = self.create_feature(feature_id="lease-none")
        other_id = created2["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=other_id,
                body=v2_body(
                    feature_id="lease-none",
                    stage="direct",
                    ui_acceptance="not-required",
                ),
            ).get("ok")
        )
        self._claim_implement(other_id)
        refused = self.payload(
            operations_worker.op_ui_lease,
            action="acquire",
            resource_id="obsidian:acceptance",
        )
        self.assertEqual(refused.get("code"), errors.UI_ACCEPTANCE_INCOMPLETE)


class TestWorkerToolsSurface(IsolatedWorkerHome):
    def test_tools_export_and_visibility(self) -> None:
        names = [item["name"] for item in tools_worker.TOOLS]
        self.assertEqual(
            names,
            [
                "devflow_start_or_inspect_relay",
                "devflow_ui_lease",
                "devflow_implement_handoff",
                "devflow_review_verdict",
            ],
        )
        for item in tools_worker.TOOLS:
            self.assertEqual(item["toolset"], "kanban")
            self.assertTrue(callable(item["handler"]))
            self.assertTrue(callable(item["check_fn"]))
            self.assertEqual(item["check_fn"], tools_worker.check_worker_tools_available)
        self.assertFalse(tools_worker.check_worker_tools_available())
        os.environ["HERMES_KANBAN_TASK"] = "t_worker"
        self.assertTrue(tools_worker.check_worker_tools_available())
        os.environ["HERMES_DELEGATED_CHILD_CONTEXT"] = "1"
        self.assertFalse(tools_worker.check_worker_tools_available())

    def test_handler_origin_refusal_envelope(self) -> None:
        raw = tools_worker.handle_start_or_inspect_relay(
            {"brief_path": "/tmp/missing.md", "repo": str(self.repo)}
        )
        result = json.loads(raw)
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("code"), errors.IMPLEMENT_ROLE_REQUIRED)

    def test_review_verdict_schema_drops_arbitrary_path(self) -> None:
        schema = tools_worker.DEVFLOW_REVIEW_VERDICT_SCHEMA
        props = schema["parameters"]["properties"]
        self.assertNotIn("review_result_path", props)
        self.assertIn("block_kind", props)
        self.assertEqual(
            props["block_kind"]["enum"],
            list(operations_worker.BLOCK_KINDS),
        )


class TestRelaySafetyRegressions(IsolatedWorkerHome):
    def test_failed_relay_cannot_handoff(self) -> None:
        created = self.create_feature(feature_id="failed-relay")
        task_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=task_id,
                body=v2_body(feature_id="failed-relay", stage="direct"),
            ).get("ok")
        )
        self._claim_implement(task_id)
        brief = self._write_brief(task_id)
        self._relay_status = "failed"
        self._relay_error = "unit test exploded"
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(spawned.get("outcome"), "spawned", spawned)
        self._track(spawned)
        self.assertTrue(self.wait_until(lambda: Path(spawned["result_path"]).is_file()))
        self._kill(spawned["pid"])
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(spawned["pid"])))
        consumed = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertFalse(consumed.get("ok"), consumed)
        self.assertEqual(consumed.get("code"), errors.RELAY_ATTEMPT_UNCERTAIN)
        self.assertEqual((consumed.get("details") or {}).get("status"), "failed")
        blocked = self.payload(
            operations_worker.op_implement_handoff, summary="should fail"
        )
        self.assertFalse(blocked.get("ok"), blocked)
        self.assertEqual(blocked.get("code"), errors.RELAY_ATTEMPT_UNCERTAIN)
        self.assertIn("cannot hand off a non-successful", blocked.get("message") or "")

    def test_terminal_reinspection_does_not_duplicate(self) -> None:
        created = self.create_feature(feature_id="no-dup")
        task_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=task_id,
                body=v2_body(feature_id="no-dup", stage="direct"),
            ).get("ok")
        )
        self._claim_implement(task_id)
        brief = self._write_brief(task_id)
        first = self._consume_relay(brief)
        self.assertEqual(first.get("outcome"), "terminal")
        out_dir = self._guard(task_id).read_state()["attempts"][0]["out_dir"]
        count = len(self._guard(task_id).read_state()["attempts"])
        second = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(second.get("outcome"), "terminal", second)
        state = self._guard(task_id).read_state()
        self.assertEqual(len(state["attempts"]), count)
        self.assertEqual(state["attempts"][0]["out_dir"], out_dir)

    def test_write_plan_rework_resumes_prior_session(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="wp-rework")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="wp-rework", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        brief = self._write_brief(wp_id)
        consumed = self._consume_relay(brief)
        prior = consumed.get("session_id") or self._relay_session
        plan_path, _digest = self._write_plan("wp-rework.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        claimed_r = self._claim_review(wp_id)
        conn = self.adapter.connect()
        try:
            ok, _info = self.adapter.request_changes(
                conn,
                wp_id,
                reason="please revise the plan",
                expected_run_id=claimed_r.current_run_id,
            )
            self.assertTrue(ok)
        finally:
            self.adapter.close(conn)
        self._claim_implement(wp_id)
        self._relay_argvs.clear()
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertTrue(spawned.get("ok"), spawned)
        self.assertEqual(spawned.get("outcome"), "spawned")
        self.assertEqual(spawned.get("operation"), "rework")
        self.assertEqual(spawned.get("attempt_number"), 2)
        self._track(spawned)
        argv = self._relay_argvs[-1]
        self.assertIn("--session", argv)
        self.assertEqual(argv[argv.index("--session") + 1], prior)
        self._kill(spawned["pid"])

    def test_ui_fail_rework_and_no_duplicate_before_evidence(self) -> None:
        created = self.create_feature(feature_id="ui-fail-rework")
        task_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=task_id,
                body=v2_body(
                    feature_id="ui-fail-rework",
                    stage="direct",
                    ui_acceptance="required",
                    manual_acceptance="[]",
                ),
            ).get("ok")
        )
        self._claim_implement(task_id)
        brief = self._write_brief(task_id)
        self._consume_relay(brief)
        count = len(self._guard(task_id).read_state()["attempts"])
        again = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(again.get("outcome"), "terminal", again)
        self.assertEqual(len(self._guard(task_id).read_state()["attempts"]), count)
        sha = self._land(task_id)
        self._write_bound_ui_evidence(task_id, sha, verdict="FAIL")
        self._relay_argvs.clear()
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(spawned.get("outcome"), "spawned", spawned)
        self.assertEqual(spawned.get("operation"), "rework")
        self._track(spawned)
        argv = self._relay_argvs[-1]
        self.assertIn("--session", argv)
        self.assertEqual(argv[argv.index("--session") + 1], self._relay_session)
        self._kill(spawned["pid"])

    def test_one_time_model_fallback(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="fallback")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="fallback", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        brief = self._write_brief(wp_id)
        self._relay_status = "failed"
        self._relay_error = "provider rate limit 429"
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self._track(spawned)
        self.assertTrue(self.wait_until(lambda: Path(spawned["result_path"]).is_file()))
        self._kill(spawned["pid"])
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(spawned["pid"])))
        failed = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertFalse(failed.get("ok"), failed)
        self._relay_argvs.clear()
        retry = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(retry.get("outcome"), "spawned", retry)
        self.assertTrue(retry.get("fallback"))
        self._track(retry)
        argv = self._relay_argvs[-1]
        self.assertIn("zai-coding-cn/glm-5.3", argv)
        self.assertIn("--session", argv)
        self.assertTrue(self.wait_until(lambda: Path(retry["result_path"]).is_file()))
        self._kill(retry["pid"])
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(retry["pid"])))
        second_fail = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertFalse(second_fail.get("ok"), second_fail)
        blocked = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertFalse(blocked.get("ok"), blocked)
        self.assertIn("fallback", (blocked.get("remediation") or "").lower())

        created = self.create_feature(route="two-stage", feature_id="unavail")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="unavail", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        brief = self._write_brief(wp_id)
        self._relay_status = "unavailable"
        self._relay_error = None
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self._track(spawned)
        self.assertTrue(self.wait_until(lambda: Path(spawned["result_path"]).is_file()))
        self._kill(spawned["pid"])
        self.wait_until(lambda: not self.pid_alive(spawned["pid"]))
        unavailable = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(unavailable.get("code"), errors.RELAY_ATTEMPT_UNCERTAIN)
        self.assertIn("pi binary missing", unavailable.get("remediation") or "")

        created = self.create_feature(route="two-stage", feature_id="nonprov")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="nonprov", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        brief = self._write_brief(wp_id)
        self._relay_status = "failed"
        self._relay_error = "segfault in plugin"
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self._track(spawned)
        self.assertTrue(self.wait_until(lambda: Path(spawned["result_path"]).is_file()))
        self._kill(spawned["pid"])
        self.wait_until(lambda: not self.pid_alive(spawned["pid"]))
        nonprov = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(nonprov.get("code"), errors.RELAY_ATTEMPT_UNCERTAIN)
        self.assertIn("never silently", nonprov.get("remediation") or "")


class TestReviewEnvelopeAndVerdict(IsolatedWorkerHome):
    def test_review_envelope_interop(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="rev-env")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="rev-env", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        brief = self._write_brief(wp_id)
        self._consume_relay(brief)
        plan_path, digest = self._write_plan("rev-env.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        review = self._claim_review(wp_id)
        self._review_report = {
            "plan": {"path": str(plan_path), "sha256": digest},
        }
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(spawned.get("outcome"), "spawned", spawned)
        self._track(spawned)
        self.assertTrue(self.wait_until(lambda: Path(spawned["result_path"]).is_file()))
        self._kill(spawned["pid"])
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(spawned["pid"])))
        consumed = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(consumed.get("outcome"), "terminal", consumed)
        evidence_path = Path(consumed["review_evidence_path"])
        self.assertTrue(evidence_path.is_file())
        first = evidence_path.read_text(encoding="utf-8")
        reused = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(reused.get("outcome"), "terminal", reused)
        self.assertEqual(evidence_path.read_text(encoding="utf-8"), first)

        self._final_message = ""
        run_dir = Path(spawned["out_dir"])
        (run_dir / "relay.json").unlink()
        self._claim_review(wp_id) if False else None
        malformed = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        # empty finalMessage on a new spawn then consume
        if malformed.get("outcome") == "spawned":
            self._track(malformed)
            self.assertTrue(
                self.wait_until(lambda: Path(malformed["result_path"]).is_file())
            )
            self._kill(malformed["pid"])
            self.wait_until(lambda: not self.pid_alive(malformed["pid"]))
            malformed = self.payload(
                operations_worker.op_start_or_inspect_relay,
                brief_path=str(brief),
                repo=str(self.repo),
            )
        self.assertEqual(malformed.get("code"), errors.RELAY_ATTEMPT_UNCERTAIN)

        created = self.create_feature(route="two-stage", feature_id="rev-bad")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="rev-bad", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        brief = self._write_brief(wp_id)
        self._final_message = None
        self._relay_status = "completed"
        self._consume_relay(brief)
        plan_path, digest = self._write_plan("rev-bad.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        self._claim_review(wp_id)
        self._relay_cwd = "/tmp/wrong-cwd"
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self._track(spawned)
        self.wait_until(lambda: Path(spawned["result_path"]).is_file())
        self._kill(spawned["pid"])
        self.wait_until(lambda: not self.pid_alive(spawned["pid"]))
        bad_cwd = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(bad_cwd.get("code"), errors.RELAY_ATTEMPT_UNCERTAIN)

        created = self.create_feature(route="two-stage", feature_id="rev-id")
        wp_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="rev-id", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        brief = self._write_brief(wp_id)
        self._relay_cwd = None
        self._consume_relay(brief)
        plan_path, digest = self._write_plan("rev-id.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        self._claim_review(wp_id)
        self._review_report = {"card_id": "not-this-card"}
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self._track(spawned)
        self.wait_until(lambda: Path(spawned["result_path"]).is_file())
        self._kill(spawned["pid"])
        self.wait_until(lambda: not self.pid_alive(spawned["pid"]))
        mismatch = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(mismatch.get("code"), errors.EVIDENCE_IDENTITY_MISMATCH)

    def test_verdict_consumes_run_scoped_evidence(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="verdict-scope")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="verdict-scope", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        self._consume_relay(self._write_brief(wp_id))
        plan_path, digest = self._write_plan("verdict-scope.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        self._complete_in_review(wp_id, plan_path, digest)
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=ex_id,
                body=v2_body(
                    feature_id="verdict-scope",
                    stage="execute-plan",
                    accepted_plan=accepted_plan_yaml(
                        card_id=wp_id, path=str(plan_path), sha256=digest
                    ),
                ),
            ).get("ok")
        )
        self._claim_implement(ex_id)
        self._consume_relay(self._write_brief(ex_id))
        sha = self._land(ex_id)
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff, summary="candidate ready"
            ).get("ok")
        )
        review = self._claim_review(ex_id)
        missing = self.payload(
            operations_worker.op_review_verdict, verdict="pass"
        )
        self.assertEqual(missing.get("code"), errors.REVIEW_GATE_INCOMPLETE)
        self._store_review_evidence(
            ex_id,
            valid_execute_review(
                card_id=ex_id,
                review_run_id=review.current_run_id,
                round=99,
                candidate_commit=sha,
                accepted_plan_sha256=digest,
            ),
            round_n=1,
            run_id=review.current_run_id,
            skill="review-execute-candidate",
        )
        wrong_round = self.payload(
            operations_worker.op_review_verdict, verdict="pass"
        )
        self.assertEqual(wrong_round.get("code"), errors.EVIDENCE_IDENTITY_MISMATCH)
        dest = evidence.review_round_run_dir(
            evidence.task_dir(self.adapter.artifacts_root, self.board, ex_id),
            1,
            review.current_run_id,
            "review-execute-candidate",
        )
        (dest / evidence.REVIEW_EVIDENCE_FILENAME).unlink()
        self._store_review_evidence(
            ex_id,
            valid_execute_review(
                card_id=ex_id,
                review_run_id=review.current_run_id,
                round=1,
                candidate_commit=sha,
                accepted_plan_sha256=digest,
                patch_gate={"verdict": "fail", "findings": ["x"]},
                plan_conformance_gate={"verdict": "pass", "findings": []},
                overall={"verdict": "pass"},
            ),
            run_id=review.current_run_id,
            skill="review-execute-candidate",
        )
        inconsistent = self.payload(
            operations_worker.op_review_verdict, verdict="pass"
        )
        self.assertEqual(inconsistent.get("code"), errors.REVIEW_GATE_INCOMPLETE)
        raw = tools_worker.handle_review_verdict(
            {"verdict": "blocked", "reason": "needs a human"}
        )
        self.assertEqual(json.loads(raw).get("code"), errors.CARD_CONTRACT_INVALID)
        (dest / evidence.REVIEW_EVIDENCE_FILENAME).unlink()
        self._store_review_evidence(
            ex_id,
            valid_execute_review(
                card_id=ex_id,
                review_run_id=review.current_run_id,
                round=1,
                candidate_commit=sha,
                accepted_plan_sha256=digest,
            ),
            run_id=review.current_run_id,
            skill="review-execute-candidate",
        )
        blocked = self.payload(
            operations_worker.op_review_verdict,
            verdict="blocked",
            block_kind="capability",
            reason="missing renderer fixture",
        )
        self.assertTrue(blocked.get("ok"), blocked)
        conn = self.adapter.connect()
        try:
            task = self.adapter.get_task(conn, ex_id)
            events = list(self.adapter.list_events(conn, ex_id) or [])
        finally:
            self.adapter.close(conn)
        self.assertEqual(task.status, "blocked")
        self.assertEqual(getattr(task, "block_kind", None), "capability")
        self.assertIn("blocked", [event.kind for event in events])

    def test_round_four_requires_authorization_and_changed_candidate(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="round-four")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="round-four", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        self._consume_relay(self._write_brief(wp_id))
        plan_path, digest = self._write_plan("round-four.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        self._complete_in_review(wp_id, plan_path, digest)
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=ex_id,
                body=v2_body(
                    feature_id="round-four",
                    stage="execute-plan",
                    accepted_plan=accepted_plan_yaml(
                        card_id=wp_id, path=str(plan_path), sha256=digest
                    ),
                ),
            ).get("ok")
        )
        self._claim_implement(ex_id)
        brief = self._write_brief(ex_id)
        self._consume_relay(brief)
        sha = self._land(ex_id)
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff, summary="candidate ready"
            ).get("ok")
        )
        for index in range(3):
            claimed_r = self._claim_review(ex_id)
            conn = self.adapter.connect()
            try:
                ok, _info = self.adapter.request_changes(
                    conn,
                    ex_id,
                    reason=f"revise round {index + 1}",
                    expected_run_id=claimed_r.current_run_id,
                )
                self.assertTrue(ok)
            finally:
                self.adapter.close(conn)
            self._claim_implement(ex_id)
            self._ensure_terminal_relay(brief)
            sha = self._land(ex_id, message=f"land round {index + 2}")
            self.assertTrue(
                self.payload(
                    operations_worker.op_implement_handoff,
                    summary=f"candidate r{index + 2}",
                ).get("ok")
            )
        review = self._claim_review(ex_id)
        self._store_review_evidence(
            ex_id,
            valid_execute_review(
                card_id=ex_id,
                review_run_id=review.current_run_id,
                round=4,
                candidate_commit=sha,
                accepted_plan_sha256=digest,
            ),
            round_n=4,
            run_id=review.current_run_id,
            skill="review-execute-candidate",
        )
        limited = self.payload(
            operations_worker.op_review_verdict, verdict="pass"
        )
        self.assertEqual(limited.get("code"), errors.ROUND_LIMIT_REACHED)
        with self._as_origin():
            authorized = self.payload(
                operations_origin.op_record_decision,
                task_id=ex_id,
                kind="round-authorization",
                decision="allow a fourth review round",
                round=4,
                candidate_commit=sha,
            )
        self.assertTrue(authorized.get("ok"), authorized)
        os.environ["HERMES_KANBAN_TASK"] = review.id
        os.environ["HERMES_KANBAN_RUN_ID"] = str(review.current_run_id)
        os.environ["HERMES_KANBAN_CLAIM_LOCK"] = review.claim_lock
        passed = self.payload(
            operations_worker.op_review_verdict, verdict="pass"
        )
        self.assertTrue(passed.get("ok"), passed)
        self.assertEqual(passed.get("status"), "done")


class TestManifestUiAndContractGates(IsolatedWorkerHome):
    def test_manifest_written_before_ui_and_immutable(self) -> None:
        created = self.create_feature(feature_id="manifest-order")
        task_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=task_id,
                body=v2_body(
                    feature_id="manifest-order",
                    stage="direct",
                    ui_acceptance="required",
                    manual_acceptance="[]",
                ),
            ).get("ok")
        )
        claimed = self._claim_implement(task_id)
        brief = self._write_brief(task_id)
        self._consume_relay(brief)
        sha = self._land(task_id)
        missing = self.payload(
            operations_worker.op_implement_handoff, summary="needs ui"
        )
        self.assertEqual(missing.get("code"), errors.UI_ACCEPTANCE_INCOMPLETE)
        dest = (
            evidence.task_dir(self.adapter.artifacts_root, self.board, task_id)
            / "candidates"
            / sha
            / "candidate.json"
        )
        self.assertTrue(dest.is_file())
        conn = self.adapter.connect()
        try:
            task = self.adapter.get_task(conn, task_id)
            stage = contracts.parse_stage_body(task.body)
        finally:
            self.adapter.close(conn)
        with self.assertRaises(HarnessError) as caught:
            operations_worker._write_manifest(
                adapter=self.adapter,
                board=self.board,
                card_id=task_id,
                stage=stage,
                candidate=sha,
                baseline_head="b" * 40,
                implement_run_id=int(claimed.current_run_id),
                attempt_number=1,
            )
        self.assertEqual(caught.exception.code, errors.CANDIDATE_CHANGED)

    def test_ui_binding_rejects_wrong_lease_and_candidate(self) -> None:
        created = self.create_feature(feature_id="ui-bind")
        task_id = created["cards"][0]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=task_id,
                body=v2_body(
                    feature_id="ui-bind",
                    stage="direct",
                    ui_acceptance="required",
                    manual_acceptance="[]",
                ),
            ).get("ok")
        )
        claimed = self._claim_implement(task_id)
        brief = self._write_brief(task_id)
        self._consume_relay(brief)
        sha = self._land(task_id)
        acquired = self.payload(
            operations_worker.op_ui_lease,
            action="acquire",
            resource_id="obsidian:acceptance",
        )
        lease = acquired.get("lease") or {}
        self._write_bound_ui_evidence(
            task_id,
            sha,
            lease={
                "resource": "obsidian:acceptance",
                "lease_id": "not-the-lease",
                "holder_run_id": claimed.current_run_id,
                "acquired_at": "2026-09-10T00:00:00Z",
                "released_at": "2026-09-10T00:01:00Z",
            },
        )
        wrong_lease = self.payload(
            operations_worker.op_implement_handoff, summary="bad lease"
        )
        self.assertIn(
            wrong_lease.get("code"),
            {errors.EVIDENCE_IDENTITY_MISMATCH, errors.UI_ACCEPTANCE_INCOMPLETE},
        )
        dest = (
            evidence.ui_dir(
                evidence.task_dir(self.adapter.artifacts_root, self.board, task_id),
                sha,
                claimed.current_run_id,
            )
            / "evidence.json"
        )
        dest.unlink()
        self._write_bound_ui_evidence(
            task_id,
            sha,
            lease={
                "resource": "obsidian:acceptance",
                "lease_id": lease.get("lease_id"),
                "holder_run_id": 999,
                "acquired_at": lease.get("acquired_at") or "2026-09-10T00:00:00Z",
                "released_at": "2026-09-10T00:01:00Z",
            },
        )
        wrong_holder = self.payload(
            operations_worker.op_implement_handoff, summary="bad holder"
        )
        self.assertIn(
            wrong_holder.get("code"),
            {errors.EVIDENCE_IDENTITY_MISMATCH, errors.UI_ACCEPTANCE_INCOMPLETE},
        )
        dest.unlink()
        self._write_bound_ui_evidence(
            task_id,
            sha,
            lease={
                "resource": "obsidian:acceptance",
                "lease_id": lease.get("lease_id"),
                "holder_run_id": claimed.current_run_id,
                "acquired_at": lease.get("acquired_at") or "2026-09-10T00:00:00Z",
                "released_at": "2026-09-10T00:01:00Z",
            },
            candidate_commit="0" * 40,
            diff_head="0" * 40,
        )
        wrong_candidate = self.payload(
            operations_worker.op_implement_handoff, summary="bad candidate"
        )
        self.assertIn(
            wrong_candidate.get("code"),
            {errors.EVIDENCE_IDENTITY_MISMATCH, errors.UI_ACCEPTANCE_INCOMPLETE},
        )

    def test_worker_contract_gate(self) -> None:
        draft = self.adapter
        conn = draft.connect()
        try:
            tid = draft.create_task(
                conn,
                title="Draft card",
                body=v2_body(intent="draft", ui_acceptance="pending"),
                assignee="default",
                workspace_kind="dir",
                workspace_path=str(self.repo),
            )
            claimed = draft.claim_task(conn, tid)
            self.assertIsNotNone(claimed)
            self._bind_worker_env(claimed)
        finally:
            draft.close(conn)
        refused = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(self._write_brief(claimed.id)),
            repo=str(self.repo),
        )
        self.assertEqual(refused.get("code"), errors.CARD_CONTRACT_INVALID)

        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn,
                title="Wrong assignee",
                body=v2_body(),
                assignee="coder",
                workspace_kind="dir",
                workspace_path=str(self.repo),
            )
            claimed = self.adapter.claim_task(conn, tid)
            self.assertIsNotNone(claimed)
            self._bind_worker_env(claimed)
        finally:
            self.adapter.close(conn)
        wrong = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(self._write_brief(claimed.id)),
            repo=str(self.repo),
        )
        self.assertEqual(wrong.get("code"), errors.RUN_NOT_OWNED)

        conn = self.adapter.connect()
        try:
            tid = self.adapter.create_task(
                conn,
                title="Scratch workspace",
                body=v2_body(),
                assignee="default",
                workspace_kind="scratch",
                workspace_path=str(self.repo),
            )
            claimed = self.adapter.claim_task(conn, tid)
            self.assertIsNotNone(claimed)
            self._bind_worker_env(claimed)
        finally:
            self.adapter.close(conn)
        scratch = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(self._write_brief(claimed.id)),
            repo=str(self.repo),
        )
        self.assertEqual(scratch.get("code"), errors.WORKSPACE_INVALID)

    def test_amendment_invalidates_execute_until_respecified(self) -> None:
        created = self.create_feature(route="two-stage", feature_id="amend-gate")
        wp_id = created["cards"][0]["task_id"]
        ex_id = created["cards"][1]["task_id"]
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=wp_id,
                body=v2_body(feature_id="amend-gate", stage="write-plan"),
            ).get("ok")
        )
        self._claim_implement(wp_id)
        self._consume_relay(self._write_brief(wp_id))
        plan_path, digest = self._write_plan("amend-gate.md")
        self.assertTrue(
            self.payload(
                operations_worker.op_implement_handoff,
                summary="plan ready",
                plan_path=str(plan_path),
            ).get("ok")
        )
        self._complete_in_review(wp_id, plan_path, digest)
        self.assertTrue(
            self.payload(
                operations_origin.op_finalize_stage,
                task_id=ex_id,
                body=v2_body(
                    feature_id="amend-gate",
                    stage="execute-plan",
                    accepted_plan=accepted_plan_yaml(
                        card_id=wp_id, path=str(plan_path), sha256=digest
                    ),
                ),
            ).get("ok")
        )
        time.sleep(1.1)
        with self._as_origin():
            recorded = self.payload(
                operations_origin.op_record_decision,
                task_id=ex_id,
                kind="amendment",
                decision="change the accepted plan scope",
                affects_accepted_plan=True,
            )
        self.assertTrue(recorded.get("ok"), recorded)
        self._claim_implement(ex_id)
        brief = self._write_brief(ex_id)
        blocked = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertEqual(blocked.get("code"), errors.PLAN_IDENTITY_MISSING)
        handoff_blocked = self.payload(
            operations_worker.op_implement_handoff, summary="nope"
        )
        self.assertEqual(handoff_blocked.get("code"), errors.PLAN_IDENTITY_MISSING)
        time.sleep(1.1)
        conn = self.adapter.connect()
        try:
            with self.adapter.write_txn(conn):
                kb._append_event(conn, ex_id, "specified", {})
        finally:
            self.adapter.close(conn)
        spawned = self.payload(
            operations_worker.op_start_or_inspect_relay,
            brief_path=str(brief),
            repo=str(self.repo),
        )
        self.assertTrue(spawned.get("ok"), spawned)
        self.assertEqual(spawned.get("outcome"), "spawned")
        self._track(spawned)
        self._kill(spawned["pid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
