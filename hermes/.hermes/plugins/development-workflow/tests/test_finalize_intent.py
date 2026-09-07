"""Focused tests for the development-workflow plugin's kanban_finalize_intent.

Runs against the real Hermes Kanban DB API (``hermes_cli.kanban_db`` plus
``hermes_cli.kanban_db_connect.connect``) with an isolated temporary
``HERMES_HOME`` per test — the live board is never touched. The suite must
stay free of ``HermesPluginCompatWarning``: no code path may touch the
deprecated ``kanban_db.connect`` facade.

Run with the installed Hermes interpreter:

    /path/to/hermes-agent/venv/bin/python tests/test_finalize_intent.py

or, from the plugin directory:

    /path/to/hermes-agent/venv/bin/python -m unittest discover -s tests -p 'test_*.py'
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Bootstrap: make the installed Hermes runtime importable when it is not
# already on sys.path (the normal launcher's venv has it via an editable
# install; other interpreters need the checkout path).
#
# The plugin directory itself contains ``tools.py`` (the plan-mandated file
# name). If it lands on sys.path — e.g. ``python -m unittest discover`` run
# from the plugin directory — it shadows Hermes' own top-level ``tools``
# package and breaks Hermes' internal imports. Drop it first: the plugin
# package is loaded below via explicit file locations, not sys.path.
# ---------------------------------------------------------------------------

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
from hermes_cli.kanban_db_connect import connect
from hermes_cli.plugin_compat import HermesPluginCompatWarning

# ---------------------------------------------------------------------------
# Load the plugin package exactly like PluginManager._load_directory_module
# (spec_from_file_location on __init__.py with submodule_search_locations).
# ---------------------------------------------------------------------------

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
tools = _plugin.tools


# ---------------------------------------------------------------------------
# Body fixtures
# ---------------------------------------------------------------------------

def draft_body() -> str:
    """A converged-shaped body left in the draft frontmatter state."""
    return (
        "---\n"
        "schema: development-task.v1\n"
        "intent: draft\n"
        "execution_route: pending\n"
        "ui_acceptance: pending\n"
        "coding_agent: pi\n"
        "---\n"
        "\n"
        "# Goal\n"
        "\n"
        "TBD\n"
        "\n"
        "# Observable acceptance\n"
        "\n"
        "TBD\n"
        "\n"
        "# Included scope\n"
        "\n"
        "None\n"
        "\n"
        "# Non-goals\n"
        "\n"
        "None\n"
        "\n"
        "# Settled decisions\n"
        "\n"
        "None\n"
        "\n"
        "# Open decisions\n"
        "\n"
        "Everything.\n"
        "\n"
        "# Repository grounding\n"
        "\n"
        "TBD\n"
        "\n"
        "# Authority boundaries\n"
        "\n"
        "TBD\n"
    )


def converged_body(
    *,
    intent: str = "converged",
    execution_route: str = "direct",
    ui_acceptance: str = "not-required",
    coding_agent: str = "pi",
    goal: str = "Ship the guard.",
    acceptance: str = "- `hermes plugins doctor development-workflow` passes.",
    included_scope: str = "- the plugin",
    non_goals: str = "- Hermes Core changes",
    settled_decisions: str = "- reuse specify_triage_task()",
    open_decisions: str = "None",
    repository_grounding: str = (
        "- dotfile repo: hermes/.hermes/plugins/development-workflow"
    ),
    authority_boundaries: str = "- no commits, no pushes",
    manual_acceptance: str | None = "[]",
) -> str:
    """Render a converged development-task.v1 body with overridable parts.

    ``manual_acceptance`` is inserted verbatim into the frontmatter (YAML
    flow style works, e.g. ``'["click through the flow"]'``); ``None``
    omits the key entirely.
    """
    frontmatter = [
        "---",
        "schema: development-task.v1",
        f"intent: {intent}",
        f"execution_route: {execution_route}",
        f"ui_acceptance: {ui_acceptance}",
    ]
    if manual_acceptance is not None:
        frontmatter.append(f"manual_acceptance: {manual_acceptance}")
    frontmatter.append(f"coding_agent: {coding_agent}")
    sections = (
        ("Goal", goal),
        ("Observable acceptance", acceptance),
        ("Included scope", included_scope),
        ("Non-goals", non_goals),
        ("Settled decisions", settled_decisions),
        ("Open decisions", open_decisions),
        ("Repository grounding", repository_grounding),
        ("Authority boundaries", authority_boundaries),
    )
    body = "\n".join(frontmatter) + "\n---\n\n"
    body += "\n\n".join(f"# {name}\n\n{content}" for name, content in sections)
    return body + "\n"


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_SCRUB_ENV_VARS = (
    "HERMES_KANBAN_DB",
    "HERMES_KANBAN_BOARD",
    "HERMES_KANBAN_HOME",
    "HERMES_KANBAN_WORKSPACES_ROOT",
    "HERMES_KANBAN_WORKSPACE",
    "HERMES_KANBAN_TASK",
    "HERMES_DELEGATED_CHILD_CONTEXT",
)


class IsolatedKanbanHome(unittest.TestCase):
    """Base case: fresh HERMES_HOME + empty board DB per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / ".hermes"
        self.home.mkdir()
        self._env_backup = os.environ.copy()
        self.addCleanup(self._restore_env)
        os.environ["HERMES_HOME"] = str(self.home)
        for var in _SCRUB_ENV_VARS:
            os.environ.pop(var, None)
        # Keep Path.home() consistent with HERMES_HOME in case any resolution
        # falls back to the platform default (mirrors Hermes' own test suite).
        self._orig_path_home = Path.home
        Path.home = lambda: Path(self._tmp.name)  # type: ignore[assignment]
        self.addCleanup(setattr, Path, "home", self._orig_path_home)
        kb.init_db()

    def _restore_env(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    # -- helpers -------------------------------------------------------------

    def create_triage_card(self, *, title="Dev task", body=None, assignee="default"):
        with connect() as conn:
            return kb.create_task(
                conn,
                title=title,
                body=body if body is not None else draft_body(),
                assignee=assignee,
                triage=True,
                created_by="default",
            )

    def call(self, **kwargs) -> dict:
        raw = tools.handle_finalize_intent(kwargs)
        self.assertIsInstance(raw, str)
        return json.loads(raw)


# ---------------------------------------------------------------------------
# Guard behavior
# ---------------------------------------------------------------------------

class TestGuards(IsolatedKanbanHome):
    def test_delegated_child_context_refused(self) -> None:
        # Create the card first: the DB layer also refuses delegated-child
        # writes, so the fixture must be built in a clean context.
        tid = self.create_triage_card()
        os.environ["HERMES_DELEGATED_CHILD_CONTEXT"] = "1"
        result = self.call(task_id=tid, body=converged_body())
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "guard")
        self.assertIn("delegate_task", result.get("error", ""))
        # Schema-level gate agrees.
        self.assertFalse(tools.check_finalize_intent_available())
        # Nothing was mutated.
        with connect() as conn:
            self.assertEqual(kb.get_task(conn, tid).status, "triage")

    def test_dispatcher_task_worker_refused(self) -> None:
        os.environ["HERMES_KANBAN_TASK"] = "t_worker123"
        tid = self.create_triage_card()
        result = self.call(task_id=tid, body=converged_body())
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "guard")
        self.assertIn("Origin", result.get("error", ""))
        self.assertFalse(tools.check_finalize_intent_available())
        with connect() as conn:
            self.assertEqual(kb.get_task(conn, tid).status, "triage")

    def test_plain_orchestrator_context_available(self) -> None:
        self.assertTrue(tools.check_finalize_intent_available())


