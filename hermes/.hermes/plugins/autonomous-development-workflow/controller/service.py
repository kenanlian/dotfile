"""Enqueue orchestration: blocked-first intake, Manifest, and serial predecessors."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from .protocol import require_absolute_path
from .store import WorkflowStore, canonical_dumps, sha256_file
from .types import (
    WORKFLOW_SCHEMA,
    WORKFLOW_TEMPLATE_ID,
    PluginConfig,
    WorkflowProtocolError,
)

RunArgv = Callable[[list[str]], tuple[int, str, str]]
InspectRepo = Callable[..., Mapping[str, Any]]

INTAKE_NOTICE = (
    "Autonomous development card. Advance only through the autodev workflow "
    "controller; do not complete this task directly."
)
_TERMINAL_STATUSES = frozenset({"completed"})


def build_kanban_create_argv(
    *,
    board: str,
    title: str,
    body: str,
    assignee: str,
    repo: str,
    idempotency_key: str,
) -> list[str]:
    return [
        "hermes",
        "kanban",
        "--board",
        board,
        "create",
        title,
        "--body",
        body,
        "--assignee",
        assignee,
        "--workspace",
        f"dir:{repo}",
        "--initial-status",
        "blocked",
        "--idempotency-key",
        idempotency_key,
        "--json",
    ]


def build_kanban_link_argv(*, board: str, parent: str, child: str) -> list[str]:
    return ["hermes", "kanban", "--board", board, "link", parent, child]


def build_kanban_show_argv(*, board: str, task_id: str) -> list[str]:
    return ["hermes", "kanban", "--board", board, "show", task_id, "--json"]


def build_kanban_unblock_argv(*, board: str, task_id: str) -> list[str]:
    return ["hermes", "kanban", "--board", board, "unblock", task_id]


def run_argv(argv: list[str], *, timeout: int = 60) -> tuple[int, str, str]:
    if not isinstance(argv, (list, tuple)) or not argv:
        raise WorkflowProtocolError("command must be a non-empty argv list, not a shell string")
    if any(not isinstance(item, str) or not item for item in argv):
        raise WorkflowProtocolError("command argv items must be non-empty strings")
    completed = subprocess.run(
        list(argv),
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def inspect_git_repo(repo: str, *, main_branch: str) -> dict[str, Any]:
    real = str(Path(require_absolute_path(repo, "repo")).resolve())
    if not Path(real).is_dir():
        raise WorkflowProtocolError("repo does not exist")

    def git(*args: str) -> str:
        code, stdout, stderr = run_argv(["git", "-C", real, *args])
        if code != 0:
            raise WorkflowProtocolError(stderr.strip() or stdout.strip() or "repository inspection failed")
        return stdout.strip()

    toplevel = str(Path(git("rev-parse", "--show-toplevel")).resolve())
    if toplevel != real:
        raise WorkflowProtocolError("repo path must be the repository root")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "HEAD")
    porcelain = git("status", "--porcelain=v1")
    clean = porcelain == ""
    if branch != main_branch:
        raise WorkflowProtocolError(f"repository branch {branch!r} is not {main_branch!r}")
    if not clean:
        raise WorkflowProtocolError("repository working tree must be clean before enqueue")
    if not head:
        raise WorkflowProtocolError("repository HEAD is missing")
    return {
        "repo_root": real,
        "git_root": toplevel,
        "branch": branch,
        "head": head,
        "clean": True,
    }


def find_serial_predecessor(store: WorkflowStore, board: str, *, exclude_task_id: str) -> str | None:
    active_ids = {
        item["taskId"]
        for item in store.list_manifests(board)
        if item.get("workflowStatus") not in _TERMINAL_STATUSES and item.get("taskId") != exclude_task_id
    }
    if not active_ids:
        return None
    has_successor: set[str] = set()
    for row in store.list_intake(board):
        predecessor = row.get("predecessor_task_id")
        child = row.get("task_id")
        if predecessor in active_ids and child in active_ids:
            has_successor.add(predecessor)
    tails = active_ids - has_successor
    if len(tails) != 1:
        raise WorkflowProtocolError("inconsistent serial predecessor tails")
    return next(iter(tails))


def enqueue_workflow(
    *,
    board: str,
    repo: str,
    title: str,
    requirement: str,
    profile: str,
    config: PluginConfig,
    store: WorkflowStore,
    run_argv: RunArgv,
    idempotency_key: str | None = None,
    inspect_repo: InspectRepo | None = None,
) -> dict[str, Any]:
    if not board.strip() or not title.strip():
        raise WorkflowProtocolError("board and title must be non-empty")
    requirement_path = Path(require_absolute_path(requirement, "requirement"))
    if not requirement_path.is_file():
        raise WorkflowProtocolError("requirement path does not exist")
    real_repo = str(Path(require_absolute_path(repo, "repo")).resolve())
    inspector = inspect_repo or inspect_git_repo
    snapshot = dict(inspector(real_repo, main_branch=config.main_branch))
    if Path(snapshot["git_root"]).resolve() != Path(real_repo):
        raise WorkflowProtocolError("repo path must be the repository root")
    if snapshot["branch"] != config.main_branch:
        raise WorkflowProtocolError(
            f"repository branch {snapshot['branch']!r} is not {config.main_branch!r}"
        )
    if not snapshot.get("clean"):
        raise WorkflowProtocolError("repository working tree must be clean before enqueue")
    requirement_sha = sha256_file(requirement_path)
    key = idempotency_key or _derive_idempotency_key(board, real_repo, title, requirement_sha)
    intake = store.get_intake(key)
    if intake is not None and intake["status"] == "published" and intake["task_id"]:
        return {
            "task_id": intake["task_id"],
            "status": "published",
            "predecessor_task_id": intake["predecessor_task_id"],
            "idempotency_key": key,
        }

    task_id = intake["task_id"] if intake and intake["task_id"] else None
    if task_id is None:
        store.put_intake(idempotency_key=key, board=board, repo_root=real_repo, status="started")
        code, stdout, stderr = run_argv(
            build_kanban_create_argv(
                board=board,
                title=title,
                body=INTAKE_NOTICE,
                assignee=profile,
                repo=real_repo,
                idempotency_key=key,
            )
        )
        created = _parse_json_object(stdout, "kanban create")
        if code != 0 or "id" not in created:
            raise WorkflowProtocolError(stderr.strip() or "kanban create failed")
        task_id = str(created["id"])
        store.put_intake(
            idempotency_key=key,
            board=board,
            repo_root=real_repo,
            status="card_created",
            task_id=task_id,
        )

    if store.get_manifest(board, task_id) is None:
        artifact_path = _write_requirement_artifact(
            store, board=board, task_id=task_id, requirement_path=requirement_path
        )
        store.put_manifest(
            {
                "schema": WORKFLOW_SCHEMA,
                "templateId": WORKFLOW_TEMPLATE_ID,
                "board": board,
                "taskId": task_id,
                "repoRoot": real_repo,
                "workflowStatus": "queued",
                "revision": 1,
                "stageAttempt": 1,
                "activeJobId": None,
                "plannerSessionId": None,
                "implementerSessionId": None,
                "planReworkCount": 0,
                "implementReworkCount": 0,
                "runFailureCounts": {},
                "baseline": {"branch": snapshot["branch"], "head": snapshot["head"]},
                "candidateFingerprint": None,
                "approvedPlan": None,
                "lastConsumedJobId": None,
                "pendingLifecycle": None,
                "resumeStatus": None,
            }
        )
        store.register_artifact(
            board=board,
            task_id=task_id,
            job_id=f"intake:{task_id}",
            kind="requirement",
            version=1,
            path=str(artifact_path),
            sha256=sha256_file(artifact_path),
        )
        store.put_intake(
            idempotency_key=key,
            board=board,
            repo_root=real_repo,
            status="bound",
            task_id=task_id,
        )

    intake = store.get_intake(key)
    status = intake["status"] if intake else "bound"
    predecessor = intake["predecessor_task_id"] if intake else None
    if status in {"card_created", "bound"}:
        predecessor = find_serial_predecessor(store, board, exclude_task_id=task_id)
        if predecessor:
            code, stdout, stderr = run_argv(
                build_kanban_link_argv(board=board, parent=predecessor, child=task_id)
            )
            if code != 0:
                raise WorkflowProtocolError(stderr.strip() or stdout.strip() or "kanban link failed")
        store.put_intake(
            idempotency_key=key,
            board=board,
            repo_root=real_repo,
            status="linked",
            task_id=task_id,
            predecessor_task_id=predecessor,
        )
        status = "linked"

    if status == "linked":
        code, stdout, stderr = run_argv(build_kanban_show_argv(board=board, task_id=task_id))
        shown = _parse_json_object(stdout, "kanban show")
        if code != 0:
            raise WorkflowProtocolError(stderr.strip() or "kanban show failed")
        _assert_readback(shown, profile=profile, repo=real_repo, predecessor=predecessor)
        store.put_intake(
            idempotency_key=key,
            board=board,
            repo_root=real_repo,
            status="verified",
            task_id=task_id,
            predecessor_task_id=predecessor,
        )
        status = "verified"

    if status == "verified":
        code, stdout, stderr = run_argv(build_kanban_unblock_argv(board=board, task_id=task_id))
        if code != 0:
            raise WorkflowProtocolError(stderr.strip() or stdout.strip() or "kanban unblock failed")
        store.put_intake(
            idempotency_key=key,
            board=board,
            repo_root=real_repo,
            status="published",
            task_id=task_id,
            predecessor_task_id=predecessor,
        )

    return {
        "task_id": task_id,
        "status": "published",
        "predecessor_task_id": predecessor,
        "idempotency_key": key,
    }


def _derive_idempotency_key(board: str, repo: str, title: str, requirement_sha: str) -> str:
    material = f"{board}\n{repo}\n{title}\n{requirement_sha}"
    return "autodev-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _write_requirement_artifact(
    store: WorkflowStore, *, board: str, task_id: str, requirement_path: Path
) -> Path:
    destination = store.state_root / "boards" / board / task_id / "requirements"
    destination.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "autonomous-development.requirement.v1",
        "sourcePath": str(requirement_path.resolve()),
        "sha256": sha256_file(requirement_path),
        "text": requirement_path.read_text(encoding="utf-8"),
    }
    path = destination / "requirement-v1.json"
    path.write_text(canonical_dumps(payload), encoding="utf-8")
    return path


def _parse_json_object(stdout: str, what: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowProtocolError(f"{what} did not return JSON") from exc
    if not isinstance(payload, dict):
        raise WorkflowProtocolError(f"{what} JSON must be an object")
    return payload


def _assert_readback(
    payload: Mapping[str, Any], *, profile: str, repo: str, predecessor: str | None
) -> None:
    task = payload.get("task", payload)
    if not isinstance(task, Mapping):
        raise WorkflowProtocolError("kanban show JSON is missing task")
    if task.get("assignee") != profile:
        raise WorkflowProtocolError("read-back assignee does not match the worker profile")
    if task.get("status") != "blocked":
        raise WorkflowProtocolError("card must remain blocked until intake is complete")
    workspace_path = task.get("workspace_path")
    kind = task.get("workspace_kind")
    if kind != "dir" or not workspace_path or Path(workspace_path).resolve() != Path(repo):
        raise WorkflowProtocolError("read-back workspace is not dir:<repo>")
    parents = payload.get("parents") or []
    if predecessor and predecessor not in parents:
        raise WorkflowProtocolError("read-back parent does not match the serial predecessor")
