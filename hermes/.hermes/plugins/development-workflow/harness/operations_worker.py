"""Worker-side Development Workflow operations (design §14, §16–§19.8, §22.2–§22.3).

``op_start_or_inspect_relay``, ``op_ui_lease``, ``op_implement_handoff``,
and ``op_review_verdict`` are owning-worker wrappers around Guard, evidence,
and native Kanban primitives. Models never pass Skill, mode, or model.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

from .context import (
    allowed_actions_for,
    apply_non_owning_quarantine,
    classify_session,
    require_worker_card,
    review_authority,
)
from .contracts import (
    CANDIDATE_SCHEMA_ID,
    PLAN_REVIEW_SCHEMA_ID,
    parse_decision_comment,
    validate_execute_review,
    validate_plan_review,
)
from .errors import (
    ADAPTER_CAPABILITY_MISSING,
    AUTO_HANDOFF_INVALID,
    BRIEF_MISSING,
    CARD_CONTRACT_INVALID,
    CANDIDATE_NOT_FROZEN,
    EVIDENCE_IDENTITY_MISMATCH,
    HARNESS_INCOMPATIBLE,
    HARNESS_STATE_UNAVAILABLE,
    IMPLEMENT_ROLE_REQUIRED,
    MANUAL_ACCEPTANCE_PENDING,
    PLAN_IDENTITY_MISSING,
    PLAN_SHA_MISMATCH,
    RELAY_ATTEMPT_UNCERTAIN,
    REVIEW_GATE_INCOMPLETE,
    REVIEW_ROLE_REQUIRED,
    ROUND_LIMIT_REACHED,
    RUN_NOT_OWNED,
    RUN_OWNERSHIP_LOST,
    UI_ACCEPTANCE_INCOMPLETE,
    WORKSPACE_INVALID,
    failure,
)
from .evidence import (
    REVIEW_EVIDENCE_FILENAME,
    extract_review_report,
    fallback_eligible,
    handoff_metadata_from_runs,
    load_candidate_manifests,
    load_json,
    load_review_evidence,
    load_ui_evidence,
    normalize_execute_review,
    normalize_plan_review,
    relay_attempt_dir,
    require_successful_relay_result,
    review_round_from_events,
    review_round_run_dir,
    sha256_file,
    task_dir,
    verify_auto_handoff_result,
    verify_landing,
    verify_plan_identity,
    verify_ui_evidence_binding,
    write_candidate_manifest,
    write_json_atomic,
    write_review_evidence,
)
from .guard_client import GuardClient
from .policy import (
    MAX_REVIEW_ROUNDS,
    POLICIES,
    check_adapter_capability,
    resolve_relay_spec,
)
from .ui_lease import UiLeaseManager, lease_records, load_release_history

REVIEW_RELAY_SCHEMA = "devflow-review-relay.v1"
REVIEW_WAIT_DEFAULT_SECONDS = 1800
REVIEW_WAIT_MAX_SECONDS = 3000
BLOCK_KINDS = ("needs_input", "capability", "dependency", "transient")
_NON_SUCCESS_STATUSES = frozenset({"failed", "timeout", "aborted", "unavailable"})
_UNCERTAIN_REMEDIATION = (
    "typed block: use the narrow manual recovery procedure; never retry or "
    "delete guard state"
)
_HANDOFF_NON_SUCCESS = "cannot hand off a non-successful relay attempt"
_PLAN_INVALIDATED_MSG = (
    "accepted plan invalidated by amendment; Origin must re-establish the "
    "write-plan→execute chain"
)
_RECORD_TERMINAL_ALREADY = 3
_TERMINAL_ATTEMPT = "terminal"
_NON_TERMINAL_LIVE = frozenset({"running", "reserved"})
_LIVE_REVIEW_PROCS: dict[int, subprocess.Popen] = {}
_PI_UNAVAILABLE_REMEDIATION = "pi binary missing; fix the adapter environment"
_REWORK_REMEDIATION = (
    "start a rework attempt (or apply fallback rules); never silently "
    "substitute a model"
)
_FALLBACK_RETRY_REMEDIATION = (
    "retry start_or_inspect_relay to use the one-time fallback model and "
    "resume the exact session"
)
_FALLBACK_USED_REMEDIATION = (
    "one-time fallback model already used; Origin must intervene"
)
_RESUME_SESSION_REMEDIATION = "resume the exact session and rework"


def _cleanup_review_procs() -> None:
    for pid, child in list(_LIVE_REVIEW_PROCS.items()):
        child.poll()
        _LIVE_REVIEW_PROCS.pop(pid, None)


atexit.register(_cleanup_review_procs)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fail(ctx: Any, code: str, message: str, **details: Any) -> NoReturn:
    kwargs: dict[str, Any] = dict(details)
    if ctx is not None:
        kwargs.setdefault("current_state", ctx.current_state())
        kwargs.setdefault("allowed_actions", allowed_actions_for(ctx.role))
    raise failure(code, message, **kwargs)


def _prologue(adapter: Any) -> Any:
    probe = adapter.probe()
    if probe.get("ok") is not True:
        raise failure(
            HARNESS_INCOMPATIBLE,
            "Hermes adapter is missing required capabilities",
            missing=probe.get("missing") or [],
        )
    ctx = classify_session(adapter)
    if ctx.role == "non-owning-worker":
        apply_non_owning_quarantine()
        _fail(
            ctx,
            RUN_OWNERSHIP_LOST,
            "this session is not the owning worker for the current run",
            reasons=list(ctx.reasons or []),
        )
    return ctx


def _require_roles(ctx: Any, *roles: str, code: str, message: str) -> None:
    if ctx.role not in roles:
        _fail(ctx, code, message)


def _worker_card(adapter: Any, ctx: Any) -> tuple[Any, Path]:
    card = require_worker_card(adapter, ctx)
    raw = getattr(ctx.card, "workspace_path", None)
    repo = Path(str(raw))
    return card, repo


def _card_id(ctx: Any) -> str:
    return str(ctx.card.id)


def _resolve_board(adapter: Any, ctx: Any) -> str:
    board = (ctx.board or "").strip() if ctx.board else ""
    if board:
        return board
    try:
        current = adapter.get_current_board()
    except Exception as exc:
        _fail(ctx, WORKSPACE_INVALID, f"cannot resolve current board: {exc}")
    board = str(current).strip() if current else ""
    if not board:
        _fail(ctx, WORKSPACE_INVALID, "no board specified and no current board")
    return board


def _connect(adapter: Any, ctx: Any, board: str | None = None) -> Any:
    try:
        return adapter.connect(board=board or ctx.board)
    except Exception as exc:
        _fail(ctx, HARNESS_STATE_UNAVAILABLE, f"kanban connect failed: {exc}")


def _task_dir(adapter: Any, board: str, card_id: str) -> Path:
    return task_dir(adapter.artifacts_root, board, card_id)


def _guard_client(adapter: Any, board: str, card_id: str) -> GuardClient:
    return GuardClient(
        script_path=adapter.guard_script_path,
        home=adapter.hermes_home,
        board=board,
        card_id=card_id,
        artifacts_root=adapter.artifacts_root,
    )


def _plan_path(accepted_plan: Any) -> str | None:
    if isinstance(accepted_plan, dict):
        path = accepted_plan.get("path")
        return str(path) if isinstance(path, str) and path else None
    return None


def _plan_sha(accepted_plan: Any) -> str | None:
    if isinstance(accepted_plan, dict):
        sha = accepted_plan.get("sha256")
        return str(sha) if isinstance(sha, str) and sha else None
    return None


def _is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    child = _LIVE_REVIEW_PROCS.get(pid)
    if child is not None:
        code = child.poll()
        if code is not None:
            _LIVE_REVIEW_PROCS.pop(pid, None)
            return False
        return True
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


def _ps_lstart(pid: int) -> str | None:
    proc = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = proc.stdout.strip()
    return output if proc.returncode == 0 and output else None


def _list_events(adapter: Any, ctx: Any, card_id: str) -> list:
    conn = _connect(adapter, ctx)
    try:
        return list(adapter.list_events(conn, card_id) or [])
    finally:
        adapter.close(conn)


def _latest_landing(state: dict | None) -> dict | None:
    if not isinstance(state, dict):
        return None
    landings = state.get("landings") or []
    if not isinstance(landings, list) or not landings:
        return None
    last = landings[-1]
    return last if isinstance(last, dict) else None


def _latest_attempt(state: dict | None) -> dict | None:
    if not isinstance(state, dict):
        return None
    attempts = state.get("attempts") or []
    if not isinstance(attempts, list) or not attempts:
        return None
    last = attempts[-1]
    return last if isinstance(last, dict) else None


def _find_attempt(state: dict | None, number: Any) -> dict | None:
    if not isinstance(state, dict):
        return None
    for attempt in state.get("attempts") or []:
        if isinstance(attempt, dict) and attempt.get("number") == number:
            return attempt
    return None


def _require_terminal_attempt(
    ctx: Any, state: dict | None, *, operations: tuple[str, ...] | None = None
) -> dict:
    last = _latest_attempt(state)
    if last is None:
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            "no relay attempt is recorded",
            remediation=_UNCERTAIN_REMEDIATION,
        )
    state_name = last.get("state")
    if state_name in _NON_TERMINAL_LIVE:
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            "relay still live",
            attempt_state=state_name,
            remediation=_UNCERTAIN_REMEDIATION,
        )
    if state_name != _TERMINAL_ATTEMPT or not last.get("terminal_status"):
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            f"latest relay attempt is {state_name!r}, not recorded-terminal",
            attempt_state=state_name,
            remediation=_UNCERTAIN_REMEDIATION,
        )
    if operations is not None and last.get("operation") not in operations:
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            f"latest terminal attempt operation is {last.get('operation')!r}, "
            f"expected one of {list(operations)}",
            operation=last.get("operation"),
            remediation=_UNCERTAIN_REMEDIATION,
        )
    return last


def _check_run_or_fail(ctx: Any, guard: GuardClient) -> None:
    rc, payload = guard.check_run()
    if rc != 0 or payload.get("ok") is False:
        _fail(
            ctx,
            RUN_NOT_OWNED,
            "guard check-run refused current task/run ownership",
            reason=payload.get("reason"),
            guard=payload,
        )


def _envelope_mode(spec: Any) -> str:
    if getattr(spec, "review", False) or getattr(spec, "mode", None) == "read":
        return "read-only"
    return "write"


def _model_for_result(spec: Any, result: Any) -> str:
    requested = result.get("requestedModel") if isinstance(result, dict) else None
    if spec.fallback_model and requested == spec.fallback_model:
        return spec.fallback_model
    return spec.model


def _fallback_already_used(attempts: list, spec: Any) -> bool:
    if not spec.fallback_model:
        return False
    for attempt in attempts or []:
        if not isinstance(attempt, dict) or attempt.get("state") != _TERMINAL_ATTEMPT:
            continue
        result = load_json(attempt.get("result_path"))
        if isinstance(result, dict) and result.get("requestedModel") == spec.fallback_model:
            return True
    return False


def _prior_terminal_session(attempts: list) -> str | None:
    for attempt in reversed(list(attempts or [])):
        if not isinstance(attempt, dict) or attempt.get("state") != _TERMINAL_ATTEMPT:
            continue
        session = attempt.get("session_id")
        if isinstance(session, str) and session.strip():
            return session
        result = load_json(attempt.get("result_path"))
        if isinstance(result, dict):
            sid = result.get("sessionId")
            if isinstance(sid, str) and sid.strip():
                return sid
    return None


def _session_of(attempt: dict | None, result: Any = None) -> str | None:
    if isinstance(attempt, dict):
        session = attempt.get("session_id")
        if isinstance(session, str) and session.strip():
            return session
        if result is None:
            result = load_json(attempt.get("result_path"))
    if isinstance(result, dict):
        sid = result.get("sessionId")
        if isinstance(sid, str) and sid.strip():
            return sid
    return None


def _non_success_remediation(result: Any, spec: Any) -> str:
    if not isinstance(result, dict):
        return _REWORK_REMEDIATION
    if result.get("status") == "unavailable" or result.get("sourceStatus") == "pi_unavailable":
        return _PI_UNAVAILABLE_REMEDIATION
    if fallback_eligible(result) and spec.fallback_model:
        return _FALLBACK_RETRY_REMEDIATION
    return _REWORK_REMEDIATION


def _has_changes_requested(events) -> bool:
    return any(getattr(event, "kind", None) == "changes_requested" for event in events or [])


def _has_ui_fail(task_dir_path: Path, candidate: str | None) -> bool:
    if not candidate:
        return False
    return any(
        item.get("verdict") == "FAIL"
        for item in load_ui_evidence(task_dir_path, candidate)
    )


def _desired_write_operation(
    stage_name: str,
    events,
    task_dir_path: Path,
    landing_commit: str | None,
) -> str:
    changes = _has_changes_requested(events)
    ui_fail = _has_ui_fail(task_dir_path, landing_commit)
    if stage_name == "write-plan":
        return "rework" if changes else "planning"
    if changes or ui_fail:
        return "rework"
    return "execution"


def _plan_invalidated(adapter: Any, conn: Any, card_id: str) -> dict | None:
    specified_at: int | None = None
    for event in adapter.list_events(conn, card_id) or []:
        if getattr(event, "kind", None) != "specified":
            continue
        created = getattr(event, "created_at", None)
        if created is None:
            continue
        try:
            stamp = int(created)
        except (TypeError, ValueError):
            continue
        if specified_at is None or stamp > specified_at:
            specified_at = stamp
    threshold = specified_at if specified_at is not None else -1
    for comment in adapter.list_comments(conn, card_id) or []:
        parsed = parse_decision_comment(getattr(comment, "body", None) or "")
        if not isinstance(parsed, dict):
            continue
        if parsed.get("kind") != "amendment":
            continue
        if parsed.get("affects_accepted_plan") is not True:
            continue
        try:
            created_at = int(getattr(comment, "created_at", 0) or 0)
        except (TypeError, ValueError):
            created_at = 0
        if created_at > threshold:
            return parsed
    return None


def _refuse_invalidated_plan(adapter: Any, ctx: Any, card_id: str) -> None:
    conn = _connect(adapter, ctx)
    try:
        amendment = _plan_invalidated(adapter, conn, card_id)
    finally:
        adapter.close(conn)
    if amendment is not None:
        _fail(
            ctx,
            PLAN_IDENTITY_MISSING,
            _PLAN_INVALIDATED_MSG,
            amendment=amendment,
        )


def _strip_path_key(item: dict) -> dict:
    return {key: value for key, value in item.items() if key != "_path"}


def _ui_binding_code(violations: list[str]) -> str:
    identity_markers = (
        "does not match",
        "identity",
        "lease_id",
        "holder_run",
        "candidate_commit",
        "relay_session_id",
        "run_id",
        "attempt_number",
    )
    blob = " ".join(violations).lower()
    if any(marker in blob for marker in identity_markers):
        return EVIDENCE_IDENTITY_MISMATCH
    return UI_ACCEPTANCE_INCOMPLETE


def _require_ui_pass(
    ctx: Any,
    adapter: Any,
    stage: Any,
    task_dir_path: Path,
    *,
    candidate: str,
    manifest: dict,
    attempt_number: int,
    plan: dict | None,
    relay_session_id: str | None,
) -> None:
    if stage.ui_acceptance != "required":
        return
    items = load_ui_evidence(task_dir_path, candidate)
    pass_items = [item for item in items if item.get("verdict") == "PASS"]
    if not pass_items:
        verdicts = [item.get("verdict") for item in items]
        _fail(
            ctx,
            UI_ACCEPTANCE_INCOMPLETE,
            "required UI acceptance has no PASS evidence for this candidate",
            candidate_commit=candidate,
            verdicts=verdicts,
        )
    ev = _strip_path_key(pass_items[0])
    violations = verify_ui_evidence_binding(
        ev,
        manifest=manifest,
        card=stage,
        run_id=int(ctx.env_run_id),
        attempt_number=int(attempt_number),
        plan=plan,
        relay_session_id=relay_session_id,
        lease_records=lease_records(adapter.hermes_home),
    )
    if violations:
        _fail(
            ctx,
            _ui_binding_code(violations),
            "UI evidence is not bound to the current candidate/run/lease",
            violations=violations,
            candidate_commit=candidate,
        )


def _manual_verdict_or_fail(
    adapter: Any, ctx: Any, conn: Any, card_id: str, stage: Any, candidate: str
) -> None:
    manual = stage.manual_acceptance
    if not (isinstance(manual, list) and manual):
        return
    fail_hit = False
    pass_hit = False
    for comment in adapter.list_comments(conn, card_id) or []:
        parsed = parse_decision_comment(getattr(comment, "body", None) or "")
        if not isinstance(parsed, dict):
            continue
        if parsed.get("kind") != "manual-verdict":
            continue
        if parsed.get("candidate_commit") != candidate:
            continue
        verdict = parsed.get("verdict")
        if verdict == "PASS":
            pass_hit = True
        elif verdict == "FAIL":
            fail_hit = True
    if fail_hit:
        _fail(
            ctx,
            MANUAL_ACCEPTANCE_PENDING,
            "manual acceptance recorded FAIL for this candidate",
            candidate_commit=candidate,
            remediation=_RESUME_SESSION_REMEDIATION,
        )
    if not pass_hit:
        _fail(
            ctx,
            MANUAL_ACCEPTANCE_PENDING,
            "manual acceptance PASS verdict is pending for this candidate",
            candidate_commit=candidate,
        )


def _write_manifest(
    *,
    adapter: Any,
    board: str,
    card_id: str,
    stage: Any,
    candidate: str,
    baseline_head: str,
    implement_run_id: int,
    attempt_number: int,
) -> tuple[dict, str]:
    accepted = None
    if stage.stage == "execute-plan" and isinstance(stage.accepted_plan, dict):
        accepted = {
            "path": stage.accepted_plan.get("path"),
            "sha256": stage.accepted_plan.get("sha256"),
        }
    task_dir_path = _task_dir(adapter, board, card_id)
    dest = task_dir_path / "candidates" / candidate / "candidate.json"
    existing = load_json(dest)
    created_at = (
        existing.get("created_at")
        if isinstance(existing, dict) and existing.get("created_at")
        else datetime.now(timezone.utc).isoformat()
    )
    manifest = {
        "schema": CANDIDATE_SCHEMA_ID,
        "board": board,
        "card_id": card_id,
        "feature_id": stage.feature_id,
        "stage": stage.stage,
        "implement_run_id": int(implement_run_id),
        "attempt_number": int(attempt_number),
        "candidate_commit": candidate,
        "diff_base": baseline_head,
        "diff_head": candidate,
        "accepted_plan": accepted,
        "created_at": created_at,
    }
    written = write_candidate_manifest(task_dir_path, manifest)
    return written, str(dest)


def _recheck_ownership(adapter: Any, ctx: Any, conn: Any, card_id: str) -> None:
    fresh = adapter.get_task(conn, card_id)
    current = getattr(fresh, "current_run_id", None) if fresh is not None else None
    if fresh is None or current is None or int(current) != int(ctx.env_run_id):
        _fail(
            ctx,
            RUN_OWNERSHIP_LOST,
            "current run ownership was lost before the native handoff",
        )


def _event_kinds(adapter: Any, conn: Any, card_id: str) -> list[str]:
    return [
        getattr(event, "kind", None)
        for event in (adapter.list_events(conn, card_id) or [])
    ]


def _brief_or_fail(ctx: Any, brief_path: str, card_id: str) -> Path:
    if not isinstance(brief_path, str) or not brief_path.strip():
        _fail(ctx, BRIEF_MISSING, "brief_path is required", rule="required")
    path = Path(brief_path)
    if not path.is_file():
        _fail(
            ctx,
            BRIEF_MISSING,
            f"brief file does not exist: {path}",
            rule="exists",
            path=str(path),
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(
            ctx,
            BRIEF_MISSING,
            f"brief file is unreadable: {exc}",
            rule="readable",
            path=str(path),
        )
    if not text.strip():
        _fail(
            ctx,
            BRIEF_MISSING,
            f"brief file is empty: {path}",
            rule="non-empty",
            path=str(path),
        )
    if card_id not in text:
        _fail(
            ctx,
            BRIEF_MISSING,
            f"brief does not contain the current card id {card_id!r}",
            rule="card-id",
            path=str(path),
            card_id=card_id,
        )
    return path


def _resolve_brief_or_fail(
    ctx: Any,
    *,
    brief_path: str | None,
    brief_content: str | None,
    card_id: str,
    dest_dir: Path,
) -> Path:
    """Resolve the Relay brief to a file on disk.

    ``brief_path`` keeps its legacy meaning (an already-on-disk brief the
    caller authored). ``brief_content`` is the review-friendly channel: the
    worker passes the brief text inline, the harness validates the same
    contract (non-empty, cites the card id) and persists it into the
    run-scoped adapter directory (control-plane evidence) before spawning.
    Exactly one of the two must be provided. Returns the brief file path.
    """
    has_path = isinstance(brief_path, str) and bool(brief_path.strip())
    has_content = isinstance(brief_content, str) and bool(brief_content.strip())
    if has_path and has_content:
        _fail(
            ctx,
            BRIEF_MISSING,
            "pass either brief_path or brief_content, not both",
            rule="exclusive",
        )
    if has_content:
        text = str(brief_content)
        if card_id not in text:
            _fail(
                ctx,
                BRIEF_MISSING,
                f"brief does not contain the current card id {card_id!r}",
                rule="card-id",
                card_id=card_id,
            )
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / "brief.md"
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return path
    return _brief_or_fail(ctx, brief_path or "", card_id)


def _validate_repo_or_fail(ctx: Any, repo: str | None) -> Path:
    if not isinstance(repo, str) or not repo.strip():
        _fail(
            ctx,
            WORKSPACE_INVALID,
            "repo is required to initialize guard state and must be an "
            "absolute existing git repository",
        )
    path = Path(repo)
    if not path.is_absolute():
        _fail(
            ctx,
            WORKSPACE_INVALID,
            f"repo must be an absolute path (got {repo!r})",
            repo=repo,
        )
    if not path.is_dir() or not _is_git_repo(path):
        _fail(
            ctx,
            WORKSPACE_INVALID,
            f"repo is not an existing git repository: {path}",
            repo=str(path),
        )
    return path


# ---------------------------------------------------------------------------
# Relay argv (test seam)
# ---------------------------------------------------------------------------


def build_relay_argv(
    spec: Any,
    *,
    relay_script: Path,
    brief_path: str,
    repo: str,
    out_dir: str,
    result_path: str,
    resume_session: str | None,
    plan_path: str | None,
    model: str,
) -> list[str]:
    """Build ``node relay.mjs ...`` argv. Tests monkeypatch this seam."""
    argv = [
        "node",
        str(relay_script),
        "--brief",
        str(brief_path),
        "--cd",
        str(repo),
    ]
    if spec.mode == "read":
        argv.append("--read-only")
    else:
        argv.append("--write")
    argv.extend(["--model", str(model)])
    thinking = getattr(spec, "thinking", None)
    if thinking:
        argv.extend(["--thinking", str(thinking)])
    if resume_session:
        argv.extend(["--session", str(resume_session)])
    argv.extend(["--out-dir", str(out_dir)])
    if plan_path:
        argv.extend(["--auto-handoff-plan", str(plan_path)])
    return argv


# ---------------------------------------------------------------------------
# Write-mode / review relay
# ---------------------------------------------------------------------------


def _gate_successful_result(
    ctx: Any,
    spec: Any,
    result: Any,
    *,
    expected_cwd: str,
    require_final_message: bool = False,
    allow_report_status: bool = False,
) -> list[str]:
    expected_model = _model_for_result(spec, result)
    violations = require_successful_relay_result(
        result,
        expected_cwd=expected_cwd,
        expected_mode=_envelope_mode(spec),
        expected_model=expected_model,
        expected_thinking=spec.thinking,
        require_final_message=require_final_message,
    )
    if not violations:
        return []
    status = result.get("status") if isinstance(result, dict) else None
    if allow_report_status and status in _NON_SUCCESS_STATUSES:
        remediation = _non_success_remediation(result, spec)
        if (
            spec.fallback_model
            and fallback_eligible(result)
            and _fallback_already_used_from_result(result, spec)
        ):
            remediation = _FALLBACK_USED_REMEDIATION
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            "terminal relay result is not a successful stage result",
            violations=violations,
            status=status,
            remediation=remediation,
        )
    _fail(
        ctx,
        RELAY_ATTEMPT_UNCERTAIN,
        "terminal relay result is not a successful stage result",
        violations=violations,
        status=status,
        remediation=_UNCERTAIN_REMEDIATION,
    )


def _fallback_already_used_from_result(result: dict, spec: Any) -> bool:
    return bool(
        spec.fallback_model and result.get("requestedModel") == spec.fallback_model
    )


def _consume_terminal(
    ctx: Any,
    guard: GuardClient,
    spec: Any,
    stage: Any,
    payload: dict,
    *,
    expected_cwd: str,
) -> dict:
    attempt_number = payload.get("attempt_number")
    state = guard.read_state() or {}
    attempt = _find_attempt(state, attempt_number) or _latest_attempt(state)
    if attempt is None:
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            "terminal outcome has no matching attempt",
            remediation=_UNCERTAIN_REMEDIATION,
        )
    result_path = attempt.get("result_path")
    rc, recorded = guard.record_terminal(result_path)
    if rc not in (0, _RECORD_TERMINAL_ALREADY):
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            "record-terminal refused the result",
            reason=(recorded or {}).get("reason"),
            guard=recorded,
            remediation=_UNCERTAIN_REMEDIATION,
        )
    state = guard.read_state() or state
    attempt = _find_attempt(state, attempt.get("number")) or attempt
    result = load_json(attempt.get("result_path"))
    _gate_successful_result(
        ctx, spec, result, expected_cwd=expected_cwd, allow_report_status=True
    )
    assert isinstance(result, dict)
    auto_handoff = None
    if spec.auto_handoff:
        out_dir = str(attempt.get("out_dir") or "")
        expected = _plan_path(stage.accepted_plan)
        if not expected:
            _fail(
                ctx,
                AUTO_HANDOFF_INVALID,
                "accepted plan path is missing for Auto Handoff verification",
            )
        auto_handoff = verify_auto_handoff_result(
            result, expected_plan_path=expected, out_dir=out_dir
        )
    session_id = (
        attempt.get("session_id")
        or result.get("sessionId")
        or payload.get("session_id")
    )
    return {
        "ok": True,
        "outcome": "terminal",
        "attempt_number": attempt.get("number"),
        "session_id": session_id,
        "status": result.get("status") or payload.get("status"),
        "auto_handoff": auto_handoff,
        "operation": attempt.get("operation"),
    }


def _write_mode_relay(
    adapter: Any,
    ctx: Any,
    stage: Any,
    *,
    brief_path: str,
    repo: Path,
) -> dict:
    card_id = _card_id(ctx)
    board = _resolve_board(adapter, ctx)
    if str(stage.stage) == "execute-plan":
        _refuse_invalidated_plan(adapter, ctx, card_id)
    brief = _brief_or_fail(ctx, brief_path, card_id)
    events = _list_events(adapter, ctx, card_id)
    if str(stage.stage) == "execute-plan":
        verify_plan_identity(
            stage.accepted_plan if isinstance(stage.accepted_plan, dict) else {}
        )

    guard = _guard_client(adapter, board, card_id)
    state = guard.read_state()
    if state is None:
        repo_path = _validate_repo_or_fail(ctx, str(repo))
        rc, initialized = guard.init(repo_path)
        if rc == 3:
            state = guard.read_state()
        elif rc != 0 or not (initialized or {}).get("ok"):
            _fail(
                ctx,
                WORKSPACE_INVALID,
                "guard init failed",
                reason=(initialized or {}).get("reason"),
                guard=initialized,
            )
        else:
            state = guard.read_state()
        if state is None:
            _fail(
                ctx,
                HARNESS_STATE_UNAVAILABLE,
                "guard state is unavailable after init",
            )

    attempts = list(state.get("attempts") or [])
    last = attempts[-1] if attempts else None
    task_dir_path = _task_dir(adapter, board, card_id)
    landing = _latest_landing(state)
    landing_commit = (
        str(landing["commit"]) if landing and landing.get("commit") else None
    )
    operation = _desired_write_operation(
        str(stage.stage), events, task_dir_path, landing_commit
    )
    spec = resolve_relay_spec(
        stage=str(stage.stage),
        operation=operation,
        coding_agent=str(stage.coding_agent),
        review=False,
    )
    issues = check_adapter_capability(
        str(stage.coding_agent),
        hermes_home=adapter.hermes_home,
        auto_handoff_required=spec.auto_handoff,
    )
    if issues:
        _fail(
            ctx,
            ADAPTER_CAPABILITY_MISSING,
            "coding agent adapter is missing required capabilities: "
            + "; ".join(issues),
            issues=issues,
            coding_agent=stage.coding_agent,
        )

    cwd = str(state.get("repo") or repo)
    last_result = load_json(last.get("result_path")) if last else None
    want_fallback = False
    if (
        last is not None
        and last.get("state") == _TERMINAL_ATTEMPT
        and fallback_eligible(last_result)
        and spec.fallback_model
        and not _fallback_already_used(attempts, spec)
    ):
        want_fallback = True

    resume_session = None
    model = spec.model
    fallback_used = False
    new_attempt = False

    if last is None:
        n = 1
        out_dir = str(relay_attempt_dir(task_dir_path, n))
        result_path = str(Path(out_dir) / "result.json")
    elif last.get("state") != _TERMINAL_ATTEMPT:
        n = last["number"]
        out_dir = str(last["out_dir"])
        result_path = str(last["result_path"])
    elif want_fallback:
        n = int(last["number"]) + 1
        out_dir = str(relay_attempt_dir(task_dir_path, n))
        result_path = str(Path(out_dir) / "result.json")
        new_attempt = True
        model = spec.fallback_model
        fallback_used = True
        resume_session = _session_of(last, last_result)
    elif last.get("operation") == operation:
        n = last["number"]
        out_dir = str(last["out_dir"])
        result_path = str(last["result_path"])
    else:
        n = int(last["number"]) + 1
        out_dir = str(relay_attempt_dir(task_dir_path, n))
        result_path = str(Path(out_dir) / "result.json")
        new_attempt = True

    if (
        last is not None
        and last.get("state") == _TERMINAL_ATTEMPT
        and last.get("operation") == operation
        and not want_fallback
        and isinstance(last_result, dict)
        and last_result.get("status") in _NON_SUCCESS_STATUSES
        and not fallback_eligible(last_result)
    ):
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            "terminal relay result is not a successful stage result",
            status=last_result.get("status"),
            remediation=_non_success_remediation(last_result, spec),
        )

    if operation == "rework" and not fallback_used:
        resume_session = _prior_terminal_session(attempts)

    plan_artifact = None
    plan_path = None
    if str(stage.stage) == "execute-plan":
        plan_path = _plan_path(stage.accepted_plan)
        plan_artifact = plan_path

    relay_script = Path(adapter.hermes_home) / spec.skill_script_relpath
    argv = build_relay_argv(
        spec,
        relay_script=relay_script,
        brief_path=str(brief),
        repo=cwd,
        out_dir=out_dir,
        result_path=result_path,
        resume_session=resume_session,
        plan_path=plan_path if spec.auto_handoff else None,
        model=model,
    )
    rc, outcome_payload = guard.start_or_inspect(
        operation=operation,
        out_dir=out_dir,
        result_path=result_path,
        cmd_json=argv,
        cwd=cwd,
        plan_artifact=plan_artifact,
        new_attempt=new_attempt,
    )
    if rc != 0:
        _fail(
            ctx,
            HARNESS_STATE_UNAVAILABLE,
            "guard start-or-inspect failed",
            guard=outcome_payload,
        )
    outcome = outcome_payload.get("outcome")
    if outcome == "uncertain":
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            str(outcome_payload.get("reason") or "relay attempt is uncertain"),
            reason=outcome_payload.get("reason"),
            remediation=_UNCERTAIN_REMEDIATION,
        )
    if outcome == "terminal":
        return _consume_terminal(
            ctx, guard, spec, stage, outcome_payload, expected_cwd=cwd
        )
    if outcome in ("spawned", "attach"):
        result: dict[str, Any] = {
            "ok": True,
            "outcome": outcome,
            "attempt_number": outcome_payload.get("attempt_number", n),
            "skill": spec.skill,
            "mode": spec.mode,
            "model": model,
            "out_dir": out_dir,
            "result_path": result_path,
            "resumed": resume_session,
            "auto_handoff": spec.auto_handoff,
            "operation": operation,
        }
        if "pid" in outcome_payload:
            result["pid"] = outcome_payload["pid"]
        if fallback_used:
            result["fallback"] = True
        return result
    _fail(
        ctx,
        RELAY_ATTEMPT_UNCERTAIN,
        f"guard returned unclassified outcome {outcome!r}",
        guard=outcome_payload,
        remediation=_UNCERTAIN_REMEDIATION,
    )


def _review_spawn(
    ctx: Any,
    spec: Any,
    *,
    brief: Path,
    repo: str,
    run_dir: Path,
    result_path: Path,
    model: str,
    relay_script: Path,
) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    argv = build_relay_argv(
        spec,
        relay_script=relay_script,
        brief_path=str(brief),
        repo=str(repo),
        out_dir=str(run_dir),
        result_path=str(result_path),
        resume_session=None,
        plan_path=None,
        model=model,
    )
    stdout_log = open(run_dir / "relay-stdout.log", "ab")
    stderr_log = open(run_dir / "relay-stderr.log", "ab")
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(repo) if repo else None,
            stdin=subprocess.DEVNULL,
            stdout=stdout_log,
            stderr=stderr_log,
            start_new_session=True,
        )
    except OSError as exc:
        stdout_log.close()
        stderr_log.close()
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            f"review relay spawn failed: {exc}",
            remediation=_UNCERTAIN_REMEDIATION,
        )
    stdout_log.close()
    stderr_log.close()
    _LIVE_REVIEW_PROCS[proc.pid] = proc
    process_start = _ps_lstart(proc.pid)
    started_at = datetime.now(timezone.utc).isoformat()
    write_json_atomic(
        run_dir / "relay.json",
        {
            "schema": REVIEW_RELAY_SCHEMA,
            "pid": proc.pid,
            "process_start": process_start,
            "result_path": str(result_path),
            "session_id": None,
            "started_at": started_at,
        },
    )
    return {
        "ok": True,
        "outcome": "spawned",
        "attempt_number": None,
        "pid": proc.pid,
        "skill": spec.skill,
        "mode": spec.mode,
        "model": model,
        "out_dir": str(run_dir),
        "result_path": str(result_path),
        "resumed": None,
        "auto_handoff": False,
    }


def _review_summary(evidence_doc: dict) -> dict:
    if evidence_doc.get("schema") == PLAN_REVIEW_SCHEMA_ID:
        return {"verdict": evidence_doc.get("verdict")}
    overall = evidence_doc.get("overall") or {}
    patch = evidence_doc.get("patch_gate") or {}
    conformance = evidence_doc.get("plan_conformance_gate") or {}
    return {
        "verdict": overall.get("verdict") if isinstance(overall, dict) else overall,
        "gates": {
            "patch_gate": patch.get("verdict") if isinstance(patch, dict) else None,
            "plan_conformance_gate": (
                conformance.get("verdict") if isinstance(conformance, dict) else None
            ),
        },
    }


def _review_consume_or_attach(
    ctx: Any,
    spec: Any,
    stage: Any,
    run_dir: Path,
    record: dict,
    model: str,
    *,
    expected_cwd: str,
    board: str,
    card_id: str,
    round_n: int,
) -> dict:
    pid = record.get("pid")
    recorded_start = record.get("process_start")
    result_path = Path(str(record.get("result_path") or (run_dir / "result.json")))
    if _pid_alive(pid):
        current = _ps_lstart(int(pid))
        if recorded_start and current == recorded_start:
            return {
                "ok": True,
                "outcome": "attach",
                "attempt_number": None,
                "pid": pid,
                "skill": spec.skill,
                "mode": spec.mode,
                "model": model,
                "out_dir": str(run_dir),
                "result_path": str(result_path),
                "resumed": None,
                "auto_handoff": False,
            }
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            "review relay pid identity mismatch",
            reason="pid-identity-mismatch",
            remediation=_UNCERTAIN_REMEDIATION,
        )
    result = load_json(result_path)
    _gate_successful_result(
        ctx,
        spec,
        result,
        expected_cwd=expected_cwd,
        require_final_message=True,
        allow_report_status=True,
    )
    assert isinstance(result, dict)
    try:
        report = extract_review_report(result.get("finalMessage") or "")
        kwargs = dict(
            board=board,
            card_id=card_id,
            feature_id=str(stage.feature_id),
            review_run_id=int(ctx.env_run_id),
            round=int(round_n),
        )
        if str(stage.stage) == "write-plan":
            evidence_doc = normalize_plan_review(report, **kwargs)
        else:
            evidence_doc = normalize_execute_review(report, **kwargs)
    except ValueError as exc:
        message = str(exc)
        code = (
            EVIDENCE_IDENTITY_MISMATCH
            if "identity mismatch" in message
            else REVIEW_GATE_INCOMPLETE
        )
        _fail(ctx, code, message)
    written = write_review_evidence(run_dir, evidence_doc)
    evidence_path = str(run_dir / REVIEW_EVIDENCE_FILENAME)
    return {
        "ok": True,
        "outcome": "terminal",
        "attempt_number": None,
        "session_id": result.get("sessionId"),
        "status": result.get("status"),
        "skill": spec.skill,
        "mode": spec.mode,
        "model": model,
        "out_dir": str(run_dir),
        "result_path": str(result_path),
        "auto_handoff": None,
        "review_evidence_path": evidence_path,
        "summary": _review_summary(written),
    }


def _review_wait_seconds(ctx: Any, value: Any) -> int:
    if value is None:
        return REVIEW_WAIT_DEFAULT_SECONDS
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            "wait_seconds must be an integer",
            wait_seconds=value,
        )
    if value < 0 or value > REVIEW_WAIT_MAX_SECONDS:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"wait_seconds must be between 0 and {REVIEW_WAIT_MAX_SECONDS}",
            wait_seconds=value,
        )
    return value


def _wait_for_review_process(pid: int, wait_seconds: int) -> None:
    """Block on the run-owned review Relay without a model polling loop."""
    if wait_seconds <= 0:
        return
    child = _LIVE_REVIEW_PROCS.get(pid)
    if child is not None:
        try:
            child.wait(timeout=wait_seconds)
        except subprocess.TimeoutExpired:
            return
        finally:
            if child.poll() is not None:
                _LIVE_REVIEW_PROCS.pop(pid, None)
        return
    deadline = time.monotonic() + wait_seconds
    while _pid_alive(pid):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def _review_wait_or_consume(
    adapter: Any,
    ctx: Any,
    spec: Any,
    stage: Any,
    run_dir: Path,
    record: dict,
    model: str,
    *,
    wait_seconds: int,
    expected_cwd: str,
    board: str,
    card_id: str,
    round_n: int,
) -> dict:
    current = _review_consume_or_attach(
        ctx,
        spec,
        stage,
        run_dir,
        record,
        model,
        expected_cwd=expected_cwd,
        board=board,
        card_id=card_id,
        round_n=round_n,
    )
    if current.get("outcome") != "attach" or wait_seconds <= 0:
        return current
    _wait_for_review_process(int(current["pid"]), wait_seconds)
    current_ctx = _prologue(adapter)
    return _review_consume_or_attach(
        current_ctx,
        spec,
        stage,
        run_dir,
        record,
        model,
        expected_cwd=expected_cwd,
        board=board,
        card_id=card_id,
        round_n=round_n,
    )


def _review_relay(
    adapter: Any,
    ctx: Any,
    stage: Any,
    *,
    brief_path: str | None,
    brief_content: str | None,
    repo: Path,
    wait_seconds: Any,
) -> dict:
    ok, reasons = review_authority(adapter, ctx)
    if not ok:
        _fail(
            ctx,
            REVIEW_ROLE_REQUIRED,
            "review authority missing: " + ", ".join(reasons),
            reasons=reasons,
        )
    policy = POLICIES.get(str(stage.stage))
    if policy is None or not policy.review_lane:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"stage {stage.stage!r} has no review lane",
            stage=stage.stage,
        )
    spec = resolve_relay_spec(
        stage=str(stage.stage),
        operation="review",
        coding_agent=str(stage.coding_agent),
        review=True,
    )
    card_id = _card_id(ctx)
    board = _resolve_board(adapter, ctx)
    events = _list_events(adapter, ctx, card_id)
    round_n = review_round_from_events(events)
    run_dir = review_round_run_dir(
        _task_dir(adapter, board, card_id), round_n, ctx.env_run_id, spec.skill
    )
    result_path = run_dir / "result.json"
    record_path = run_dir / "relay.json"
    record = load_json(record_path)
    model = spec.model
    cwd = str(repo)
    bounded_wait = _review_wait_seconds(ctx, wait_seconds)
    if isinstance(record, dict):
        return _review_wait_or_consume(
            adapter,
            ctx,
            spec,
            stage,
            run_dir,
            record,
            model,
            wait_seconds=bounded_wait,
            expected_cwd=cwd,
            board=board,
            card_id=card_id,
            round_n=round_n,
        )
    brief = _resolve_brief_or_fail(
        ctx,
        brief_path=brief_path,
        brief_content=brief_content,
        card_id=card_id,
        dest_dir=run_dir,
    )
    spawned = _review_spawn(
        ctx,
        spec,
        brief=brief,
        repo=cwd,
        run_dir=run_dir,
        result_path=result_path,
        model=model,
        relay_script=Path(adapter.hermes_home) / spec.skill_script_relpath,
    )
    if bounded_wait <= 0:
        return spawned
    record = load_json(record_path)
    if not isinstance(record, dict):
        _fail(ctx, RELAY_ATTEMPT_UNCERTAIN, "review relay record missing after spawn")
    return _review_wait_or_consume(
        adapter,
        ctx,
        spec,
        stage,
        run_dir,
        record,
        model,
        wait_seconds=bounded_wait,
        expected_cwd=cwd,
        board=board,
        card_id=card_id,
        round_n=round_n,
    )


def op_start_or_inspect_relay(
    adapter: Any,
    *,
    brief_path: str | None = None,
    brief_content: str | None = None,
    repo: str | None = None,
    wait_seconds: Any = None,
) -> dict:
    """Derive commissioning and spawn, attach, or consume a Relay (§14, §19.5)."""
    ctx = _prologue(adapter)
    if ctx.role not in {"implement-worker", "review-worker"}:
        _fail(
            ctx,
            IMPLEMENT_ROLE_REQUIRED,
            "Origin commissions workers, not relays; this action requires an "
            f"implement or review worker (role is {ctx.role!r})",
            remediation="dispatch a Worker; do not start Relays from Origin",
        )
    stage, workspace = _worker_card(adapter, ctx)
    if ctx.role == "review-worker":
        return _review_relay(
            adapter,
            ctx,
            stage,
            brief_path=brief_path,
            brief_content=brief_content,
            repo=workspace,
            wait_seconds=wait_seconds,
        )
    if isinstance(brief_content, str) and brief_content.strip():
        _fail(
            ctx,
            BRIEF_MISSING,
            "brief_content is supported on the review lane only; implement "
            "workers author the brief file and pass brief_path",
            rule="review-only",
        )
    return _write_mode_relay(
        adapter, ctx, stage, brief_path=brief_path or "", repo=workspace
    )


# ---------------------------------------------------------------------------
# UI lease
# ---------------------------------------------------------------------------


def op_ui_lease(adapter: Any, *, action: str, resource_id: str) -> dict:
    """Acquire, release, or inspect a named UI acceptance resource (§17.2)."""
    ctx = _prologue(adapter)
    _require_roles(
        ctx,
        "implement-worker",
        code=IMPLEMENT_ROLE_REQUIRED,
        message=(
            "devflow_ui_lease requires an implement worker "
            f"(role is {ctx.role!r})"
        ),
    )
    stage, _workspace = _worker_card(adapter, ctx)
    action_name = (action or "").strip()
    if action_name not in {"acquire", "release", "inspect"}:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"action must be acquire, release, or inspect (got {action!r})",
        )
    board = _resolve_board(adapter, ctx)
    card_id = _card_id(ctx)
    manager = UiLeaseManager(hermes_home=adapter.hermes_home)
    normalized = (resource_id or "").strip().lower()
    if action_name == "inspect":
        found = manager.inspect(resource_id)
        history = [
            rec
            for rec in load_release_history(adapter.hermes_home)
            if rec.get("resource") == normalized
        ]
        if found is None:
            return {
                "ok": True,
                "lease": None,
                "resource_id": resource_id,
                "released": history,
            }
        return {
            "ok": True,
            "resource_id": resource_id,
            "released": history,
            **found,
        }
    guard = _guard_client(adapter, board, card_id)
    landing = _latest_landing(guard.read_state())
    candidate = (
        str(landing["commit"]) if landing and landing.get("commit") else None
    )
    if action_name == "release":
        released = manager.release(
            resource_id, run_id=ctx.env_run_id, candidate_commit=candidate
        )
        return {"ok": True, **released}
    if stage.ui_acceptance != "required":
        _fail(
            ctx,
            UI_ACCEPTANCE_INCOMPLETE,
            "ui_acceptance is not 'required'",
            ui_acceptance=stage.ui_acceptance,
        )
    if not candidate:
        _fail(
            ctx,
            CANDIDATE_NOT_FROZEN,
            "no candidate landing commit is recorded for UI lease acquire",
        )

    def holder_run_is_current(run_id: Any) -> bool:
        conn = None
        try:
            conn = adapter.connect(board=board)
            task = adapter.get_task(conn, card_id)
            current = getattr(task, "current_run_id", None) if task else None
            return current is not None and int(current) == int(run_id)
        except Exception:
            return False
        finally:
            if conn is not None:
                adapter.close(conn)

    lease = manager.acquire(
        resource_id,
        board=board,
        card_id=card_id,
        run_id=ctx.env_run_id,
        candidate_commit=candidate,
        holder_run_is_current=holder_run_is_current,
    )
    return {"ok": True, "lease": lease, "lease_id": lease.get("lease_id")}


# ---------------------------------------------------------------------------
# Implement handoff
# ---------------------------------------------------------------------------


def _require_successful_terminal(
    ctx: Any, spec: Any, last: dict, *, expected_cwd: str
) -> dict:
    result = load_json(last.get("result_path"))
    status = result.get("status") if isinstance(result, dict) else None
    violations = require_successful_relay_result(
        result,
        expected_cwd=expected_cwd,
        expected_mode=_envelope_mode(spec),
        expected_model=_model_for_result(spec, result),
        expected_thinking=spec.thinking,
    )
    if violations:
        _fail(
            ctx,
            RELAY_ATTEMPT_UNCERTAIN,
            _HANDOFF_NON_SUCCESS,
            violations=violations,
            status=status,
            remediation=_non_success_remediation(result, spec),
        )
    assert isinstance(result, dict)
    return result


def _candidate_landing_or_fail(
    ctx: Any, guard: GuardClient, card_id: str
) -> tuple[str, int, dict]:
    state = guard.read_state()
    landing = _latest_landing(state)
    if landing is None or not landing.get("commit"):
        _fail(ctx, CANDIDATE_NOT_FROZEN, "no candidate landing commit is recorded")
    candidate = str(landing["commit"])
    attempt_number = int(landing.get("attempt_number") or 0)
    baseline_head = ((state or {}).get("baseline") or {}).get("head")
    repo = (state or {}).get("repo")
    violations = verify_landing(repo, candidate, card_id, str(baseline_head or ""))
    if violations:
        _fail(
            ctx,
            CANDIDATE_NOT_FROZEN,
            "candidate landing failed verification",
            violations=violations,
            candidate_commit=candidate,
        )
    return candidate, attempt_number, state or {}


def _handoff_spec(stage: Any, last: dict) -> Any:
    operation = last.get("operation") or "execution"
    return resolve_relay_spec(
        stage=str(stage.stage),
        operation=str(operation),
        coding_agent=str(stage.coding_agent),
        review=False,
    )


def op_implement_handoff(
    adapter: Any, *, summary: str, plan_path: str | None = None
) -> dict:
    """Validate then native-complete or request-review (§16.2, §19.7)."""
    ctx = _prologue(adapter)
    _require_roles(
        ctx,
        "implement-worker",
        code=IMPLEMENT_ROLE_REQUIRED,
        message=(
            "devflow_implement_handoff requires an implement worker "
            f"(role is {ctx.role!r})"
        ),
    )
    stage, workspace = _worker_card(adapter, ctx)
    card_id = _card_id(ctx)
    board = _resolve_board(adapter, ctx)
    if not isinstance(summary, str) or not summary.strip():
        _fail(ctx, CARD_CONTRACT_INVALID, "summary is required")
    summary = summary.strip()
    guard = _guard_client(adapter, board, card_id)
    state = guard.read_state()
    cwd = str((state or {}).get("repo") or workspace)
    task_dir_path = _task_dir(adapter, board, card_id)
    conn = _connect(adapter, ctx, board)
    try:
        if stage.stage == "direct":
            last = _require_terminal_attempt(ctx, state)
            spec = _handoff_spec(stage, last)
            result = _require_successful_terminal(ctx, spec, last, expected_cwd=cwd)
            _check_run_or_fail(ctx, guard)
            candidate, attempt_number, state = _candidate_landing_or_fail(
                ctx, guard, card_id
            )
            manifest, manifest_path = _write_manifest(
                adapter=adapter,
                board=board,
                card_id=card_id,
                stage=stage,
                candidate=candidate,
                baseline_head=str((state.get("baseline") or {}).get("head") or ""),
                implement_run_id=int(ctx.env_run_id),
                attempt_number=attempt_number,
            )
            _require_ui_pass(
                ctx,
                adapter,
                stage,
                task_dir_path,
                candidate=candidate,
                manifest=manifest,
                attempt_number=attempt_number,
                plan=None,
                relay_session_id=_session_of(last, result),
            )
            _manual_verdict_or_fail(adapter, ctx, conn, card_id, stage, candidate)
            _recheck_ownership(adapter, ctx, conn, card_id)
            ok = adapter.complete_task(
                conn,
                card_id,
                summary=summary,
                metadata={
                    "candidate": {
                        "commit": candidate,
                        "manifest_path": manifest_path,
                        "attempt_number": attempt_number,
                    },
                    "handoff": "devflow",
                },
                expected_run_id=ctx.env_run_id,
            )
            if ok is not True:
                _fail(
                    ctx,
                    RUN_OWNERSHIP_LOST,
                    "native complete_task refused the handoff",
                )
            fresh = adapter.get_task(conn, card_id)
            kinds = _event_kinds(adapter, conn, card_id)
            if fresh is None or fresh.status != "done" or "completed" not in kinds:
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    "complete read-back failed",
                    status=getattr(fresh, "status", None),
                    events=kinds,
                )
            return {
                "ok": True,
                "task_id": card_id,
                "status": fresh.status,
                "handoff": "complete",
                "candidate_commit": candidate,
                "manifest_path": manifest_path,
            }

        if stage.stage == "write-plan":
            last = _require_terminal_attempt(ctx, state, operations=("planning", "rework"))
            spec = _handoff_spec(stage, last)
            _require_successful_terminal(ctx, spec, last, expected_cwd=cwd)
            if not isinstance(plan_path, str) or not plan_path.strip():
                _fail(
                    ctx,
                    CARD_CONTRACT_INVALID,
                    "plan_path is required for write-plan handoff",
                )
            plan = Path(plan_path).expanduser()
            if not plan.is_file() or plan.stat().st_size == 0:
                _fail(
                    ctx,
                    CARD_CONTRACT_INVALID,
                    f"plan_path is missing or empty: {plan}",
                    path=str(plan),
                )
            plan = plan.resolve()
            digest = sha256_file(plan)
            if not digest:
                _fail(
                    ctx,
                    CARD_CONTRACT_INVALID,
                    f"plan_path could not be hashed: {plan}",
                    path=str(plan),
                )
            _check_run_or_fail(ctx, guard)
            _recheck_ownership(adapter, ctx, conn, card_id)
            requested = adapter.request_review(
                conn,
                card_id,
                summary=summary,
                metadata={
                    "accepted_plan": {
                        "card_id": card_id,
                        "path": str(plan),
                        "sha256": digest,
                    }
                },
                expected_run_id=ctx.env_run_id,
            )
            if requested is not True:
                _fail(
                    ctx,
                    RUN_OWNERSHIP_LOST,
                    "native request_review refused the handoff",
                )
            fresh = adapter.get_task(conn, card_id)
            kinds = _event_kinds(adapter, conn, card_id)
            if (
                fresh is None
                or fresh.status != "review"
                or "review_requested" not in kinds
            ):
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    "request_review read-back failed",
                    status=getattr(fresh, "status", None),
                    events=kinds,
                )
            return {
                "ok": True,
                "task_id": card_id,
                "status": fresh.status,
                "handoff": "request_review",
                "accepted_plan": {
                    "card_id": card_id,
                    "path": str(plan),
                    "sha256": digest,
                },
            }

        if stage.stage == "execute-plan":
            amendment = _plan_invalidated(adapter, conn, card_id)
            if amendment is not None:
                _fail(
                    ctx,
                    PLAN_IDENTITY_MISSING,
                    _PLAN_INVALIDATED_MSG,
                    amendment=amendment,
                )
            last = _require_terminal_attempt(
                ctx, state, operations=("execution", "rework")
            )
            spec = _handoff_spec(stage, last)
            result = _require_successful_terminal(ctx, spec, last, expected_cwd=cwd)
            expected = _plan_path(stage.accepted_plan)
            if not expected:
                _fail(
                    ctx,
                    AUTO_HANDOFF_INVALID,
                    "accepted plan path is missing for Auto Handoff verification",
                )
            verify_auto_handoff_result(
                result,
                expected_plan_path=expected,
                out_dir=str(last.get("out_dir") or ""),
            )
            live_sha = sha256_file(expected)
            expected_sha = _plan_sha(stage.accepted_plan)
            if live_sha != expected_sha:
                _fail(
                    ctx,
                    PLAN_SHA_MISMATCH,
                    "accepted plan sha256 does not match the file on disk",
                    expected=expected_sha,
                    actual=live_sha,
                    path=expected,
                )
            _check_run_or_fail(ctx, guard)
            candidate, attempt_number, state = _candidate_landing_or_fail(
                ctx, guard, card_id
            )
            manifest, manifest_path = _write_manifest(
                adapter=adapter,
                board=board,
                card_id=card_id,
                stage=stage,
                candidate=candidate,
                baseline_head=str((state.get("baseline") or {}).get("head") or ""),
                implement_run_id=int(ctx.env_run_id),
                attempt_number=attempt_number,
            )
            _require_ui_pass(
                ctx,
                adapter,
                stage,
                task_dir_path,
                candidate=candidate,
                manifest=manifest,
                attempt_number=attempt_number,
                plan=stage.accepted_plan if isinstance(stage.accepted_plan, dict) else None,
                relay_session_id=_session_of(last, result),
            )
            _manual_verdict_or_fail(adapter, ctx, conn, card_id, stage, candidate)
            round_n = review_round_from_events(
                adapter.list_events(conn, card_id) or []
            )
            _recheck_ownership(adapter, ctx, conn, card_id)
            requested = adapter.request_review(
                conn,
                card_id,
                summary=summary,
                metadata={
                    "candidate": {
                        "commit": candidate,
                        "manifest_path": manifest_path,
                        "attempt_number": attempt_number,
                    },
                    "accepted_plan_sha256": expected_sha,
                    "round": round_n,
                },
                expected_run_id=ctx.env_run_id,
            )
            if requested is not True:
                _fail(
                    ctx,
                    RUN_OWNERSHIP_LOST,
                    "native request_review refused the handoff",
                )
            fresh = adapter.get_task(conn, card_id)
            kinds = _event_kinds(adapter, conn, card_id)
            if (
                fresh is None
                or fresh.status != "review"
                or "review_requested" not in kinds
            ):
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    "request_review read-back failed",
                    status=getattr(fresh, "status", None),
                    events=kinds,
                )
            return {
                "ok": True,
                "task_id": card_id,
                "status": fresh.status,
                "handoff": "request_review",
                "candidate_commit": candidate,
                "manifest_path": manifest_path,
                "round": round_n,
            }

        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"unsupported stage for implement handoff: {stage.stage!r}",
        )
    finally:
        adapter.close(conn)


# ---------------------------------------------------------------------------
# Review verdict
# ---------------------------------------------------------------------------


def _round_limit_authorized(
    adapter: Any,
    conn: Any,
    *,
    card_id: str,
    round_n: int,
    candidate: str | None,
) -> bool:
    authorized = False
    for comment in adapter.list_comments(conn, card_id) or []:
        parsed = parse_decision_comment(getattr(comment, "body", None) or "")
        if not isinstance(parsed, dict):
            continue
        if parsed.get("kind") != "round-authorization":
            continue
        if parsed.get("round") != round_n:
            continue
        if candidate is not None and parsed.get("candidate_commit") != candidate:
            continue
        authorized = True
        break
    if not authorized:
        return False
    if candidate is None:
        return True
    metas = handoff_metadata_from_runs(adapter.list_runs(conn, card_id) or [])
    if len(metas) < 2:
        return False
    prior = metas[1] if isinstance(metas[1], dict) else {}
    prior_candidate = None
    nested = prior.get("candidate")
    if isinstance(nested, dict):
        prior_candidate = nested.get("commit")
    prior_candidate = prior_candidate or prior.get("candidate_commit")
    return bool(candidate and prior_candidate and candidate != prior_candidate)


def _load_harness_review_evidence(
    ctx: Any,
    adapter: Any,
    board: str,
    card_id: str,
    stage: Any,
    round_n: int,
) -> tuple[dict, str]:
    policy = POLICIES.get(str(stage.stage))
    skill = getattr(policy, "review_skill", None) if policy is not None else None
    if not skill:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"stage {stage.stage!r} has no review skill",
            stage=stage.stage,
        )
    dest_dir = _task_dir(adapter, board, card_id)
    data = load_review_evidence(
        dest_dir, round=round_n, run_id=int(ctx.env_run_id), skill=str(skill)
    )
    if not isinstance(data, dict):
        _fail(
            ctx,
            REVIEW_GATE_INCOMPLETE,
            "no harness review evidence for the current review run — run "
            "devflow_start_or_inspect_relay first",
        )
    path = str(
        review_round_run_dir(dest_dir, round_n, ctx.env_run_id, str(skill))
        / REVIEW_EVIDENCE_FILENAME
    )
    return data, path


def _bind_execute_review(
    ctx: Any,
    data: dict,
    *,
    card_id: str,
    round_n: int,
    candidate: str | None,
    accepted_sha: str | None,
) -> None:
    mismatches: dict[str, Any] = {}
    if data.get("card_id") != card_id:
        mismatches["card_id"] = {"expected": card_id, "actual": data.get("card_id")}
    if data.get("review_run_id") != ctx.env_run_id:
        mismatches["review_run_id"] = {
            "expected": ctx.env_run_id,
            "actual": data.get("review_run_id"),
        }
    if data.get("round") != round_n:
        mismatches["round"] = {"expected": round_n, "actual": data.get("round")}
    if data.get("candidate_commit") != candidate:
        mismatches["candidate_commit"] = {
            "expected": candidate,
            "actual": data.get("candidate_commit"),
        }
    if data.get("accepted_plan_sha256") != accepted_sha:
        mismatches["accepted_plan_sha256"] = {
            "expected": accepted_sha,
            "actual": data.get("accepted_plan_sha256"),
        }
    if mismatches:
        _fail(
            ctx,
            EVIDENCE_IDENTITY_MISMATCH,
            "execute review identity does not match the current candidate/run",
            fields=mismatches,
        )


def op_review_verdict(
    adapter: Any,
    *,
    verdict: str,
    reason: str | None = None,
    findings_ref: str | None = None,
    block_kind: str | None = None,
) -> dict:
    """Managed pass / revise / blocked with exactly one native action (§18.3, §19.8)."""
    ctx = _prologue(adapter)
    if ctx.role == "implement-worker":
        _fail(
            ctx,
            IMPLEMENT_ROLE_REQUIRED,
            "devflow_review_verdict is a review-worker tool "
            f"(role is {ctx.role!r})",
        )
    _require_roles(
        ctx,
        "review-worker",
        code=REVIEW_ROLE_REQUIRED,
        message=(
            "devflow_review_verdict requires a review worker "
            f"(role is {ctx.role!r})"
        ),
    )
    ok, reasons = review_authority(adapter, ctx)
    if not ok:
        _fail(
            ctx,
            REVIEW_ROLE_REQUIRED,
            "review authority missing: " + ", ".join(reasons),
            reasons=reasons,
        )
    stage, _workspace = _worker_card(adapter, ctx)
    card_id = _card_id(ctx)
    board = _resolve_board(adapter, ctx)
    verdict_name = (verdict or "").strip()
    if verdict_name not in {"pass", "revise", "blocked"}:
        _fail(
            ctx,
            CARD_CONTRACT_INVALID,
            f"verdict must be pass, revise, or blocked (got {verdict!r})",
        )
    if verdict_name == "blocked":
        if block_kind not in BLOCK_KINDS:
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                "blocked requires block_kind "
                f"(one of {list(BLOCK_KINDS)}; got {block_kind!r})",
            )
    conn = _connect(adapter, ctx, board)
    try:
        events = list(adapter.list_events(conn, card_id) or [])
        round_n = review_round_from_events(events)
        guard = _guard_client(adapter, board, card_id)
        landing = _latest_landing(guard.read_state())
        candidate = str(landing["commit"]) if landing and landing.get("commit") else None
        if round_n > MAX_REVIEW_ROUNDS:
            if not _round_limit_authorized(
                adapter,
                conn,
                card_id=card_id,
                round_n=round_n,
                candidate=candidate,
            ):
                _fail(
                    ctx,
                    ROUND_LIMIT_REACHED,
                    f"review round {round_n} exceeds MAX_REVIEW_ROUNDS="
                    f"{MAX_REVIEW_ROUNDS} without Origin round-authorization "
                    "and a changed candidate",
                    round=round_n,
                    max_review_rounds=MAX_REVIEW_ROUNDS,
                )

        if verdict_name == "pass":
            data, result_path = _load_harness_review_evidence(
                ctx, adapter, board, card_id, stage, round_n
            )
            if stage.stage == "write-plan":
                violations = validate_plan_review(data)
                if violations or data.get("schema") != PLAN_REVIEW_SCHEMA_ID:
                    _fail(
                        ctx,
                        REVIEW_GATE_INCOMPLETE,
                        "write-plan review evidence failed contract validation",
                        violations=violations,
                    )
                if data.get("verdict") != "pass":
                    _fail(
                        ctx,
                        REVIEW_GATE_INCOMPLETE,
                        "write-plan review result verdict must be 'pass'",
                        verdict=data.get("verdict"),
                    )
                if data.get("round") != round_n:
                    _fail(
                        ctx,
                        EVIDENCE_IDENTITY_MISMATCH,
                        "plan review round does not match the derived round",
                        expected=round_n,
                        actual=data.get("round"),
                    )
                plan = data.get("plan")
                if not isinstance(plan, dict):
                    _fail(
                        ctx,
                        REVIEW_GATE_INCOMPLETE,
                        "write-plan review result must include plan.path and plan.sha256",
                    )
                path_raw = plan.get("path")
                expected_sha = plan.get("sha256")
                if not isinstance(path_raw, str) or not path_raw:
                    _fail(
                        ctx,
                        REVIEW_GATE_INCOMPLETE,
                        "write-plan review result plan.path is missing",
                    )
                actual = sha256_file(path_raw)
                if actual != expected_sha:
                    _fail(
                        ctx,
                        PLAN_SHA_MISMATCH,
                        "write-plan review result sha256 does not match the plan file",
                        expected=expected_sha,
                        actual=actual,
                        path=path_raw,
                    )
                summary = reason or "review pass"
                ok = adapter.complete_task(
                    conn,
                    card_id,
                    summary=summary,
                    metadata={
                        "accepted_plan": {
                            "card_id": card_id,
                            "path": path_raw,
                            "sha256": expected_sha,
                        },
                        "review": {"path": result_path, "round": round_n},
                    },
                    expected_run_id=ctx.env_run_id,
                )
                if ok is not True:
                    _fail(
                        ctx,
                        RUN_OWNERSHIP_LOST,
                        "native complete_task refused the review pass",
                    )
                fresh = adapter.get_task(conn, card_id)
                kinds = _event_kinds(adapter, conn, card_id)
                if fresh is None or fresh.status != "done" or "completed" not in kinds:
                    _fail(
                        ctx,
                        HARNESS_STATE_UNAVAILABLE,
                        "complete read-back failed",
                        status=getattr(fresh, "status", None),
                    )
                return {
                    "ok": True,
                    "task_id": card_id,
                    "status": fresh.status,
                    "verdict": "pass",
                    "round": round_n,
                    "accepted_plan": {
                        "card_id": card_id,
                        "path": path_raw,
                        "sha256": expected_sha,
                    },
                }

            if stage.stage == "execute-plan":
                violations = validate_execute_review(data)
                if violations:
                    _fail(
                        ctx,
                        REVIEW_GATE_INCOMPLETE,
                        "execute review result failed contract validation",
                        violations=violations,
                    )
                if candidate is None:
                    _fail(
                        ctx,
                        CANDIDATE_NOT_FROZEN,
                        "no candidate landing commit is recorded for execute review",
                    )
                _bind_execute_review(
                    ctx,
                    data,
                    card_id=card_id,
                    round_n=round_n,
                    candidate=candidate,
                    accepted_sha=_plan_sha(stage.accepted_plan),
                )
                if stage.ui_acceptance == "required":
                    manifests = [
                        item
                        for item in load_candidate_manifests(
                            _task_dir(adapter, board, card_id)
                        )
                        if item.get("candidate_commit") == candidate
                    ]
                    if not manifests:
                        _fail(
                            ctx,
                            CANDIDATE_NOT_FROZEN,
                            "candidate manifest is missing for UI evidence binding",
                            candidate_commit=candidate,
                        )
                    attempt_number = int(manifests[0].get("attempt_number") or 0)
                    landing_attempt = _find_attempt(
                        guard.read_state(), attempt_number
                    ) or _latest_attempt(guard.read_state())
                    _require_ui_pass(
                        ctx,
                        adapter,
                        stage,
                        _task_dir(adapter, board, card_id),
                        candidate=candidate,
                        manifest=manifests[0],
                        attempt_number=attempt_number,
                        plan=stage.accepted_plan
                        if isinstance(stage.accepted_plan, dict)
                        else None,
                        relay_session_id=_session_of(landing_attempt),
                    )
                summary = reason or "review pass"
                ok = adapter.complete_task(
                    conn,
                    card_id,
                    summary=summary,
                    metadata={
                        "review": {"path": result_path, "round": round_n},
                        "candidate": {"commit": candidate},
                    },
                    expected_run_id=ctx.env_run_id,
                )
                if ok is not True:
                    _fail(
                        ctx,
                        RUN_OWNERSHIP_LOST,
                        "native complete_task refused the review pass",
                    )
                fresh = adapter.get_task(conn, card_id)
                kinds = _event_kinds(adapter, conn, card_id)
                if fresh is None or fresh.status != "done" or "completed" not in kinds:
                    _fail(
                        ctx,
                        HARNESS_STATE_UNAVAILABLE,
                        "complete read-back failed",
                        status=getattr(fresh, "status", None),
                    )
                return {
                    "ok": True,
                    "task_id": card_id,
                    "status": fresh.status,
                    "verdict": "pass",
                    "round": round_n,
                    "candidate_commit": candidate,
                }

            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                f"stage {stage.stage!r} does not support a review pass",
            )

        if verdict_name == "revise":
            text = (reason or findings_ref or "").strip()
            if not text:
                _fail(
                    ctx,
                    CARD_CONTRACT_INVALID,
                    "revise requires reason or findings_ref",
                )
            if stage.stage == "execute-plan":
                data, _path = _load_harness_review_evidence(
                    ctx, adapter, board, card_id, stage, round_n
                )
                violations = validate_execute_review(data)
                if violations:
                    _fail(
                        ctx,
                        REVIEW_GATE_INCOMPLETE,
                        "execute review result failed contract validation",
                        violations=violations,
                    )
                overall = (data.get("overall") or {}).get("verdict")
                if overall != "revise":
                    _fail(
                        ctx,
                        REVIEW_GATE_INCOMPLETE,
                        "execute review overall/gates are not consistent with revise",
                        overall=overall,
                    )
                _bind_execute_review(
                    ctx,
                    data,
                    card_id=card_id,
                    round_n=round_n,
                    candidate=candidate,
                    accepted_sha=_plan_sha(stage.accepted_plan),
                )
            returned = adapter.request_changes(
                conn,
                card_id,
                reason=text,
                expected_run_id=ctx.env_run_id,
            )
            ok = returned[0] if isinstance(returned, tuple) else returned
            info = returned[1] if isinstance(returned, tuple) and len(returned) > 1 else None
            if not ok:
                _fail(
                    ctx,
                    RUN_OWNERSHIP_LOST,
                    "native request_changes refused the revise verdict",
                    info=info,
                )
            fresh = adapter.get_task(conn, card_id)
            kinds = _event_kinds(adapter, conn, card_id)
            if fresh is None or "changes_requested" not in kinds:
                _fail(
                    ctx,
                    HARNESS_STATE_UNAVAILABLE,
                    "request_changes read-back failed",
                    status=getattr(fresh, "status", None),
                )
            return {
                "ok": True,
                "task_id": card_id,
                "status": fresh.status,
                "verdict": "revise",
                "round": round_n,
                "implementer": info,
            }

        block_reason = (reason or "").strip()
        if not block_reason:
            _fail(
                ctx,
                CARD_CONTRACT_INVALID,
                "blocked requires a genuine typed-blocker reason",
            )
        blocked = adapter.block_task(
            conn,
            card_id,
            reason=block_reason,
            kind=block_kind,
            expected_run_id=ctx.env_run_id,
        )
        if blocked is not True:
            _fail(
                ctx,
                RUN_OWNERSHIP_LOST,
                "native block_task refused the blocked verdict",
            )
        fresh = adapter.get_task(conn, card_id)
        kinds = _event_kinds(adapter, conn, card_id)
        if fresh is None or "blocked" not in kinds:
            _fail(
                ctx,
                HARNESS_STATE_UNAVAILABLE,
                "block read-back failed",
                status=getattr(fresh, "status", None),
                events=kinds,
            )
        return {
            "ok": True,
            "task_id": card_id,
            "status": fresh.status,
            "verdict": "blocked",
            "block_kind": block_kind,
            "round": round_n,
        }
    finally:
        adapter.close(conn)
