"""Focused tests for the development-workflow pre_tool_call safety net.

Bootstrap mirrors ``test_devflow_origin.py``: drop the plugin directory from
``sys.path``, load the plugin package via ``spec_from_file_location``, and run
against an isolated temporary ``HERMES_HOME``.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
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
hook = importlib.import_module(_MODULE_NAME + ".harness.hook")

HermesAdapter = hermes_adapter.HermesAdapter

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


def v2_body(
    *,
    schema: str = "development-stage.v2",
    feature_id: str = "ship-guard",
    stage: str = "direct",
    intent: str = "draft",
    ui_acceptance: str = "pending",
    coding_agent: str = "pi",
    manual_acceptance: str = "[]",
    accepted_plan: str = "null",
    goal: str = "Ship the guard.",
    acceptance: str = "- doctor passes.",
    included_scope: str = "- the plugin",
    non_goals: str = "- Hermes Core changes",
    settled_decisions: str = "- reuse specify_triage_task()",
    open_decisions: str = "TBD",
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


def _is_block(result) -> bool:
    return (
        isinstance(result, dict)
        and result.get("action") == "block"
        and isinstance(result.get("message"), str)
        and result["message"].strip() != ""
    )


class IsolatedHookHome(unittest.TestCase):
    """Fresh HERMES_HOME, empty board, and scrubbed dispatcher env per test."""

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
        kb.init_db()
        self.adapter = HermesAdapter(home=self.home)

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _bind_worker_env(self, task) -> None:
        os.environ["HERMES_KANBAN_TASK"] = task.id
        os.environ["HERMES_KANBAN_RUN_ID"] = str(task.current_run_id)
        os.environ["HERMES_KANBAN_CLAIM_LOCK"] = task.claim_lock

    def _create_card(self, *, title: str, body: str | None = None, triage: bool = False) -> str:
        conn = self.adapter.connect()
        try:
            kwargs = {"title": title, "assignee": "default"}
            if body is not None:
                kwargs["body"] = body
            if triage:
                kwargs["triage"] = True
            return self.adapter.create_task(conn, **kwargs)
        finally:
            self.adapter.close(conn)

    def _claim_ready(self, task_id: str):
        conn = self.adapter.connect()
        try:
            claimed = self.adapter.claim_task(conn, task_id)
            self.assertIsNotNone(claimed)
            return claimed
        finally:
            self.adapter.close(conn)

    def _bind_implement_worker(self, *, body: str | None = None):
        tid = self._create_card(title="Implement me", body=body)
        claimed = self._claim_ready(tid)
        self._bind_worker_env(claimed)
        return claimed

    def _bind_managed_implement_worker(self):
        return self._bind_implement_worker(body=v2_body())

    def _bind_review_worker(self, *, body: str | None = None):
        tid = self._create_card(title="Review me", body=body)
        conn = self.adapter.connect()
        try:
            claimed = self.adapter.claim_task(conn, tid)
            self.assertIsNotNone(claimed)
            self.assertTrue(
                self.adapter.request_review(
                    conn, tid, expected_run_id=claimed.current_run_id
                )
            )
            reviewed = self.adapter.claim_review_task(conn, tid)
            self.assertIsNotNone(reviewed)
            self._bind_worker_env(reviewed)
            return reviewed
        finally:
            self.adapter.close(conn)

    def _bind_managed_review_worker(self):
        return self._bind_review_worker(body=v2_body())


class TestNameMatching(unittest.TestCase):
    def test_browser_prefix_minus_readonly(self) -> None:
        self.assertTrue(hook._is_browser_mutator("browser_click"))
        self.assertTrue(hook._is_browser_mutator("browser_console"))
        self.assertFalse(hook._is_browser_mutator("browser_snapshot"))
        self.assertFalse(hook._is_browser_mutator("browser_back"))
        self.assertFalse(hook._is_browser_mutator("browser_get_images"))
        self.assertFalse(hook._is_browser_mutator("write_file"))

    def test_mcp_prefix(self) -> None:
        self.assertTrue(hook._is_mcp_name("mcp_fs_write"))
        self.assertTrue(hook._is_mcp_name("mcp-fs-write"))
        self.assertFalse(hook._is_mcp_name("filesystem_write"))


class TestUnrelatedToolFastAllow(IsolatedHookHome):
    def test_unrelated_tool_skips_adapter(self) -> None:
        def boom(*_a, **_k):
            raise AssertionError("HermesAdapter must not be constructed")

        with patch.object(hook, "HermesAdapter", boom):
            result = hook.pre_tool_call(tool_name="web_search", args={"query": "x"})
        self.assertIsNone(result)

    def test_unknown_tool_without_env_skips_adapter(self) -> None:
        def boom(*_a, **_k):
            raise AssertionError("HermesAdapter must not be constructed")

        with patch.object(hook, "HermesAdapter", boom):
            result = hook.pre_tool_call(tool_name="mystery_tool", args={})
        self.assertIsNone(result)


class TestLifecycleBypass(IsolatedHookHome):
    def test_dev_card_complete_blocked_non_dev_allowed(self) -> None:
        dev_id = self._create_card(title="Dev", body=v2_body(), triage=True)
        plain_id = self._create_card(title="Plain")
        blocked = hook.pre_tool_call(
            tool_name="kanban_complete", args={"task_id": dev_id}
        )
        self.assertTrue(_is_block(blocked), blocked)
        self.assertIn("devflow", blocked["message"])
        allowed = hook.pre_tool_call(
            tool_name="kanban_complete", args={"task_id": plain_id}
        )
        self.assertIsNone(allowed)


class TestNativeAssembly(IsolatedHookHome):
    def test_create_and_link_markers(self) -> None:
        blocked_create = hook.pre_tool_call(
            tool_name="kanban_create",
            args={
                "title": "Feature",
                "body": "---\nschema: development-stage.v2\n---\n",
            },
        )
        self.assertTrue(_is_block(blocked_create), blocked_create)
        self.assertIn("devflow_create_feature", blocked_create["message"])
        fallback = hook.pre_tool_call(
            tool_name="kanban_create",
            args={"title": "Raw", "body": "development-stage.v2 without yaml"},
        )
        self.assertTrue(_is_block(fallback), fallback)
        allowed_create = hook.pre_tool_call(
            tool_name="kanban_create",
            args={"title": "Notes", "body": "plain body"},
        )
        self.assertIsNone(allowed_create)

        dev_id = self._create_card(title="Dev", body=v2_body(), triage=True)
        a = self._create_card(title="A")
        b = self._create_card(title="B")
        blocked_link = hook.pre_tool_call(
            tool_name="kanban_link",
            args={"parent_id": dev_id, "child_id": a},
        )
        self.assertTrue(_is_block(blocked_link), blocked_link)
        allowed_link = hook.pre_tool_call(
            tool_name="kanban_link",
            args={"parent_id": a, "child_id": b},
        )
        self.assertIsNone(allowed_link)


class TestOrdinaryCardNonInterference(IsolatedHookHome):
    def test_ordinary_implement_lifecycle_and_writes_allowed(self) -> None:
        claimed = self._bind_implement_worker()
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_complete", args={"task_id": claimed.id}
            )
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_request_review", args={"task_id": claimed.id}
            )
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="terminal", args={"command": "echo ok"}
            )
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="write_file",
                args={"path": "/tmp/x", "content": "hi"},
            )
        )

    def test_ordinary_review_writes_allowed(self) -> None:
        self._bind_review_worker()
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="write_file",
                args={"path": "/tmp/x", "content": "hi"},
            )
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="Terminal",
                args={"command": "echo ok"},
            )
        )

    def test_ordinary_non_owning_unrestricted(self) -> None:
        claimed = self._bind_implement_worker()
        os.environ["HERMES_KANBAN_RUN_ID"] = str(int(claimed.current_run_id) + 99)
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_complete", args={"task_id": claimed.id}
            )
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="write_file",
                args={"path": "/tmp/x", "content": "hi"},
            )
        )


class TestScriptBypass(IsolatedHookHome):
    def test_origin_direct_relay_and_guard_allowed(self) -> None:
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="Terminal",
                args={"command": "node pi-delegate/scripts/relay.mjs"},
            )
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="Terminal",
                args={"command": "python3 development_external_guard.py status"},
            )
        )

    def test_managed_implement_script_blocked(self) -> None:
        self._bind_managed_implement_worker()
        guard = hook.pre_tool_call(
            tool_name="Terminal",
            args={"command": "python3 development_external_guard.py status"},
        )
        self.assertTrue(_is_block(guard), guard)
        self.assertIn("devflow_start_or_inspect_relay", guard["message"])
        relay = hook.pre_tool_call(
            tool_name="terminal",
            args={"command": "node pi-delegate/scripts/relay.mjs"},
        )
        self.assertTrue(_is_block(relay), relay)

    def test_managed_review_script_blocked(self) -> None:
        self._bind_managed_review_worker()
        review_relay = hook.pre_tool_call(
            tool_name="execute_code",
            args={"code": "node pi-delegate/scripts/relay.mjs"},
        )
        self.assertTrue(_is_block(review_relay), review_relay)
        review_guard = hook.pre_tool_call(
            tool_name="terminal",
            args={"command": "python3 development_external_guard.py status"},
        )
        self.assertTrue(_is_block(review_guard), review_guard)

    def test_ordinary_worker_relay_allowed(self) -> None:
        self._bind_implement_worker()
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="terminal",
                args={"command": "node pi-delegate/scripts/relay.mjs"},
            )
        )


class TestOmittedTaskId(IsolatedHookHome):
    def test_managed_env_complete_without_task_id_blocked(self) -> None:
        self._bind_managed_implement_worker()
        blocked = hook.pre_tool_call(tool_name="kanban_complete", args={})
        self.assertTrue(_is_block(blocked), blocked)

    def test_ordinary_env_complete_without_task_id_allowed(self) -> None:
        self._bind_implement_worker()
        self.assertIsNone(hook.pre_tool_call(tool_name="kanban_complete", args={}))

    def test_comment_requires_explicit_id_and_follows_policy(self) -> None:
        claimed = self._bind_managed_implement_worker()
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_comment",
                args={"body": "progress note"},
            )
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_comment",
                args={"task_id": claimed.id, "body": "progress note"},
            )
        )
        decision = contracts.encode_decision_comment(
            "intent-decision",
            card_id=claimed.id,
            feature_id="ship-guard",
            stage="direct",
            decision="use pi",
            decided_by="origin",
        )
        blocked = hook.pre_tool_call(
            tool_name="kanban_comment",
            args={"task_id": claimed.id, "body": decision},
        )
        self.assertTrue(_is_block(blocked), blocked)


class TestLegacyLookalike(IsolatedHookHome):
    def test_v1_schema_with_eight_sections_is_not_managed(self) -> None:
        tid = self._create_card(
            title="Legacy",
            body=v2_body(schema="development-task.v1"),
            triage=True,
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_complete", args={"task_id": tid}
            )
        )
        other = self._create_card(
            title="Other schema",
            body=v2_body(schema="other-workflow.v9"),
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_request_review", args={"task_id": other}
            )
        )


class TestNonOwningQuarantine(IsolatedHookHome):
    def test_managed_non_owning_deny_by_default(self) -> None:
        claimed = self._bind_managed_implement_worker()
        os.environ["HERMES_KANBAN_RUN_ID"] = str(int(claimed.current_run_id) + 99)
        blocked = hook.pre_tool_call(
            tool_name="kanban_comment",
            args={"task_id": claimed.id, "body": "audit note"},
        )
        self.assertTrue(_is_block(blocked), blocked)
        self.assertEqual(os.environ.get("HERMES_KANBAN_STOP_NUDGE"), "0")
        self.assertIn("non-owning-worker", blocked["message"])
        mutator = hook.pre_tool_call(
            tool_name="write_file",
            args={"path": "/tmp/x", "content": "hi"},
        )
        self.assertTrue(_is_block(mutator), mutator)
        unknown = hook.pre_tool_call(tool_name="mystery_tool", args={})
        self.assertTrue(_is_block(unknown), unknown)
        shown = hook.pre_tool_call(
            tool_name="kanban_show", args={"task_id": claimed.id}
        )
        self.assertIsNone(shown)
        self.assertIsNone(
            hook.pre_tool_call(tool_name="read_file", args={"path": "/tmp/x"})
        )
        self.assertIsNone(
            hook.pre_tool_call(tool_name="devflow_inspect", args={})
        )


class TestOwningWorkerBlockAndComment(IsolatedHookHome):
    def test_block_reason_and_decision_comment(self) -> None:
        self._bind_managed_implement_worker()
        allowed_block = hook.pre_tool_call(
            tool_name="kanban_block",
            args={"task_id": "t_any", "reason": "waiting on product"},
        )
        self.assertIsNone(allowed_block)
        blocked_blank = hook.pre_tool_call(
            tool_name="kanban_block",
            args={"task_id": "t_any", "reason": ""},
        )
        self.assertTrue(_is_block(blocked_blank), blocked_blank)
        allowed_comment = hook.pre_tool_call(
            tool_name="kanban_comment",
            args={"task_id": "t_any", "body": "progress note"},
        )
        self.assertIsNone(allowed_comment)
        decision = contracts.encode_decision_comment(
            "intent-decision",
            card_id="t_any",
            feature_id="ship-guard",
            stage="direct",
            decision="use pi",
            decided_by="origin",
        )
        blocked_decision = hook.pre_tool_call(
            tool_name="kanban_comment",
            args={"task_id": "t_any", "body": decision},
        )
        self.assertTrue(_is_block(blocked_decision), blocked_decision)


class TestUnblockRole(IsolatedHookHome):
    def test_origin_allowed_managed_worker_blocked(self) -> None:
        origin = hook.pre_tool_call(
            tool_name="kanban_unblock", args={"task_id": "t_any"}
        )
        self.assertIsNone(origin)
        self._bind_managed_implement_worker()
        worker = hook.pre_tool_call(
            tool_name="kanban_unblock", args={"task_id": "t_any"}
        )
        self.assertTrue(_is_block(worker), worker)


class TestReviewMutationSurface(IsolatedHookHome):
    def test_managed_review_blocks_mutators_allows_reads(self) -> None:
        self._bind_managed_review_worker()
        blocked_names = (
            "terminal",
            "execute_code",
            "write_file",
            "patch",
            "memory",
            "skill_manage",
            "browser_click",
            "computer_use",
            "cronjob_manage",
            "delegate_task",
            "mystery_tool",
            "mcp_fs_write",
        )
        for name in blocked_names:
            result = hook.pre_tool_call(tool_name=name, args={"x": "1"})
            self.assertTrue(_is_block(result), f"{name}: {result}")
        for name in ("read_file", "search_files", "kanban_show", "devflow_inspect"):
            self.assertIsNone(
                hook.pre_tool_call(tool_name=name, args={"path": "/tmp/x"}),
                name,
            )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_heartbeat", args={}
            )
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_block",
                args={"reason": "waiting on fixture access"},
            )
        )
        self.assertIsNone(
            hook.pre_tool_call(
                tool_name="kanban_comment",
                args={"task_id": "t_any", "body": "evidence note"},
            )
        )

    def test_implement_worker_write_file_allowed(self) -> None:
        self._bind_managed_implement_worker()
        implement = hook.pre_tool_call(
            tool_name="write_file",
            args={"path": "/tmp/x", "content": "hi"},
        )
        self.assertIsNone(implement)


class TestFailClose(IsolatedHookHome):
    def test_connect_failure_blocks_mutations_allows_show(self) -> None:
        with patch.object(
            hook.HermesAdapter, "connect", side_effect=RuntimeError("db down")
        ):
            complete = hook.pre_tool_call(
                tool_name="kanban_complete", args={"task_id": "t_unknown"}
            )
            show = hook.pre_tool_call(
                tool_name="kanban_show", args={"task_id": "t_unknown"}
            )
        self.assertTrue(_is_block(complete), complete)
        self.assertTrue(
            complete["message"].startswith("HARNESS_STATE_UNAVAILABLE:"),
            complete,
        )
        self.assertIsNone(show)


if __name__ == "__main__":
    unittest.main(verbosity=2)