# ---------------------------------------------------------------------------
# Input and precondition handling
# ---------------------------------------------------------------------------

class TestInputsAndPreconditions(IsolatedKanbanHome):
    def test_missing_task_id_rejected(self) -> None:
        result = self.call(body=converged_body())
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "input")
        self.assertIn("task_id", result.get("error", ""))

    def test_missing_body_rejected(self) -> None:
        tid = self.create_triage_card()
        result = self.call(task_id=tid, body="   ")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "input")

    def test_blank_title_rejected(self) -> None:
        tid = self.create_triage_card()
        result = self.call(task_id=tid, body=converged_body(), title="   ")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "input")

    def test_task_not_found(self) -> None:
        result = self.call(task_id="t_missing", body=converged_body())
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "precondition")
        self.assertIn("not found", result.get("error", ""))

    def test_non_triage_card_rejected(self) -> None:
        with connect() as conn:
            ready_id = kb.create_task(
                conn, title="Plain task", assignee="default"
            )
        result = self.call(task_id=ready_id, body=converged_body())
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "precondition")
        self.assertIn("only finalizes 'triage'", result.get("error", ""))
        self.assertEqual(result.get("status"), "ready")

    def test_foreign_assignee_rejected(self) -> None:
        tid = self.create_triage_card(assignee="other-profile")
        result = self.call(task_id=tid, body=converged_body())
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "precondition")
        self.assertIn("other-profile", result.get("error", ""))
        with connect() as conn:
            self.assertEqual(kb.get_task(conn, tid).status, "triage")

    def test_invalid_board_slug_rejected(self) -> None:
        tid = self.create_triage_card()
        result = self.call(task_id=tid, body=converged_body(), board="Not A Slug!!")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "input")
        self.assertIn("board", result.get("error", ""))


