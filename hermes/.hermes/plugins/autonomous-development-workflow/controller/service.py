"""Enqueue orchestration: blocked-first intake, Manifest, and serial predecessors."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .harness import HarnessHandle, start_harness_run, wait_on_harness
from .jobs import build_job, consume_result, write_job_document
from .lifecycle import apply_pending_lifecycle, make_pending_lifecycle, show_task
from .policy import ActiveJobView, WorkflowAction, next_action, snapshot_from_manifest
from .protocol import parse_manifest, require_absolute_path, result_digest, review_verdict_from_result
from .store import WorkflowStore, canonical_dumps, sha256_file
from .types import (
    WORKFLOW_SCHEMA,
    WORKFLOW_TEMPLATE_ID,
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
        popen: Callable[..., Any] | None = None,
        identity_fn: Callable[[int], str | None] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.dispatch_tool = dispatch_tool
        self.agents = dict(agents or _DEFAULT_AGENTS)
        self.popen = popen
        self.identity_fn = identity_fn
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn

    def status(self, *, board: str, task_id: str, run_id: str | None = None) -> dict[str, Any]:
        manifest = self._require_manifest(board, task_id)
        shown = show_task(self.dispatch_tool, task_id=task_id, board=board)
        self._validate_bindings(manifest, shown, task_id=task_id, board=board, run_id=run_id)
        snapshot = self._snapshot(manifest)
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
        if manifest.get("pendingLifecycle"):
            return self._apply_pending(manifest, run_id=run_id)
        snapshot = self._snapshot(manifest)
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
            self._observe_or_start(manifest, wait_seconds=wait_seconds)
            snapshot = self._snapshot(self.store.get_manifest(board, task_id) or manifest)
            action = next_action(snapshot)
        if action.kind == "consume_job":
            return self._consume_and_maybe_lifecycle(manifest, run_id=run_id)
        snapshot = self._snapshot(self.store.get_manifest(board, task_id) or manifest)
        action = next_action(snapshot)
        return self._summary(self.store.get_manifest(board, task_id) or manifest, action)

    def _require_manifest(self, board: str, task_id: str) -> dict[str, Any]:
        manifest = self.store.get_manifest(board, task_id)
        if manifest is None:
            raise WorkflowProtocolError("no workflow manifest is bound to this task")
        parsed = parse_manifest(manifest)
        if parsed.template_id != WORKFLOW_TEMPLATE_ID:
            raise WorkflowProtocolError("manifest template is not autonomous-development.v1")
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

    def _snapshot(self, manifest: Mapping[str, Any]) -> PolicySnapshot:
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
                job_view = ActiveJobView(
                    job_id=str(job_id),
                    stage=row["stage"],
                    status=status,
                    result=result,
                    consumed=row.get("consumed_at") is not None,
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
        )

    def _create_or_reuse_job(self, manifest: dict[str, Any], action: WorkflowAction) -> dict[str, Any]:
        stage = action.stage
        if not stage:
            raise WorkflowProtocolError("create_job is missing a stage")
        board, task_id = manifest["board"], manifest["taskId"]
        inputs = self._inputs_for_stage(manifest, stage)
        session_id = None
        if stage == "plan" and manifest.get("plannerSessionId") and (
            action.reason == "plan_rework" or int(manifest.get("planReworkCount") or 0) > 0
        ):
            session_id = manifest.get("plannerSessionId")
        if stage == "implement" and manifest.get("implementerSessionId") and (
            action.reason == "implement_rework" or int(manifest.get("implementReworkCount") or 0) > 0
        ):
            session_id = manifest.get("implementerSessionId")
        failures = dict(manifest.get("runFailureCounts") or {})
        transport_retry = int(failures.get(stage, 0)) if action.reason == "transport_retry" else 0
        business_attempt = (
            int(manifest.get("planReworkCount") or 0) + 1
            if stage in {"plan", "plan_review"}
            else int(manifest.get("implementReworkCount") or 0) + 1
        )
        baseline = manifest.get("baseline") or {}
        workspace = {
            "repoRoot": manifest["repoRoot"],
            "branch": baseline.get("branch") or self.config.main_branch,
            "expectedHead": baseline.get("head") or "0" * 40,
            "requireCleanAtStart": stage in {"plan", "plan_review"} or (
                stage == "implement" and int(manifest.get("implementReworkCount") or 0) == 0
            ),
        }
        job = build_job(
            board=board,
            task_id=task_id,
            stage=stage,
            business_attempt=business_attempt,
            transport_retry=transport_retry,
            workspace=workspace,
            agents=self.agents,
            inputs=inputs,
            session_id=session_id,
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
        updated = dict(manifest)
        updated["activeJobId"] = job["jobId"]
        if action.target_status is not None:
            updated["workflowStatus"] = action.target_status.value
        updated["revision"] = int(manifest["revision"]) + 1
        self.store.cas_update_manifest(
            board, task_id, expected_revision=int(manifest["revision"]), manifest=updated
        )
        return updated

    def _inputs_for_stage(self, manifest: Mapping[str, Any], stage: str) -> tuple[dict[str, str], ...]:
        board, task_id = manifest["board"], manifest["taskId"]
        required = {"plan": ("requirement",), "plan_review": ("requirement", "plan"),
                    "implement": ("plan",), "execute_review": ("requirement", "plan", "implementation")}[stage]
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
        if handle.observation.kind == "live_process":
            wait_on_harness(
                run_dir=row["run_dir"],
                job_id=row["job_id"],
                job_sha256=row["job_sha256"],
                wait_seconds=wait_seconds,
                poll_interval_seconds=self.config.poll_interval_seconds,
                recorded_pid=handle.pid or row.get("harness_pid"),
                recorded_identity=handle.process_identity or row.get("process_identity"),
                heartbeat=lambda: self.dispatch_tool(
                    "kanban_heartbeat",
                    {"task_id": manifest["taskId"], "note": "autodev harness still running"},
                ),
                sleep_fn=self.sleep_fn,
                monotonic_fn=self.monotonic_fn,
                identity_fn=self.identity_fn,
            )
        return handle

    def _consume_and_maybe_lifecycle(self, manifest: dict[str, Any], *, run_id: str) -> dict[str, Any]:
        job_id = manifest["activeJobId"]
        row = self.store.get_job(str(job_id))
        result_path = Path(row["run_dir"]) / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        job_doc = json.loads(Path(row["job_path"]).read_text(encoding="utf-8"))
        previous = None
        if row.get("consumed_at") is not None:
            previous = result_digest(result)
        outcome = consume_result(job_doc, result, previously_consumed_sha256=previous)
        board, task_id = manifest["board"], manifest["taskId"]
        updated = dict(manifest)
        updated["revision"] = int(manifest["revision"]) + 1
        updated["lastConsumedJobId"] = job_id
        artifacts: list[dict[str, Any]] = []
        if outcome.kind == "consumed":
            updated["workflowStatus"] = outcome.next_status.value if outcome.next_status else manifest["workflowStatus"]
            if row["stage"] == "plan" and outcome.session_id:
                updated["plannerSessionId"] = outcome.session_id
            if row["stage"] == "implement" and outcome.session_id:
                updated["implementerSessionId"] = outcome.session_id
            if outcome.review_verdict == "request_changes" and row["stage"] == "plan_review":
                updated["planReworkCount"] = int(manifest.get("planReworkCount") or 0) + 1
            if outcome.review_verdict == "request_changes" and row["stage"] == "execute_review":
                updated["implementReworkCount"] = int(manifest.get("implementReworkCount") or 0) + 1
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
        elif outcome.kind == "transport_failure":
            failures = dict(manifest.get("runFailureCounts") or {})
            failures[row["stage"]] = int(failures.get(row["stage"], 0)) + 1
            updated["runFailureCounts"] = failures
        elif outcome.kind == "protocol_failure":
            updated["workflowStatus"] = WorkflowStatus.BLOCKED.value
            updated["pendingLifecycle"] = make_pending_lifecycle(
                target_status=WorkflowStatus.BLOCKED.value,
                run_id=run_id,
                workflow_revision=updated["revision"],
                args={"reason": outcome.reason or "protocol failure"},
            )
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
        action = next_action(snapshot)
        if action.kind == "apply_lifecycle" and action.target_status is not None:
            return self._write_and_apply_lifecycle(updated, action.target_status, run_id=run_id)
        if action.kind == "block":
            return self._write_and_apply_lifecycle(
                updated, WorkflowStatus.BLOCKED, run_id=run_id, reason=action.reason
            )
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
        pending = make_pending_lifecycle(
            target_status=target.value,
            run_id=run_id,
            workflow_revision=int(manifest["revision"]) + 1,
            args=args,
        )
        updated = dict(manifest)
        updated["revision"] = int(manifest["revision"]) + 1
        updated["workflowStatus"] = target.value
        updated["pendingLifecycle"] = pending
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
            updated["pendingLifecycle"] = None
            self.store.cas_update_manifest(
                manifest["board"],
                manifest["taskId"],
                expected_revision=int(manifest["revision"]),
                manifest=updated,
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
        return {
            "ok": True,
            "workflowStatus": status,
            "revision": manifest.get("revision"),
            "stageAttempt": manifest.get("stageAttempt"),
            "activeJobId": manifest.get("activeJobId"),
            "nextAction": action.kind,
            "inProgress": in_progress,
            "pendingLifecycle": manifest.get("pendingLifecycle"),
            "outcome": outcome,
        }


def snapshot_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return dict(manifest)
