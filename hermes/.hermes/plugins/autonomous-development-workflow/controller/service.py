"""Enqueue orchestration: blocked-first intake, Manifest, and serial predecessors."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .acceptance import is_review_lane, submit_typed_acceptance
from .git_guard import capture_candidate_fingerprint, capture_git_baseline, fingerprint_digest
from .harness import (
    HarnessHandle,
    observe_harness_run,
    start_harness_run,
    wait_on_harness,
)
from .jobs import (
    build_job,
    consume_result,
    json_load_if_possible,
    resolve_agent_selection,
    verification_from_intake_artifact,
    verification_from_plan_input,
    write_job_document,
)
from .lifecycle import (
    apply_pending_lifecycle,
    kanban_status_of,
    lifecycle_already_applied,
    make_pending_lifecycle,
    show_task,
)
from .policy import (
    MAX_IMPLEMENT_REWORK,
    MAX_PLAN_REWORK,
    ActiveJobView,
    WorkflowAction,
    next_action,
    snapshot_from_manifest,
)
from .protocol import (
    digest_canonical,
    parse_manifest,
    parse_verification_document,
    require_absolute_path,
    result_digest,
    review_verdict_from_result,
)
from .store import WorkflowStore, canonical_dumps, sha256_file
from .templates import get_template, template_for_flow
from .types import (
    AGENT_SELECTION_FIELDS,
    TRANSPORT_FAILURE_STATUSES,
    VERIFICATION_SCHEMA,
    WORKFLOW_SCHEMA,
    PluginConfig,
    WorkflowConflict,
    WorkflowProtocolError,
    WorkflowStatus,
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


# Optional notify target fields forwarded to `kanban notify-subscribe` (see
# normalize_notify_target). platform/chat_id are mandatory together.
_NOTIFY_OPTIONAL_FLAGS = (
    ("chat_type", "--chat-type"),
    ("thread_id", "--thread-id"),
    ("user_id", "--user-id"),
    ("user_id_alt", "--user-id-alt"),
    ("delivery_mode", "--delivery-mode"),
)


def normalize_notify_target(notify: Mapping[str, Any] | None) -> dict[str, str] | None:
    """Validate operator-supplied notify flags; None when no subscription wanted."""
    if notify is None:
        return None
    platform = str(notify.get("platform") or "").strip()
    chat_id = str(notify.get("chat_id") or "").strip()
    if not platform and not chat_id:
        return None
    if not platform or not chat_id:
        raise WorkflowProtocolError(
            "notify requires both platform and chat_id"
        )
    target = {"platform": platform, "chat_id": chat_id}
    for field, _flag_name in _NOTIFY_OPTIONAL_FLAGS:
        value = notify.get(field)
        if value is not None and str(value).strip():
            target[field] = str(value)
    return target


def build_kanban_notify_subscribe_argv(
    *, board: str, task_id: str, notify: Mapping[str, str]
) -> list[str]:
    argv = [
        "hermes", "kanban", "--board", board,
        "notify-subscribe", task_id,
        "--platform", str(notify["platform"]),
        "--chat-id", str(notify["chat_id"]),
    ]
    for field, flag_name in _NOTIFY_OPTIONAL_FLAGS:
        value = notify.get(field)
        if value:
            argv.extend([flag_name, str(value)])
    return argv


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
    flow: str = "full",
    verification: str | None = None,
    notify: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not board.strip() or not title.strip():
        raise WorkflowProtocolError("board and title must be non-empty")
    notify_target = normalize_notify_target(notify)
    template = template_for_flow(flow)
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
    verification_document = None
    verification_sha = None
    if template.verification_source == "intake":
        if not verification:
            raise WorkflowProtocolError("direct flow requires --verification")
        verification_path = Path(require_absolute_path(verification, "verification"))
        if not verification_path.is_file():
            raise WorkflowProtocolError("verification path does not exist")
        try:
            raw_document = json.loads(verification_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkflowProtocolError("verification is not valid JSON") from exc
        verification_document = parse_verification_document(raw_document, repo_root=real_repo)
        verification_sha = digest_canonical(verification_document)
    elif verification:
        raise WorkflowProtocolError("verification is only valid for direct flow")
    requirement_sha = sha256_file(requirement_path)
    key = idempotency_key or _derive_idempotency_key(
        board,
        real_repo,
        title,
        requirement_sha,
        template_id=template.id,
        verification_sha=verification_sha,
    )
    intake = store.get_intake(key)
    if intake is not None:
        _assert_intake_fingerprint(intake, template_id=template.id, verification_sha=verification_sha)
    if intake is not None and intake["status"] == "published" and intake["task_id"]:
        return _enqueue_result(
            intake["task_id"], intake["predecessor_task_id"], key, template,
            **_subscribe_notify(run_argv, board=board, task_id=intake["task_id"], notify=notify_target),
        )

    task_id = intake["task_id"] if intake and intake["task_id"] else None
    if task_id is None:
        store.put_intake(
            idempotency_key=key,
            board=board,
            repo_root=real_repo,
            status="started",
            template_id=template.id,
            verification_sha256=verification_sha,
        )
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
            template_id=template.id,
            verification_sha256=verification_sha,
        )

    if store.get_manifest(board, task_id) is None:
        artifact_path = _write_requirement_artifact(
            store, board=board, task_id=task_id, requirement_path=requirement_path
        )
        artifacts = [
            {
                "job_id": f"intake:{task_id}",
                "kind": "requirement",
                "version": 1,
                "path": str(artifact_path),
                "sha256": sha256_file(artifact_path),
            }
        ]
        if verification_document is not None:
            verification_path = _write_verification_artifact(
                store,
                board=board,
                task_id=task_id,
                document=verification_document,
            )
            artifacts.append(
                {
                    "job_id": f"intake:{task_id}",
                    "kind": "verification",
                    "version": 1,
                    "path": str(verification_path),
                    "sha256": sha256_file(verification_path),
                }
            )
        store.put_manifest(
            {
                "schema": WORKFLOW_SCHEMA,
                "templateId": template.id,
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
                "lastLifecycle": None,
                "resumeStatus": None,
            }
        )
        for artifact in artifacts:
            store.register_artifact(
                board=board,
                task_id=task_id,
                job_id=artifact["job_id"],
                kind=artifact["kind"],
                version=artifact["version"],
                path=artifact["path"],
                sha256=artifact["sha256"],
            )
        store.put_intake(
            idempotency_key=key,
            board=board,
            repo_root=real_repo,
            status="bound",
            task_id=task_id,
            template_id=template.id,
            verification_sha256=verification_sha,
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
            template_id=template.id,
            verification_sha256=verification_sha,
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
            template_id=template.id,
            verification_sha256=verification_sha,
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
            template_id=template.id,
            verification_sha256=verification_sha,
        )

    return _enqueue_result(
        task_id, predecessor, key, template,
        **_subscribe_notify(run_argv, board=board, task_id=task_id, notify=notify_target),
    )


def _subscribe_notify(
    run_argv: RunArgv, *, board: str, task_id: str, notify: Mapping[str, str] | None
) -> dict[str, Any]:
    """Best-effort notify-subscribe after publication. Bookkeeping must not fail
    an already-published card, and kanban notify-subscribe is idempotent on
    (task, platform, chat, thread), so replay is safe."""
    if notify is None:
        return {"notify_subscribed": False}
    try:
        code, stdout, stderr = run_argv(
            build_kanban_notify_subscribe_argv(board=board, task_id=task_id, notify=notify)
        )
    except Exception as exc:
        return {"notify_subscribed": False, "notify_error": str(exc)}
    if code != 0:
        return {
            "notify_subscribed": False,
            "notify_error": (stderr.strip() or stdout.strip() or "kanban notify-subscribe failed"),
        }
    return {"notify_subscribed": True}


def _derive_idempotency_key(
    board: str,
    repo: str,
    title: str,
    requirement_sha: str,
    *,
    template_id: str,
    verification_sha: str | None,
) -> str:
    material = f"{board}\n{repo}\n{title}\n{requirement_sha}\n{template_id}\n{verification_sha or '-'}"
    return "autodev-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _enqueue_result(
    task_id: str, predecessor: str | None, key: str, template, **extra: Any
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "status": "published",
        "predecessor_task_id": predecessor,
        "idempotency_key": key,
        "templateId": template.id,
        "flow": template.flow,
        **extra,
    }


def _assert_intake_fingerprint(
    intake: Mapping[str, Any], *, template_id: str, verification_sha: str | None
) -> None:
    stored_template = intake.get("template_id") or "autonomous-development.v1"
    stored_verification = intake.get("verification_sha256") or None
    if stored_template != template_id or stored_verification != verification_sha:
        raise WorkflowConflict(
            "intake idempotency key is bound to a different flow or verification document"
        )


def _write_verification_artifact(
    store: WorkflowStore, *, board: str, task_id: str, document: Mapping[str, Any]
) -> Path:
    destination = store.state_root / "boards" / board / task_id / "verification"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "verification-v1.json"
    payload = {
        "schema": VERIFICATION_SCHEMA,
        "checks": list(document["checks"]),
    }
    path.write_text(canonical_dumps(payload), encoding="utf-8")
    return path


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


FORBIDDEN_ADVANCE_KEYS = frozenset(
    {
        "stage",
        "target",
        "target_status",
        "targetStatus",
        "session",
        "sessionId",
        "session_id",
        "artifact",
        "artifactPath",
        "lifecycle",
        "pendingLifecycle",
    }
)

_DEFAULT_AGENTS = {
    "planner": {"model": "unconfigured", "thinking": "high"},
    "plan-reviewer": {"model": "unconfigured", "thinking": "high"},
    "implementer": {"model": "unconfigured", "thinking": "high"},
    "execute-reviewer": {"model": "unconfigured", "thinking": "high"},
}


class WorkflowController:
    """Single-step controller: Store + Policy + Harness + native Kanban lifecycle."""

    def __init__(
        self,
        *,
        store: WorkflowStore,
        config: PluginConfig,
        dispatch_tool: RunArgv | Callable[..., str],
        agents: Mapping[str, Mapping[str, str]] | None = None,
        stage_agents: Mapping[str, Mapping[str, str]] | None = None,
        popen: Callable[..., Any] | None = None,
        identity_fn: Callable[[int], str | None] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.dispatch_tool = dispatch_tool
        self.agents = dict(agents or _DEFAULT_AGENTS)
        # Exact-Stage agent config (adapter/model/thinking). Only consulted
        # when a Stage lineage has no frozen selection yet; in-flight lineages
        # keep their frozen binding regardless of later config changes.
        self.stage_agents = dict(stage_agents or {})
        self.popen = popen
        self.identity_fn = identity_fn
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn

    def status(self, *, board: str, task_id: str, run_id: str | None = None) -> dict[str, Any]:
        self._assert_guard_clear(board, task_id)
        manifest = self._require_manifest(board, task_id)
        shown = show_task(self.dispatch_tool, task_id=task_id, board=board)
        self._validate_bindings(manifest, shown, task_id=task_id, board=board, run_id=run_id)
        snapshot = self._snapshot(manifest, kanban_status=kanban_status_of(shown))
        action = next_action(snapshot)
        return self._summary(manifest, action, in_progress=action.kind in {"observe_job", "create_job"})

    def advance(
        self,
        *,
        board: str,
        task_id: str,
        run_id: str,
        wait_seconds: int = 60,
        extra_args: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_guard_clear(board, task_id)
        if extra_args:
            forbidden = FORBIDDEN_ADVANCE_KEYS.intersection(extra_args)
            if forbidden:
                raise WorkflowProtocolError(
                    f"advance does not accept {sorted(forbidden)}"
                )
        if wait_seconds > 300:
            raise WorkflowProtocolError("wait_seconds must be between 0 and 300")
        shown = show_task(self.dispatch_tool, task_id=task_id, board=board)
        manifest = self._require_manifest(board, task_id)
        self._validate_bindings(manifest, shown, task_id=task_id, board=board, run_id=run_id)
        kanban_status = kanban_status_of(shown)
        if manifest.get("pendingLifecycle"):
            return self._apply_pending(manifest, run_id=run_id)
        if (
            manifest.get("workflowStatus") == WorkflowStatus.REVIEW_REQUESTED.value
            and is_review_lane(shown, run_id)
        ):
            updated = dict(manifest)
            updated["revision"] = int(manifest["revision"]) + 1
            updated["workflowStatus"] = WorkflowStatus.CODE_REVIEWING.value
            self.store.cas_update_manifest(
                board, task_id, expected_revision=int(manifest["revision"]), manifest=updated
            )
            manifest = updated
        manifest = self._maybe_resume_from_blocked(manifest, kanban_status)
        snapshot = self._snapshot(manifest, kanban_status=kanban_status)
        action = next_action(snapshot)
        if action.kind == "apply_lifecycle" and action.target_status is not None:
            return self._write_and_apply_lifecycle(manifest, action.target_status, run_id=run_id)
        if action.kind == "await_acceptance":
            return self._summary(manifest, action, in_progress=False, outcome="acceptance_required")
        if action.kind == "block":
            return self._write_and_apply_lifecycle(
                manifest, WorkflowStatus.BLOCKED, run_id=run_id, reason=action.reason
            )
        if action.kind == "noop":
            return self._summary(manifest, action, in_progress=False)
        if action.kind == "create_job":
            manifest = self._create_or_reuse_job(manifest, action)
            snapshot = self._snapshot(manifest)
            action = next_action(snapshot)
        if action.kind in {"observe_job", "create_job"}:
            handle = self._observe_or_start(manifest, wait_seconds=wait_seconds)
            if handle.observation.kind == "process_gone":
                return self._consume_process_gone(manifest, run_id=run_id)
            snapshot = self._snapshot(self.store.get_manifest(board, task_id) or manifest)
            action = next_action(snapshot)
        if action.kind == "consume_job":
            return self._consume_and_maybe_lifecycle(manifest, run_id=run_id)
        snapshot = self._snapshot(self.store.get_manifest(board, task_id) or manifest)
        action = next_action(snapshot)
        return self._summary(self.store.get_manifest(board, task_id) or manifest, action)

    def submit_acceptance(
        self,
        *,
        board: str,
        task_id: str,
        run_id: str,
        verdict: str,
        summary: str,
        scenarios: Any,
        findings: Any = None,
        question: str | None = None,
    ) -> dict[str, Any]:
        from .acceptance import submit_typed_acceptance

        self._assert_guard_clear(board, task_id)
        shown = show_task(self.dispatch_tool, task_id=task_id, board=board)
        manifest = self._require_manifest(board, task_id)
        self._validate_bindings(manifest, shown, task_id=task_id, board=board, run_id=run_id)
        return submit_typed_acceptance(
            store=self.store,
            config=self.config,
            dispatch_tool=self.dispatch_tool,
            board=board,
            task_id=task_id,
            run_id=str(run_id),
            shown=shown,
            submission={
                "verdict": verdict,
                "summary": summary,
                "scenarios": scenarios or [],
                "findings": findings or [],
                "question": question,
            },
        )

    def _assert_guard_clear(self, board: str, task_id: str) -> None:
        from ..hooks import assert_guard_clear

        assert_guard_clear(board, task_id)

    def _require_manifest(self, board: str, task_id: str) -> dict[str, Any]:
        manifest = self.store.get_manifest(board, task_id)
        if manifest is None:
            raise WorkflowProtocolError("no workflow manifest is bound to this task")
        parsed = parse_manifest(manifest)
        get_template(parsed.template_id)
        return manifest

    def _validate_bindings(
        self,
        manifest: Mapping[str, Any],
        shown: Mapping[str, Any],
        *,
        task_id: str,
        board: str,
        run_id: str | None,
    ) -> None:
        if manifest.get("board") != board or manifest.get("taskId") != task_id:
            raise WorkflowProtocolError("manifest board/task does not match the Worker context")
        task = shown.get("task") if isinstance(shown.get("task"), Mapping) else shown
        if not isinstance(task, Mapping):
            raise WorkflowProtocolError("kanban_show is missing task")
        if task.get("id") not in {None, task_id} and task.get("id") != task_id:
            raise WorkflowProtocolError("kanban_show task id does not match")
        workspace = task.get("workspace_path")
        if workspace and Path(str(workspace)).resolve() != Path(str(manifest["repoRoot"])).resolve():
            raise WorkflowProtocolError("Kanban workspace does not match Manifest repoRoot")
        lease = self.store.get_repo_lease(str(manifest["repoRoot"]))
        if lease and lease.get("released_at") is None:
            if lease.get("board") != board or lease.get("task_id") != task_id:
                raise WorkflowConflict("repo lease is held by a different task")
        if run_id:
            current = task.get("current_run_id")
            if current not in {None, "", int(run_id) if str(run_id).isdigit() else run_id, str(run_id)}:
                if str(current) != str(run_id):
                    raise WorkflowProtocolError("Kanban current run does not match the Worker run")

    def _snapshot(
        self,
        manifest: Mapping[str, Any],
        *,
        kanban_status: str | None = None,
    ) -> PolicySnapshot:
        job_view = None
        job_id = manifest.get("activeJobId")
        result = None
        if job_id:
            row = self.store.get_job(str(job_id))
            if row:
                result_path = Path(row["run_dir"]) / "result.json"
                result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
                status = row["status"]
                if result and result.get("status"):
                    status = str(result["status"])
                consumed = row.get("consumed_at") is not None
                if (
                    consumed
                    and str(job_id) == str(manifest.get("activeJobId") or "")
                    and status not in TRANSPORT_FAILURE_STATUSES
                ):
                    consumed = False
                job_view = ActiveJobView(
                    job_id=str(job_id),
                    stage=row["stage"],
                    status=status,
                    result=result,
                    consumed=consumed,
                    result_sha256=result_digest(result) if result else None,
                    business_attempt=int(row["business_attempt"]),
                    transport_retry=int(row["transport_retry"]),
                )
        checks = None
        verdict = None
        if result and isinstance(result.get("checks"), list):
            checks = tuple(item for item in result["checks"] if isinstance(item, Mapping))
        if result:
            verdict = review_verdict_from_result(result)
        last_hash = None
        last_id = manifest.get("lastConsumedJobId")
        if last_id and job_view and job_view.job_id == last_id:
            last_hash = job_view.result_sha256
        return snapshot_from_manifest(
            manifest,
            active_job=job_view,
            implement_checks=checks,
            review_verdict=verdict,
            last_consumed_result_sha256=last_hash,
            kanban_status=kanban_status,
        )

    def _maybe_resume_from_blocked(
        self, manifest: dict[str, Any], kanban_status: str | None
    ) -> dict[str, Any]:
        if manifest.get("workflowStatus") != WorkflowStatus.BLOCKED.value:
            return manifest
        if not kanban_status or kanban_status == WorkflowStatus.BLOCKED.value:
            return manifest
        resume = manifest.get("resumeStatus")
        if not isinstance(resume, str) or not resume.strip():
            return manifest
        try:
            target = WorkflowStatus(resume)
        except ValueError:
            return manifest
        if target in {WorkflowStatus.BLOCKED, WorkflowStatus.COMPLETED}:
            return manifest
        updated = dict(manifest)
        updated["revision"] = int(manifest["revision"]) + 1
        updated["workflowStatus"] = target.value
        updated["resumeStatus"] = None
        self.store.cas_update_manifest(
            manifest["board"],
            manifest["taskId"],
            expected_revision=int(manifest["revision"]),
            manifest=updated,
        )
        return updated

    def _create_or_reuse_job(self, manifest: dict[str, Any], action: WorkflowAction) -> dict[str, Any]:
        stage = action.stage
        if not stage:
            raise WorkflowProtocolError("create_job is missing a stage")
        template = get_template(str(manifest.get("templateId") or ""))
        if stage not in template.allowed_stages:
            raise WorkflowProtocolError(f"stage {stage!r} is not allowed for template {template.id}")
        board, task_id = manifest["board"], manifest["taskId"]
        inputs = self._inputs_for_stage(manifest, stage)
        verification = ()
        if template.verification_source == "plan" and stage == "implement":
            verification = verification_from_plan_input(
                inputs[0], repo_root=str(manifest["repoRoot"])
            )
        elif template.verification_source == "intake" and stage == template.implement_stage:
            row = self.store.latest_artifact(board, task_id, "verification")
            if row is None:
                raise WorkflowProtocolError("missing chained verification artifact")
            verification = verification_from_intake_artifact(
                {"kind": "verification", "path": row["path"], "sha256": row["sha256"]},
                repo_root=str(manifest["repoRoot"]),
            )
        session_id = None
        if stage == "plan" and manifest.get("plannerSessionId") and (
            action.reason == "plan_rework" or int(manifest.get("planReworkCount") or 0) > 0
        ):
            session_id = manifest.get("plannerSessionId")
        saved_implementer = manifest.get("implementerSessionId")
        if stage == template.implement_stage and saved_implementer:
            if action.reason == "implement_rework" or int(manifest.get("implementReworkCount") or 0) > 0:
                session_id = saved_implementer
            elif action.reason == "transport_retry" and stage == "direct_implement":
                session_id = saved_implementer
        failures = dict(manifest.get("runFailureCounts") or {})
        transport_retry = int(failures.get(stage, 0)) if action.reason == "transport_retry" else 0
        implement_rework_count = int(manifest.get("implementReworkCount") or 0)
        # Attempt numbers must be monotonic per stage. Deriving them from the
        # rework counters breaks when an operator resets a counter to stay
        # under the rework budget (the recomputed attempt collides with an
        # already-persisted job identity). Derive from the durable job rows
        # instead; a transport retry deliberately reuses the failed attempt.
        persisted_max = self.store.max_business_attempt(board, task_id, stage)
        if action.reason == "transport_retry" and persisted_max is not None:
            business_attempt = persisted_max
        else:
            business_attempt = (persisted_max or 0) + 1
        baseline = manifest.get("baseline") or {}
        # Stale-baseline repair (dotfile t_bf68d977): cards queued behind an
        # upstream card pin baseline.head at intake time. Once the upstream
        # card commits, HEAD advances and the pinned expectedHead would fail
        # every Harness preflight. Before the workflow has consumed any Job
        # the baseline is still a private intake snapshot, so refresh it to
        # the repo's current HEAD/branch. Once a Job has been consumed the
        # baseline is the relay contract between stages (candidate changes
        # travel uncommitted in the tree) and must never be refreshed.
        refreshed_baseline = self._refresh_stale_baseline(manifest, baseline)
        if refreshed_baseline is not None:
            baseline = refreshed_baseline
        # A transport retry deliberately continues on the tree the failed Job
        # left behind (a reused implementer session expects its work in place),
        # so the clean-tree requirement must not re-arm for it. expectedHead
        # stays pinned to the baseline: agents must never move HEAD.
        require_clean_at_start = template.require_clean_at_start(
            stage, implement_rework_count=implement_rework_count
        ) and action.reason != "transport_retry"
        workspace = {
            "repoRoot": manifest["repoRoot"],
            "branch": baseline.get("branch") or self.config.main_branch,
            "expectedHead": baseline.get("head") or "0" * 40,
            "requireCleanAtStart": require_clean_at_start,
        }
        job = build_job(
            board=board,
            task_id=task_id,
            stage=stage,
            business_attempt=business_attempt,
            transport_retry=transport_retry,
            workspace=workspace,
            agents=self.agents,
            stage_agents=self.stage_agents,
            agent_selection=self._frozen_stage_agent(manifest, stage),
            inputs=inputs,
            session_id=session_id,
            verification=verification,
            template_id=template.id,
        )
        run_dir = self.store.state_root / "boards" / board / task_id / "jobs" / job["jobId"]
        written = write_job_document(job, run_dir)
        record = {
            "job_id": job["jobId"],
            "board": board,
            "task_id": task_id,
            "stage": stage,
            "business_attempt": business_attempt,
            "transport_retry": transport_retry,
            "idempotency_key": job["idempotencyKey"],
            "job_path": written["job_path"],
            "run_dir": written["run_dir"],
            "job_sha256": written["job_sha256"],
            "harness_pid": None,
            "process_identity": None,
            "status": "pending",
            "result_path": None,
            "started_at": None,
            "finished_at": None,
            "consumed_at": None,
        }
        self.store.put_job(record)
        self.store.acquire_repo_lease(
            str(manifest["repoRoot"]),
            board=board,
            task_id=task_id,
            fencing_token=job["idempotencyKey"],
        )
        updated = dict(manifest)
        updated["activeJobId"] = job["jobId"]
        if refreshed_baseline is not None:
            updated["baseline"] = refreshed_baseline
        # Freeze this Stage lineage's {adapter, model, thinking} on first Job
        # creation: rework, transport retry, and exact-session resume must
        # reuse this binding, and it must survive restarts and config edits.
        stage_bindings = dict(manifest.get("stageAgents") or {})
        stage_bindings[stage] = {field: job["agent"][field] for field in AGENT_SELECTION_FIELDS}
        updated["stageAgents"] = stage_bindings
        if stage == "execute_review":
            digest = fingerprint_digest(
                capture_candidate_fingerprint(
                    str(manifest["repoRoot"]), declared_repo=str(manifest["repoRoot"])
                )
            )
            existing = updated.get("candidateFingerprint")
            if existing and existing != digest:
                raise WorkflowProtocolError("candidate fingerprint drift")
            updated["candidateFingerprint"] = digest
        if action.target_status is not None:
            updated["workflowStatus"] = action.target_status.value
        updated["revision"] = int(manifest["revision"]) + 1
        self.store.cas_update_manifest(
            board, task_id, expected_revision=int(manifest["revision"]), manifest=updated
        )
        return updated

    def _refresh_stale_baseline(
        self, manifest: Mapping[str, Any], baseline: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Refresh an unconsumed workflow's stale intake baseline, else None.

        Allowed only while no Job of this workflow has ever been consumed.
        Refuses on branch drift or repo inspection failure: those are
        anomalies the pinned baseline must surface (as a precondition
        failure), not silently absorb.
        """
        board, task_id = manifest["board"], manifest["taskId"]
        for row in self.store.list_jobs(board, task_id):
            if row.get("consumed_at") is not None:
                return None
        expected_branch = str(baseline.get("branch") or self.config.main_branch)
        try:
            current = capture_git_baseline(
                str(manifest["repoRoot"]),
                expected_branch=expected_branch,
                expected_head=None,
                declared_repo=str(manifest["repoRoot"]),
                require_clean=False,
            )
        except (WorkflowProtocolError, OSError):
            # Refresh is best-effort: inspection failures keep the pinned
            # baseline so the mismatch surfaces as a precondition failure.
            return None
        if current.head == str(baseline.get("head") or ""):
            return None
        return {"branch": current.branch, "head": current.head}

    def _frozen_stage_agent(self, manifest: Mapping[str, Any], stage: str) -> dict[str, str] | None:
        """Frozen {adapter, model, thinking} for one Stage lineage, if any.

        The persisted Manifest binding is authoritative. When it is absent
        (lineage started before the binding existed, or a crash between
        ``put_job`` and the Manifest CAS), recover the selection from the
        latest persisted Job document of the same Stage instead of
        re-deriving it from the current config.
        """
        binding = manifest.get("stageAgents")
        if isinstance(binding, Mapping):
            entry = binding.get(stage)
            if isinstance(entry, Mapping):
                return resolve_agent_selection(stage=stage, agents=None, agent_selection=entry)
        rows = [
            row
            for row in self.store.list_jobs(manifest["board"], manifest["taskId"])
            if row["stage"] == stage
        ]
        if not rows:
            return None
        latest = rows[-1]
        document = json_load_if_possible(Path(latest["job_path"]))
        if document is None:
            raise WorkflowProtocolError(
                f"cannot recover the frozen agent selection: Job document {latest['job_path']} is unreadable"
            )
        agent = document.get("agent")
        if not isinstance(agent, Mapping):
            raise WorkflowProtocolError(
                f"cannot recover the frozen agent selection: Job document {latest['job_path']} has no agent"
            )
        return resolve_agent_selection(stage=stage, agents=None, agent_selection=agent)

    def _inputs_for_stage(self, manifest: Mapping[str, Any], stage: str) -> tuple[dict[str, str], ...]:
        from .types import STAGE_INPUT_KINDS

        board, task_id = manifest["board"], manifest["taskId"]
        if stage not in STAGE_INPUT_KINDS:
            raise WorkflowProtocolError(f"unknown job stage {stage!r}")
        required = STAGE_INPUT_KINDS[stage]
        inputs = []
        for kind in required:
            row = self.store.latest_artifact(board, task_id, kind)
            if row is None:
                raise WorkflowProtocolError(f"missing chained {kind} artifact")
            inputs.append({"kind": kind, "path": row["path"], "sha256": row["sha256"]})
        return tuple(inputs)

    def _observe_or_start(self, manifest: Mapping[str, Any], *, wait_seconds: int) -> HarnessHandle:
        job_id = manifest.get("activeJobId")
        if not job_id:
            raise WorkflowProtocolError("no active Job to observe")
        row = self.store.get_job(str(job_id))
        if row is None:
            raise WorkflowProtocolError("active Job is missing from the ledger")
        handle = start_harness_run(
            harness_command=self.config.harness_command,
            job_path=row["job_path"],
            out_dir=row["run_dir"],
            job_id=row["job_id"],
            job_sha256=row["job_sha256"],
            recorded_pid=row.get("harness_pid"),
            recorded_identity=row.get("process_identity"),
            env=os.environ.copy(),
            popen=self.popen,
            identity_fn=self.identity_fn,
        )
        if handle.pid and handle.observation.kind == "live_process":
            self.store.update_job(
                row["job_id"],
                harness_pid=handle.pid,
                process_identity=handle.process_identity,
                status="running",
                started_at=handle.started_at,
            )
        observed = handle.observation
        if observed.kind == "live_process":
            observed = wait_on_harness(
                run_dir=row["run_dir"],
                job_id=row["job_id"],
                job_sha256=row["job_sha256"],
                wait_seconds=wait_seconds,
                poll_interval_seconds=self.config.poll_interval_seconds,
                recorded_pid=handle.pid or row.get("harness_pid"),
                recorded_identity=handle.process_identity or row.get("process_identity"),
                heartbeat=lambda current=None: self.dispatch_tool(
                    "kanban_heartbeat",
                    {"task_id": manifest["taskId"], "note": _heartbeat_note(current)},
                ),
                sleep_fn=self.sleep_fn,
                monotonic_fn=self.monotonic_fn,
                identity_fn=self.identity_fn,
            )
        proc = handle.proc
        if proc is not None and hasattr(proc, "wait"):
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        return HarnessHandle(
            observation=observed,
            pid=handle.pid,
            process_identity=handle.process_identity,
            started_at=handle.started_at,
            proc=handle.proc,
        )

    def _consume_process_gone(self, manifest: dict[str, Any], *, run_id: str) -> dict[str, Any]:
        job_id = manifest.get("activeJobId")
        if not job_id:
            raise WorkflowProtocolError("no active Job to mark gone")
        row = self.store.get_job(str(job_id))
        if row is None:
            raise WorkflowProtocolError("active Job is missing from the ledger")
        board, task_id = manifest["board"], manifest["taskId"]
        failures = dict(manifest.get("runFailureCounts") or {})
        failures[row["stage"]] = int(failures.get(row["stage"], 0)) + 1
        updated = dict(manifest)
        updated["revision"] = int(manifest["revision"]) + 1
        updated["lastConsumedJobId"] = job_id
        updated["runFailureCounts"] = failures
        self.store.checkpoint(
            board=board,
            task_id=task_id,
            expected_revision=int(manifest["revision"]),
            manifest=updated,
            job_patch={
                "job_id": job_id,
                "status": "unavailable",
                "consumed_at": int(time.time()),
                "finished_at": int(time.time()),
            },
            artifacts=[],
        )
        snapshot = self._snapshot(self.store.get_manifest(board, task_id) or updated)
        action = next_action(snapshot)
        if action.kind == "block":
            return self._write_and_apply_lifecycle(
                updated, WorkflowStatus.BLOCKED, run_id=run_id, reason=action.reason
            )
        return self._summary(updated, action)

    def _consume_and_maybe_lifecycle(
        self, manifest: dict[str, Any], *, run_id: str, apply_lifecycle: bool = True
    ) -> dict[str, Any]:
        job_id = manifest["activeJobId"]
        row = self.store.get_job(str(job_id))
        result_path = Path(row["run_dir"]) / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        job_doc = json.loads(Path(row["job_path"]).read_text(encoding="utf-8"))
        template = get_template(str(manifest.get("templateId") or ""))
        if str(job_doc.get("stage") or "") not in template.allowed_stages:
            raise WorkflowProtocolError(
                f"job stage {job_doc.get('stage')!r} is not allowed for template {template.id}"
            )
        previous = None
        if row.get("consumed_at") is not None:
            result_status = str(result.get("status") or "")
            if result_status in TRANSPORT_FAILURE_STATUSES or str(manifest.get("activeJobId")) != str(job_id):
                previous = result_digest(result)
        outcome = consume_result(
            job_doc,
            result,
            previously_consumed_sha256=previous,
            expected_job_sha256=row["job_sha256"],
        )
        board, task_id = manifest["board"], manifest["taskId"]
        prior_status = str(manifest.get("workflowStatus") or "")
        updated = dict(manifest)
        updated["revision"] = int(manifest["revision"]) + 1
        updated["lastConsumedJobId"] = job_id
        artifacts: list[dict[str, Any]] = []
        if outcome.kind == "consumed":
            updated["workflowStatus"] = outcome.next_status.value if outcome.next_status else manifest["workflowStatus"]
            if row["stage"] == "plan" and outcome.session_id:
                updated["plannerSessionId"] = outcome.session_id
            if row["stage"] in {"implement", "direct_implement"} and outcome.session_id:
                updated["implementerSessionId"] = outcome.session_id
            if outcome.review_verdict == "request_changes" and row["stage"] == "plan_review":
                updated["planReworkCount"] = int(manifest.get("planReworkCount") or 0) + 1
                if int(updated["planReworkCount"]) > MAX_PLAN_REWORK:
                    updated["workflowStatus"] = WorkflowStatus.BLOCKED.value
                    updated["pendingLifecycle"] = make_pending_lifecycle(
                        target_status=WorkflowStatus.BLOCKED.value,
                        run_id=run_id,
                        workflow_revision=updated["revision"],
                        args={"reason": "plan_rework_limit"},
                    )
            if outcome.review_verdict == "request_changes" and row["stage"] == "execute_review":
                updated["implementReworkCount"] = int(manifest.get("implementReworkCount") or 0) + 1
                if int(updated["implementReworkCount"]) > MAX_IMPLEMENT_REWORK:
                    updated["workflowStatus"] = WorkflowStatus.BLOCKED.value
                    updated["pendingLifecycle"] = make_pending_lifecycle(
                        target_status=WorkflowStatus.BLOCKED.value,
                        run_id=run_id,
                        workflow_revision=updated["revision"],
                        args={"reason": "implement_rework_limit"},
                    )
                else:
                    updated["pendingLifecycle"] = make_pending_lifecycle(
                        target_status=WorkflowStatus.IMPLEMENT_REWORK.value,
                        run_id=run_id,
                        workflow_revision=updated["revision"],
                    )
            for artifact in outcome.artifacts:
                artifacts.append(
                    {
                        "job_id": job_id,
                        "kind": artifact.kind,
                        "version": self.store.next_artifact_version(board, task_id, artifact.kind),
                        "path": artifact.path,
                        "sha256": artifact.sha256,
                    }
                )
            updated["activeJobId"] = None
            if (
                outcome.next_status is WorkflowStatus.BLOCKED
                and row["stage"] == "direct_implement"
                and not updated.get("pendingLifecycle")
            ):
                updated["pendingLifecycle"] = make_pending_lifecycle(
                    target_status=WorkflowStatus.BLOCKED.value,
                    run_id=run_id,
                    workflow_revision=updated["revision"],
                    args={"reason": "structured outcome blocked"},
                )
        elif outcome.kind == "transport_failure":
            failures = dict(manifest.get("runFailureCounts") or {})
            failures[row["stage"]] = int(failures.get(row["stage"], 0)) + 1
            updated["runFailureCounts"] = failures
            if (
                row["stage"] == "direct_implement"
                and isinstance(outcome.session_id, str)
                and outcome.session_id.strip()
            ):
                updated["implementerSessionId"] = outcome.session_id.strip()
        elif outcome.kind in {"protocol_failure", "precondition_failure"}:
            updated["workflowStatus"] = WorkflowStatus.BLOCKED.value
            updated["pendingLifecycle"] = make_pending_lifecycle(
                target_status=WorkflowStatus.BLOCKED.value,
                run_id=run_id,
                workflow_revision=updated["revision"],
                args={"reason": outcome.reason or "protocol failure"},
            )
        if updated.get("workflowStatus") == WorkflowStatus.BLOCKED.value:
            if prior_status not in {WorkflowStatus.BLOCKED.value, WorkflowStatus.COMPLETED.value, ""}:
                updated["resumeStatus"] = prior_status
        self.store.checkpoint(
            board=board,
            task_id=task_id,
            expected_revision=int(manifest["revision"]),
            manifest=updated,
            job_patch={
                "job_id": job_id,
                "status": result.get("status") or "consumed",
                "result_path": str(result_path),
                "consumed_at": int(time.time()),
                "finished_at": int(time.time()),
            },
            artifacts=artifacts,
        )
        if updated.get("pendingLifecycle"):
            return self._apply_pending(updated, run_id=run_id)
        snapshot = self._snapshot(updated)
        if row["stage"] in {"implement", "direct_implement"} and isinstance(result.get("checks"), list):
            from dataclasses import replace

            snapshot = replace(
                snapshot,
                implement_checks=tuple(
                    item for item in result["checks"] if isinstance(item, Mapping)
                ),
            )
        if row["stage"] == "execute_review" and updated.get("candidateFingerprint"):
            actual = fingerprint_digest(
                capture_candidate_fingerprint(
                    str(manifest["repoRoot"]), declared_repo=str(manifest["repoRoot"])
                )
            )
            if actual != updated["candidateFingerprint"]:
                raise WorkflowProtocolError("candidate fingerprint drift")
        action = next_action(snapshot)
        if apply_lifecycle and action.kind == "apply_lifecycle" and action.target_status is not None:
            return self._write_and_apply_lifecycle(updated, action.target_status, run_id=run_id)
        if apply_lifecycle and action.kind == "block":
            return self._write_and_apply_lifecycle(
                updated, WorkflowStatus.BLOCKED, run_id=run_id, reason=action.reason
            )
        if action.kind == "create_job":
            created = self._create_or_reuse_job(updated, action)
            created_action = next_action(self._snapshot(created))
            return self._summary(created, created_action, in_progress=True)
        return self._summary(updated, action)

    def _write_and_apply_lifecycle(
        self,
        manifest: dict[str, Any],
        target: WorkflowStatus,
        *,
        run_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        args = {"reason": reason} if reason and target is WorkflowStatus.BLOCKED else None
        if target is WorkflowStatus.COMPLETED:
            template = get_template(str(manifest.get("templateId") or ""))
            args = {"summary": template.completion_summary}
        pending = make_pending_lifecycle(
            target_status=target.value,
            run_id=run_id,
            workflow_revision=int(manifest["revision"]) + 1,
            args=args,
        )
        previous = str(manifest.get("workflowStatus") or "")
        updated = dict(manifest)
        updated["revision"] = int(manifest["revision"]) + 1
        updated["workflowStatus"] = target.value
        updated["pendingLifecycle"] = pending
        if (
            previous == WorkflowStatus.VERIFYING.value
            and target is WorkflowStatus.IMPLEMENT_REWORK
        ):
            updated["implementReworkCount"] = int(manifest.get("implementReworkCount") or 0) + 1
        if target is WorkflowStatus.BLOCKED and previous not in {
            WorkflowStatus.BLOCKED.value,
            WorkflowStatus.COMPLETED.value,
            "",
        }:
            updated["resumeStatus"] = previous
        self.store.cas_update_manifest(
            manifest["board"],
            manifest["taskId"],
            expected_revision=int(manifest["revision"]),
            manifest=updated,
        )
        return self._apply_pending(updated, run_id=run_id)

    def _apply_pending(self, manifest: dict[str, Any], *, run_id: str) -> dict[str, Any]:
        pending = manifest.get("pendingLifecycle")
        if not pending:
            return self._summary(manifest, WorkflowAction(kind="noop"))
        result = apply_pending_lifecycle(
            pending,
            current_run_id=run_id,
            task_id=manifest["taskId"],
            board=manifest["board"],
            dispatch=self.dispatch_tool,
        )
        if result["applied"]:
            updated = dict(manifest)
            updated["revision"] = int(manifest["revision"]) + 1
            # Receipt for the saga close-out: once pendingLifecycle clears,
            # later observers can still tell "applied" from "stuck".
            updated["lastLifecycle"] = {
                "tool": pending["tool"],
                "targetStatus": pending["targetStatus"],
                "kanbanStatus": pending["kanbanStatus"],
                "dispatched": result["dispatched"],
                "appliedAt": int(time.time()),
                "workflowRevision": pending["workflowRevision"],
            }
            if result.get("skipped"):
                updated["lastLifecycle"]["skipped"] = str(result["skipped"])
            updated["pendingLifecycle"] = None
            self.store.cas_update_manifest(
                manifest["board"],
                manifest["taskId"],
                expected_revision=int(manifest["revision"]),
                manifest=updated,
            )
            if updated["workflowStatus"] == WorkflowStatus.COMPLETED.value:
                lease = self.store.get_repo_lease(str(manifest["repoRoot"]))
                if lease and lease.get("released_at") is None:
                    self.store.release_repo_lease(
                        str(manifest["repoRoot"]),
                        board=manifest["board"],
                        task_id=manifest["taskId"],
                        reason="completed",
                    )
            action = next_action(self._snapshot(updated))
            outcome = "blocked" if updated["workflowStatus"] == WorkflowStatus.BLOCKED.value else None
            return self._summary(updated, action, outcome=outcome)
        return self._summary(manifest, WorkflowAction(kind="apply_lifecycle"))

    def _summary(
        self,
        manifest: Mapping[str, Any],
        action: WorkflowAction,
        *,
        in_progress: bool | None = None,
        outcome: str | None = None,
    ) -> dict[str, Any]:
        status = manifest.get("workflowStatus")
        if in_progress is None:
            in_progress = action.kind in {"observe_job", "create_job"}
        if outcome is None:
            if action.kind == "await_acceptance":
                outcome = "acceptance_required"
            elif status == WorkflowStatus.BLOCKED.value:
                outcome = "blocked"
            elif in_progress:
                outcome = "in_progress"
            else:
                outcome = "ok"
        template = get_template(str(manifest.get("templateId") or ""))
        return {
            "ok": True,
            "workflowStatus": status,
            "revision": manifest.get("revision"),
            "stageAttempt": manifest.get("stageAttempt"),
            "activeJobId": manifest.get("activeJobId"),
            "nextAction": action.kind,
            "inProgress": in_progress,
            "pendingLifecycle": manifest.get("pendingLifecycle"),
            "lastLifecycle": manifest.get("lastLifecycle"),
            "outcome": outcome,
            "templateId": template.id,
            "flow": template.flow,
        }

    def reconcile(self, *, board: str, task_id: str, run_id: str | None = None) -> dict[str, Any]:
        shown = show_task(self.dispatch_tool, task_id=task_id, board=board)
        manifest = self._require_manifest(board, task_id)
        self._validate_bindings(manifest, shown, task_id=task_id, board=board, run_id=run_id)
        pending = manifest.get("pendingLifecycle")
        if pending:
            if lifecycle_already_applied(shown, pending):
                updated = dict(manifest)
                updated["revision"] = int(manifest["revision"]) + 1
                updated["pendingLifecycle"] = None
                self.store.cas_update_manifest(
                    board, task_id, expected_revision=int(manifest["revision"]), manifest=updated
                )
                return {**self._summary(updated, WorkflowAction(kind="noop")), "reconciled": True}
            if run_id and str(pending.get("runId")) == str(run_id):
                result = self._apply_pending(manifest, run_id=str(run_id))
                return {**result, "reconciled": True}
            return {
                **self._summary(manifest, WorkflowAction(kind="apply_lifecycle")),
                "reconciled": False,
                "reason": "pendingLifecycle requires the bound Worker run",
            }
        kanban_status = kanban_status_of(shown)
        manifest = self._maybe_resume_from_blocked(manifest, kanban_status)
        snapshot = self._snapshot(manifest, kanban_status=kanban_status)
        action = next_action(snapshot)
        if action.kind == "consume_job":
            if not run_id:
                result = self._consume_and_maybe_lifecycle(
                    manifest, run_id="cli-reconcile", apply_lifecycle=False
                )
                return {**result, "reconciled": True}
            result = self._consume_and_maybe_lifecycle(manifest, run_id=str(run_id))
            return {**result, "reconciled": True}
        return {**self._summary(manifest, action), "reconciled": False}

    def reset_failure_counts(self, *, board: str, task_id: str) -> dict[str, Any]:
        """Operator repair for a transport-failure-limited card.

        Lesson from dotfile t_bf68d977's second blockage: clearing
        ``runFailureCounts`` alone makes the controller re-derive a
        attempt-1/retry-0 Job identity that collides with already-consumed
        dead Jobs ("job document identity conflict" in both the run dir and
        the Job ledger). The repair is exactly two steps in one Manifest
        revision: clear ``runFailureCounts`` and set ``activeJobId`` to null,
        so the next Job derives a fresh business attempt. Job rows and audit
        trails are preserved.
        """
        self._assert_guard_clear(board, task_id)
        shown = show_task(self.dispatch_tool, task_id=task_id, board=board)
        manifest = self._require_manifest(board, task_id)
        self._validate_bindings(manifest, shown, task_id=task_id, board=board, run_id=None)
        job_id = manifest.get("activeJobId")
        bypassed: str | None = None
        if job_id:
            row = self.store.get_job(str(job_id))
            if row:
                observed = observe_harness_run(
                    run_dir=row["run_dir"],
                    job_id=row["job_id"],
                    job_sha256=row["job_sha256"],
                    recorded_pid=row.get("harness_pid"),
                    recorded_identity=row.get("process_identity"),
                    identity_fn=self.identity_fn,
                )
                if observed.kind == "live_process":
                    raise WorkflowProtocolError(
                        "cannot reset failure counts while a Harness process is live"
                    )
                if row.get("consumed_at") is None:
                    # The dead Job is being bypassed by operator decision;
                    # record the consumption so the ledger reflects reality.
                    result_path = Path(row["run_dir"]) / "result.json"
                    status = str(row["status"])
                    if result_path.is_file():
                        try:
                            result = json.loads(result_path.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            result = None
                        if isinstance(result, dict) and result.get("status"):
                            status = str(result["status"])
                    self.store.update_job(
                        row["job_id"],
                        status=status,
                        result_path=str(result_path) if result_path.is_file() else row.get("result_path"),
                        consumed_at=int(time.time()),
                        finished_at=int(time.time()),
                    )
                    bypassed = str(job_id)
        updated = dict(manifest)
        updated["revision"] = int(manifest["revision"]) + 1
        updated["runFailureCounts"] = {}
        updated["activeJobId"] = None
        self.store.cas_update_manifest(
            board, task_id, expected_revision=int(manifest["revision"]), manifest=updated
        )
        return {
            **self._summary(updated, WorkflowAction(kind="noop")),
            "resetFailureCounts": True,
            "activeJobIdCleared": True,
            "bypassedJobId": bypassed,
        }

    def abandon(self, *, board: str, task_id: str, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip():
            raise WorkflowProtocolError("abandon requires an explicit operator reason")
        manifest = self._require_manifest(board, task_id)
        job_id = manifest.get("activeJobId")
        if job_id:
            row = self.store.get_job(str(job_id))
            if row:
                observed = observe_harness_run(
                    run_dir=row["run_dir"],
                    job_id=row["job_id"],
                    job_sha256=row["job_sha256"],
                    recorded_pid=row.get("harness_pid"),
                    recorded_identity=row.get("process_identity"),
                    identity_fn=self.identity_fn,
                )
                if observed.kind == "live_process":
                    raise WorkflowProtocolError("cannot abandon while a Harness process is live")
        lease = self.store.get_repo_lease(str(manifest["repoRoot"]))
        released = False
        if lease and lease.get("released_at") is None:
            self.store.release_repo_lease(
                str(manifest["repoRoot"]),
                board=board,
                task_id=task_id,
                reason="abandon",
            )
            released = True
        updated = dict(manifest)
        updated["revision"] = int(manifest["revision"]) + 1
        updated["workflowStatus"] = WorkflowStatus.BLOCKED.value
        updated["resumeStatus"] = None
        updated["abandonReason"] = reason.strip()
        updated["pendingLifecycle"] = None
        updated["activeJobId"] = None
        self.store.cas_update_manifest(
            board, task_id, expected_revision=int(manifest["revision"]), manifest=updated
        )
        return {
            **self._summary(updated, WorkflowAction(kind="noop"), outcome="blocked"),
            "abandoned": True,
            "leaseReleased": released,
            "reason": reason.strip(),
        }


def doctor_report(
    store: WorkflowStore,
    *,
    board: str,
    task_id: str | None = None,
    shown: Mapping[str, Any] | None = None,
    config: PluginConfig | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    targets = [task_id] if task_id else [item["taskId"] for item in store.list_manifests(board)]
    if task_id and store.get_manifest(board, task_id) is None:
        findings.append(
            {
                "code": "missing_manifest",
                "severity": "error",
                "message": f"Kanban task {task_id} has no workflow Manifest",
            }
        )
    for current_id in targets:
        if not current_id:
            continue
        manifest = store.get_manifest(board, current_id)
        if manifest is None:
            continue
        findings.extend(_doctor_manifest(store, manifest, shown=shown, config=config))
    return {"ok": not any(item["severity"] == "error" for item in findings), "findings": findings}


def _doctor_manifest(
    store: WorkflowStore,
    manifest: Mapping[str, Any],
    *,
    shown: Mapping[str, Any] | None,
    config: PluginConfig | None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    board, task_id = manifest["board"], manifest["taskId"]
    if shown:
        task = shown.get("task") if isinstance(shown.get("task"), Mapping) else shown
        kanban_status = kanban_status_of(shown)
        workspace = task.get("workspace_path") if isinstance(task, Mapping) else None
        if workspace and Path(str(workspace)).resolve() != Path(str(manifest["repoRoot"])).resolve():
            findings.append(
                {
                    "code": "repo_mismatch",
                    "severity": "error",
                    "message": "Kanban workspace does not match Manifest repoRoot",
                }
            )
        expected_lane = get_template(str(manifest.get("templateId") or "")).expected_kanban_lanes.get(
            str(manifest.get("workflowStatus")), set()
        )
        if kanban_status and expected_lane and kanban_status not in expected_lane:
            findings.append(
                {
                    "code": "lane_mismatch",
                    "severity": "warning",
                    "message": f"workflow {manifest.get('workflowStatus')} vs Kanban {kanban_status}",
                }
            )
        pending = manifest.get("pendingLifecycle")
        if isinstance(pending, Mapping) and not lifecycle_already_applied(shown, pending):
            findings.append(
                {
                    "code": "pending_lifecycle",
                    "severity": "warning",
                    "message": f"{pending.get('tool')} is not yet applied",
                }
            )
    job_id = manifest.get("activeJobId")
    if job_id:
        row = store.get_job(str(job_id))
        if row is None:
            findings.append(
                {"code": "missing_job", "severity": "error", "message": f"active Job {job_id} is missing"}
            )
        else:
            if not Path(row["job_path"]).is_file():
                findings.append(
                    {"code": "missing_job_file", "severity": "error", "message": "active Job file is missing"}
                )
            observed = observe_harness_run(
                run_dir=row["run_dir"],
                job_id=row["job_id"],
                job_sha256=row["job_sha256"],
                recorded_pid=row.get("harness_pid"),
                recorded_identity=row.get("process_identity"),
            )
            if observed.kind == "orphan_lock":
                findings.append(
                    {
                        "code": "orphan_lock",
                        "severity": "error",
                        "message": "orphan run.lock bound to the active Job",
                    }
                )
            if observed.kind == "process_gone":
                findings.append(
                    {
                        "code": "process_gone",
                        "severity": "warning",
                        "message": "recorded Harness process is gone without a Result",
                    }
                )
            if observed.kind == "not_started" and row.get("consumed_at") is None:
                findings.append(
                    {
                        "code": "job_not_started",
                        "severity": "warning",
                        "message": "active Job has no Result and no live process",
                    }
                )
    for kind in (
        "requirement",
        "verification",
        "plan",
        "implementation",
        "direct-implementation",
        "plan-review",
        "execute-review",
        "product-acceptance",
    ):
        artifact = store.latest_artifact(board, task_id, kind)
        if artifact is None:
            continue
        path = Path(artifact["path"])
        if not path.is_file():
            findings.append(
                {"code": "artifact_missing", "severity": "error", "message": f"{kind} artifact is missing"}
            )
        elif sha256_file(path) != artifact["sha256"]:
            findings.append(
                {"code": "artifact_hash", "severity": "error", "message": f"{kind} artifact hash drifted"}
            )
    lease = store.get_repo_lease(str(manifest["repoRoot"]))
    if lease and lease.get("released_at") is None:
        if lease.get("task_id") != task_id or lease.get("board") != board:
            findings.append(
                {
                    "code": "lease_foreign",
                    "severity": "error",
                    "message": "repo lease is held by a different task",
                }
            )
        if manifest.get("workflowStatus") == WorkflowStatus.COMPLETED.value:
            findings.append(
                {
                    "code": "lease_terminal",
                    "severity": "warning",
                    "message": "repo lease still held after completion",
                }
            )
    if config is not None and not config.harness_command:
        findings.append(
            {"code": "harness_config", "severity": "error", "message": "harness_command is missing"}
        )
    return findings


def snapshot_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return dict(manifest)


def _heartbeat_note(observed: Any) -> str:
    kind = getattr(observed, "kind", None)
    if kind == "live_process":
        return "autodev harness still running"
    if kind:
        return f"autodev harness {kind}"
    return "autodev harness waiting"