# ---------------------------------------------------------------------------
# development-task.v1 contract validation
# ---------------------------------------------------------------------------

class TestContractValidation(IsolatedKanbanHome):
    def finalize_expect_violation(self, body, *, needle: str) -> None:
        tid = self.create_triage_card()
        result = self.call(task_id=tid, body=body)
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("stage"), "contract")
        self.assertIn(needle, json.dumps(result))
        with connect() as conn:
            self.assertEqual(kb.get_task(conn, tid).status, "triage")

    def test_draft_intent_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(intent="draft"), needle="intent"
        )

    def test_pending_route_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(execution_route="pending"), needle="execution_route"
        )

    def test_pending_ui_acceptance_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(ui_acceptance="pending"), needle="ui_acceptance"
        )

    def test_unsupported_coding_agent_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(coding_agent="claude"), needle="coding_agent"
        )

    def test_missing_goal_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(goal=""), needle="Goal"
        )

    def test_missing_observable_acceptance_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(acceptance=""), needle="Observable acceptance"
        )

    def test_open_decisions_not_none_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(open_decisions="- which renderer?"), needle="Open decisions"
        )

    def test_missing_frontmatter_rejected(self) -> None:
        self.finalize_expect_violation(
            "# Goal\n\nx\n", needle="frontmatter"
        )

    def test_missing_section_rejected(self) -> None:
        body = converged_body().replace("# Non-goals\n\n- Hermes Core changes\n", "")
        self.finalize_expect_violation(body, needle="sections")

    def test_unknown_frontmatter_key_rejected(self) -> None:
        body = converged_body().replace(
            "coding_agent: pi\n",
            "coding_agent: pi\ncomplexity: simple\n",
        )
        self.finalize_expect_violation(body, needle="complexity")

    def test_all_supported_agents_accepted(self) -> None:
        for agent in ("pi", "cursor", "codex", "opencode"):
            with self.subTest(agent=agent):
                tid = self.create_triage_card()
                result = self.call(
                    task_id=tid, body=converged_body(coding_agent=agent)
                )
                self.assertTrue(result.get("ok"), result)

    # -- manual_acceptance frontmatter rules --------------------------------

    def test_manual_acceptance_non_list_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(manual_acceptance='"click through the flow"'),
            needle="manual_acceptance",
        )

    def test_manual_acceptance_empty_string_item_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(manual_acceptance='[""]'), needle="manual_acceptance"
        )

    def test_manual_acceptance_non_string_item_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(manual_acceptance="[3, true]"),
            needle="manual_acceptance",
        )

    def test_manual_acceptance_with_ui_not_required_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(
                ui_acceptance="not-required",
                manual_acceptance='["click through the flow"]',
            ),
            needle="manual_acceptance",
        )

    def test_manual_acceptance_with_ui_required_accepted(self) -> None:
        tid = self.create_triage_card()
        result = self.call(
            task_id=tid,
            body=converged_body(
                ui_acceptance="required",
                manual_acceptance='["click through the flow"]',
            ),
        )
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("status"), "ready")

    def test_absent_manual_acceptance_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(manual_acceptance=None), needle="manual_acceptance"
        )

    def test_empty_manual_acceptance_with_ui_required_accepted(self) -> None:
        tid = self.create_triage_card()
        result = self.call(
            task_id=tid,
            body=converged_body(ui_acceptance="required", manual_acceptance="[]"),
        )
        self.assertTrue(result.get("ok"), result)

    # -- substantive section rules ------------------------------------------

    def test_included_scope_empty_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(included_scope=""), needle="Included scope"
        )

    def test_included_scope_literal_none_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(included_scope="None"), needle="Included scope"
        )

    def test_authority_boundaries_empty_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(authority_boundaries=""), needle="Authority boundaries"
        )

    def test_authority_boundaries_literal_none_rejected(self) -> None:
        self.finalize_expect_violation(
            converged_body(authority_boundaries="None"),
            needle="Authority boundaries",
        )

    def test_non_goals_literal_none_accepted(self) -> None:
        tid = self.create_triage_card()
        result = self.call(task_id=tid, body=converged_body(non_goals="None"))
        self.assertTrue(result.get("ok"), result)


# ---------------------------------------------------------------------------
# Successful finalization + read-back verification
# ---------------------------------------------------------------------------

