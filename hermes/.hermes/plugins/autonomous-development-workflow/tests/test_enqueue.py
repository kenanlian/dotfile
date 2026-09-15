"""Safe enqueue, JSON-only Kanban CLI, and serial predecessor chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugin_imports import import_plugin

_cli = import_plugin("cli")
_config = import_plugin("config")
_service = import_plugin("controller.service")
_store = import_plugin("controller.store")
_types = import_plugin("controller.types")

PluginConfig = _types.PluginConfig
WorkflowConflict = _types.WorkflowConflict
WorkflowProtocolError = _types.WorkflowProtocolError
WorkflowStore = _store.WorkflowStore
build_kanban_create_argv = _cli.build_kanban_create_argv
build_kanban_link_argv = _cli.build_kanban_link_argv
build_kanban_show_argv = _cli.build_kanban_show_argv
build_kanban_unblock_argv = _cli.build_kanban_unblock_argv
enqueue_workflow = _service.enqueue_workflow
load_plugin_config = _config.load_plugin_config
run_argv = _service.run_argv
setup_autodev_cli = _cli.setup_autodev_cli


def _sha(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _config(state_root: Path) -> PluginConfig:
    return PluginConfig(
        profile="autodev",
        state_root=str(state_root),
        harness_command=("/usr/bin/node", "/abs/harness.mjs"),
        main_branch="main",
        poll_interval_seconds=5,
        advance_wait_seconds=60,
    )


def _snapshot(repo: Path, *, branch: str = "main", head: str = "a" * 40, clean: bool = True):
    real = str(repo.resolve())
    return {
        "repo_root": real,
        "git_root": real,
        "branch": branch,
        "head": head,
        "clean": clean,
    }


class FakeKanban:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.cards_by_key: dict[str, dict] = {}
        self.cards_by_id: dict[str, dict] = {}
        self.links: list[tuple[str, str]] = []
        self.unblocked: set[str] = set()
        self.fail_on: str | None = None
        self.human_create = False
        self._n = 0

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
            raise AssertionError("kanban runner must receive argv list of strings")
        if any("workflow_template_id" in item for item in argv):
            raise AssertionError("enqueue must not read or write workflow_template_id")
        self.calls.append(list(argv))
        action = _kanban_action(argv)
        if self.fail_on == action:
            raise RuntimeError(f"crash before {action}")
        if action == "create":
            return self._create(argv)
        if action == "link":
            parent, child = argv[-2], argv[-1]
            self.links.append((parent, child))
            return 0, f"Linked {parent} -> {child}\n", ""
        if action == "show":
            task_id = argv[argv.index("show") + 1]
            task = self.cards_by_id[task_id]
            parents = [parent for parent, child in self.links if child == task_id]
            payload = {"task": dict(task), "parents": parents, "children": []}
            return 0, json.dumps(payload), ""
        if action == "unblock":
            task_id = argv[argv.index("unblock") + 1]
            task = self.cards_by_id[task_id]
            parents = [parent for parent, child in self.links if child == task_id]
            task["status"] = "todo" if parents else "ready"
            self.unblocked.add(task_id)
            return 0, f"Unblocked {task_id}\n", ""
        raise AssertionError(f"unexpected argv {argv}")

    def _create(self, argv: list[str]) -> tuple[int, str, str]:
        if self.human_create:
            return 0, "Created t_human  (blocked, assignee=autodev)\n", ""
        key = _flag(argv, "--idempotency-key")
        if key in self.cards_by_key:
            return 0, json.dumps(self.cards_by_key[key]), ""
        self._n += 1
        task_id = f"t_{self._n}"
        workspace = _flag(argv, "--workspace")
        path = workspace.split(":", 1)[1]
        task = {
            "id": task_id,
            "title": argv[argv.index("create") + 1],
            "assignee": _flag(argv, "--assignee"),
            "status": "blocked",
            "workspace_kind": "dir",
            "workspace_path": path,
            "workflow_template_id": None,
        }
        self.cards_by_key[key] = task
        self.cards_by_id[task_id] = task
        return 0, json.dumps(task), ""


def _kanban_action(argv: list[str]) -> str:
    for name in ("create", "link", "show", "unblock"):
        if name in argv:
            return name
    return "unknown"


def _flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


class ArgvBuilderTests(unittest.TestCase):
    def test_kanban_argv_is_pure_list_with_json_and_blocked_create(self) -> None:
        create = build_kanban_create_argv(
            board="proj",
            title="Ship login",
            body="notice",
            assignee="autodev",
            repo="/abs/repo",
            idempotency_key="key-1",
        )
        self.assertIsInstance(create, list)
        self.assertEqual(create[0], "hermes")
        self.assertNotIn(True, [item for item in create if not isinstance(item, str)])
        self.assertIn("--json", create)
        self.assertEqual(_flag(create, "--board"), "proj")
        self.assertEqual(_flag(create, "--initial-status"), "blocked")
        self.assertEqual(_flag(create, "--workspace"), "dir:/abs/repo")
        self.assertEqual(_flag(create, "--idempotency-key"), "key-1")
        self.assertNotIn("workflow_template_id", create)
        self.assertNotIn("--workflow-template-id", create)

        link = build_kanban_link_argv(board="proj", parent="t_1", child="t_2")
        self.assertEqual(link[0], "hermes")
        self.assertIn("link", link)
        self.assertEqual(link[-2:], ["t_1", "t_2"])

        show = build_kanban_show_argv(board="proj", task_id="t_2")
        self.assertIn("--json", show)
        self.assertNotIn("workflow_template_id", " ".join(show))

        unblock = build_kanban_unblock_argv(board="proj", task_id="t_2")
        self.assertIn("unblock", unblock)

    def test_run_argv_uses_list_and_shell_false(self) -> None:
        source = Path(_service.__file__).read_text(encoding="utf-8")
        self.assertIn("shell=False", source)
        self.assertNotIn("shell=True", source)
        self.assertIn("shell=False", Path(_cli.__file__).read_text(encoding="utf-8"))
        with self.assertRaises(WorkflowProtocolError):
            run_argv("hermes kanban create")  # type: ignore[arg-type]
        completed = run_argv(["/usr/bin/true"])
        self.assertEqual(completed[0], 0)

    def test_cli_parser_accepts_enqueue_flags(self) -> None:
        parser = argparse.ArgumentParser()
        setup_autodev_cli(parser)
        args = parser.parse_args(
            [
                "enqueue",
                "--board",
                "proj",
                "--repo",
                "/abs/repo",
                "--title",
                "Ship login",
                "--requirement",
                "/abs/requirement.md",
                "--profile",
                "autodev",
                "--idempotency-key",
                "k1",
            ]
        )
        self.assertEqual(args.autodev_command, "enqueue")
        self.assertEqual(args.board, "proj")
        self.assertEqual(args.idempotency_key, "k1")


class EnqueueWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-enqueue-")
        self.root = Path(self._tmp.name)
        self.state_root = self.root / "state"
        self.state_root.mkdir()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.requirement = self.root / "requirement.md"
        self.requirement.write_text("# Need login\n", encoding="utf-8")
        self.store = WorkflowStore(str(self.state_root))
        self.kanban = FakeKanban()
        self.config = _config(self.state_root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _enqueue(self, **overrides):
        kwargs = {
            "board": "proj",
            "repo": str(self.repo),
            "title": "Ship login",
            "requirement": str(self.requirement),
            "profile": "autodev",
            "idempotency_key": "key-1",
            "config": self.config,
            "store": self.store,
            "run_argv": self.kanban,
            "inspect_repo": lambda repo, main_branch: _snapshot(self.repo),
        }
        kwargs.update(overrides)
        return enqueue_workflow(**kwargs)

    def test_rejects_dirty_or_mismatched_repo_before_create(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            self._enqueue(
                inspect_repo=lambda repo, main_branch: _snapshot(self.repo, clean=False)
            )
        with self.assertRaises(WorkflowProtocolError):
            self._enqueue(
                inspect_repo=lambda repo, main_branch: _snapshot(self.repo, branch="dev")
            )
        self.assertEqual(self.kanban.calls, [])
        self.assertIsNone(self.store.get_intake("key-1"))

    def test_happy_path_creates_blocked_card_manifest_artifact_then_unblocks(self) -> None:
        result = self._enqueue()
        self.assertEqual(result["task_id"], "t_1")
        self.assertEqual(result["status"], "published")
        self.assertEqual(self.kanban.cards_by_id["t_1"]["status"], "ready")
        self.assertIn("t_1", self.kanban.unblocked)
        create = next(call for call in self.kanban.calls if "create" in call)
        self.assertEqual(_flag(create, "--initial-status"), "blocked")
        self.assertIn("--json", create)
        manifest = self.store.get_manifest("proj", "t_1")
        self.assertEqual(manifest["templateId"], "autonomous-development.v1")
        self.assertEqual(manifest["workflowStatus"], "queued")
        self.assertEqual(manifest["repoRoot"], str(self.repo.resolve()))
        artifact = self.store.get_artifact("proj", "t_1", "requirement", 1)
        self.assertTrue(Path(artifact["path"]).is_file())
        self.assertTrue(artifact["path"].endswith("requirement-v1.json"))

    def test_links_serial_predecessor_and_unblocks_to_todo(self) -> None:
        first = self._enqueue(idempotency_key="key-1", title="First")
        second = self._enqueue(idempotency_key="key-2", title="Second")
        self.assertEqual(second["predecessor_task_id"], first["task_id"])
        self.assertIn((first["task_id"], second["task_id"]), self.kanban.links)
        self.assertEqual(self.kanban.cards_by_id[second["task_id"]]["status"], "todo")
        show = json.loads(
            self.kanban(
                build_kanban_show_argv(board="proj", task_id=second["task_id"])
            )[1]
        )
        self.assertEqual(show["parents"], [first["task_id"]])

    def test_inconsistent_tails_fail_closed_and_keep_blocked(self) -> None:
        self._enqueue(idempotency_key="key-1", title="First")
        self.store.put_manifest(
            {
                "schema": "autonomous-development.workflow.v1",
                "templateId": "autonomous-development.v1",
                "board": "proj",
                "taskId": "t_orphan",
                "repoRoot": str(self.repo.resolve()),
                "workflowStatus": "blocked",
                "revision": 1,
                "baseline": {"branch": "main", "head": "a" * 40},
                "candidateFingerprint": None,
                "approvedPlan": None,
            }
        )
        with self.assertRaises(WorkflowProtocolError):
            self._enqueue(idempotency_key="key-2", title="Second")
        created = [call for call in self.kanban.calls if "create" in call]
        self.assertEqual(len(created), 2)
        second = self.kanban.cards_by_key["key-2"]
        self.assertEqual(second["status"], "blocked")
        self.assertNotIn(second["id"], self.kanban.unblocked)

    def test_human_format_create_output_is_rejected(self) -> None:
        self.kanban.human_create = True
        with self.assertRaises(WorkflowProtocolError):
            self._enqueue()
        self.assertEqual(self.kanban.unblocked, set())

    def test_idempotent_replay_does_not_create_a_second_card(self) -> None:
        first = self._enqueue()
        again = self._enqueue()
        self.assertEqual(again["task_id"], first["task_id"])
        creates = [call for call in self.kanban.calls if "create" in call]
        self.assertEqual(len(creates), 1)
        self.assertEqual(len(self.kanban.cards_by_id), 1)

    def test_crash_before_unblock_keeps_blocked_then_replay_publishes(self) -> None:
        self.kanban.fail_on = "unblock"
        with self.assertRaises(RuntimeError):
            self._enqueue()
        task_id = self.kanban.cards_by_key["key-1"]["id"]
        self.assertEqual(self.kanban.cards_by_id[task_id]["status"], "blocked")
        self.assertNotIn(task_id, self.kanban.unblocked)
        self.assertEqual(self.store.get_intake("key-1")["status"], "verified")
        self.kanban.fail_on = None
        result = self._enqueue()
        self.assertEqual(result["task_id"], task_id)
        self.assertEqual(result["status"], "published")
        self.assertEqual(len(self.kanban.cards_by_id), 1)
        self.assertIn(task_id, self.kanban.unblocked)

    def test_crash_after_create_replays_without_duplicate(self) -> None:
        original_put = self.store.put_manifest

        def crash_put(manifest):
            self.store.put_intake(
                idempotency_key="key-1",
                board="proj",
                repo_root=str(self.repo.resolve()),
                status="card_created",
                task_id=manifest["taskId"],
            )
            raise RuntimeError("crash after create")

        with patch.object(self.store, "put_manifest", side_effect=crash_put):
            with self.assertRaises(RuntimeError):
                self._enqueue()
        self.store.put_manifest = original_put
        result = self._enqueue()
        self.assertEqual(len(self.kanban.cards_by_id), 1)
        self.assertEqual(result["status"], "published")

    def test_does_not_read_or_write_workflow_template_id(self) -> None:
        self._enqueue()
        joined = " ".join(item for call in self.kanban.calls for item in call)
        self.assertNotIn("workflow_template_id", joined)
        self.assertNotIn("--workflow-template-id", joined)
        source = (
            Path(_service.__file__).read_text(encoding="utf-8")
            + Path(_cli.__file__).read_text(encoding="utf-8")
        )
        self.assertNotIn("workflow_template_id", source)

    def test_real_git_repo_is_inspected_with_argv_and_mocked_kanban_only(self) -> None:
        git_repo = self.root / "git-repo"
        git_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=git_repo, check=True)
        subprocess.run(["git", "config", "user.name", "Dev"], cwd=git_repo, check=True)
        (git_repo / "README").write_text("ok\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=git_repo, check=True, capture_output=True)
        result = self._enqueue(repo=str(git_repo), inspect_repo=None)
        self.assertEqual(result["status"], "published")
        manifest = self.store.get_manifest("proj", result["task_id"])
        self.assertEqual(manifest["repoRoot"], str(git_repo.resolve()))
        self.assertEqual(manifest["baseline"]["branch"], "main")
        self.assertEqual(len(manifest["baseline"]["head"]), 40)

    def test_relative_requirement_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            self._enqueue(requirement="requirement.md")
        self.assertEqual(self.kanban.calls, [])


if __name__ == "__main__":
    unittest.main()