class TestFinalization(IsolatedKanbanHome):
    def test_parent_free_card_lands_ready_with_verified_read_back(self) -> None:
        tid = self.create_triage_card()
        body = converged_body()
        result = self.call(task_id=tid, body=body, title="Dev task (converged)")
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("status"), "ready")
        self.assertFalse(result.get("parent_gated"))
        self.assertEqual(result.get("assignee"), "default")
        self.assertEqual(
            result.get("verified"),
            {
                "body": True,
                "assignee": True,
                "status": True,
                "specified_event": True,
            },
        )
        # Independent read-back through the DB API.
        with connect() as conn:
            task = kb.get_task(conn, tid)
            self.assertEqual(task.status, "ready")
            self.assertEqual(task.title, "Dev task (converged)")
            self.assertEqual(task.body, body)  # exact replacement stored
            self.assertEqual(task.assignee, "default")
            self.assertTrue(
                any(e.kind == "specified" for e in kb.list_events(conn, tid))
            )

    def test_unassigned_triage_card_gets_default_assignee(self) -> None:
        tid = self.create_triage_card(assignee=None)
        result = self.call(task_id=tid, body=converged_body())
        self.assertTrue(result.get("ok"), result)
        with connect() as conn:
            self.assertEqual(kb.get_task(conn, tid).assignee, "default")

    def test_parent_gated_card_lands_todo_then_promotes(self) -> None:
        with connect() as conn:
            parent_id = kb.create_task(
                conn, title="Parent", assignee="default"
            )
            child_id = kb.create_task(
                conn,
                title="Child dev task",
                body=draft_body(),
                assignee="default",
                parents=[parent_id],
                triage=True,
                created_by="default",
            )
        self.assertEqual(kb.get_task.__name__, "get_task")  # sanity: real API

        result = self.call(task_id=child_id, body=converged_body())
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("status"), "todo")
        self.assertTrue(result.get("parent_gated"))
        self.assertEqual(result.get("open_parents"), [parent_id])

        with connect() as conn:
            self.assertEqual(kb.get_task(conn, child_id).status, "todo")
            # Parent completion promotes the child through the native path.
            self.assertTrue(kb.complete_task(conn, parent_id, result="done"))
            kb.recompute_ready(conn)
            self.assertEqual(kb.get_task(conn, child_id).status, "ready")

    def test_done_parent_card_lands_ready_immediately(self) -> None:
        with connect() as conn:
            parent_id = kb.create_task(conn, title="Parent", assignee="default")
            kb.complete_task(conn, parent_id, result="done")
            child_id = kb.create_task(
                conn,
                title="Child dev task",
                body=draft_body(),
                assignee="default",
                parents=[parent_id],
                triage=True,
                created_by="default",
            )
        result = self.call(task_id=child_id, body=converged_body())
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("status"), "ready")


# ---------------------------------------------------------------------------
# Deprecated-path hygiene: the handler must complete with
# HermesPluginCompatWarning promoted to an error (no code path may touch
# the ``kanban_db.connect`` facade).
# ---------------------------------------------------------------------------

class TestCompatWarningHygiene(IsolatedKanbanHome):
    def test_registration_and_handler_are_compat_warning_clean(self) -> None:
        tid = self.create_triage_card()
        recorded = {}

        class RecordingCtx:
            def register_tool(self, **kwargs):
                recorded.update(kwargs)

        with warnings.catch_warnings():
            warnings.simplefilter("error", HermesPluginCompatWarning)
            _plugin.register(RecordingCtx())
            raw = recorded["handler"](
                {"task_id": tid, "body": converged_body()}
            )
        result = json.loads(raw)
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("status"), "ready")
        with connect() as conn:
            self.assertEqual(kb.get_task(conn, tid).status, "ready")


# ---------------------------------------------------------------------------
# Registration wiring
# ---------------------------------------------------------------------------

class TestRegistration(unittest.TestCase):
    def test_register_wires_the_single_narrow_tool(self) -> None:
        recorded = {}

        class RecordingCtx:
            def register_tool(self, **kwargs):
                recorded.update(kwargs)

        _plugin.register(RecordingCtx())
        self.assertEqual(recorded.get("name"), "kanban_finalize_intent")
        self.assertEqual(recorded.get("toolset"), "kanban")
        schema = recorded.get("schema")
        self.assertEqual(schema["name"], "kanban_finalize_intent")
        self.assertEqual(
            sorted(schema["parameters"]["properties"].keys()),
            ["board", "body", "task_id", "title"],
        )
        self.assertEqual(
            schema["parameters"]["required"], ["task_id", "body"]
        )
        self.assertTrue(callable(recorded.get("handler")))
        self.assertTrue(callable(recorded.get("check_fn")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
