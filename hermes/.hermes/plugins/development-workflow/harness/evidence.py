"""Plan, candidate, review, UI, and relay evidence binding (design §9.3–9.4, §14.4, §16, §18.3).

Pure disk/git helpers. Artifacts are evidence, not scheduling state: files are
parsed and identity-checked; presence alone is not a Gate PASS.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import contracts as _contracts
from .contracts import (
    EXECUTE_REVIEW_SCHEMA_ID,
    PLAN_REVIEW_SCHEMA_ID,
    validate_candidate_manifest,
    validate_execute_review,
    validate_plan_review,
    validate_ui_evidence,
)
from .errors import (
    AUTO_HANDOFF_INVALID,
    CANDIDATE_CHANGED,
    CANDIDATE_NOT_FROZEN,
    EVIDENCE_IDENTITY_MISMATCH,
    PLAN_IDENTITY_MISSING,
    PLAN_SHA_MISMATCH,
    HarnessError,
)

RELAY_RESULT_SCHEMA = "delegate-relay.result.v1"
RELAY_RESULT_STATUSES = (
    "completed",
    "failed",
    "timeout",
    "aborted",
    "unavailable",
)
KANBAN_TASK_TRAILER_PREFIX = "Kanban-Task: "
REVIEW_EVIDENCE_FILENAME = "review-evidence.json"
_FALLBACK_MARKERS = (
    "quota",
    "rate limit",
    "ratelimit",
    "provider",
    "429",
    "insufficient",
    "balance",
    "overloaded",
)
_IDENTITY_FIELDS = ("board", "card_id", "feature_id", "review_run_id", "round")


def task_dir(artifacts_root, board: str, card_id: str) -> Path:
    return Path(artifacts_root) / board / "tasks" / card_id


def relay_attempt_dir(task_dir_path: Path, attempt: int) -> Path:
    return Path(task_dir_path) / "relay" / f"attempt-{int(attempt)}"


def candidate_dir(task_dir_path: Path, commit_sha: str) -> Path:
    return Path(task_dir_path) / "candidates" / str(commit_sha)


def reviews_dir(task_dir_path: Path) -> Path:
    return Path(task_dir_path) / "reviews"


def review_round_run_dir(
    task_dir_path: Path, round: int, run_id, skill: str
) -> Path:
    return (
        reviews_dir(task_dir_path)
        / f"round-{int(round)}"
        / f"run-{run_id}"
        / str(skill)
    )


def ui_dir(task_dir_path: Path, commit_sha: str, run_id) -> Path:
    return Path(task_dir_path) / "ui" / str(commit_sha) / str(run_id)


def sha256_file(path) -> str | None:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def load_json(path) -> Any | None:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def write_json_atomic(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=".devflow-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def verify_plan_identity(accepted_plan: dict) -> dict:
    """Return ``{path, sha256, size}`` for a live Accepted Plan file.

    Missing/empty identity raises ``PLAN_IDENTITY_MISSING``. A present file
    whose digest does not match raises ``PLAN_SHA_MISMATCH``.
    """
    if not isinstance(accepted_plan, dict):
        raise HarnessError(
            PLAN_IDENTITY_MISSING,
            "accepted plan identity is missing",
        )
    path_raw = accepted_plan.get("path")
    expected = accepted_plan.get("sha256")
    if not isinstance(path_raw, str) or not path_raw.strip():
        raise HarnessError(
            PLAN_IDENTITY_MISSING,
            "accepted plan path is missing or empty",
        )
    if not isinstance(expected, str) or not expected.strip():
        raise HarnessError(
            PLAN_IDENTITY_MISSING,
            "accepted plan sha256 is missing or empty",
        )
    path = Path(path_raw)
    try:
        size = path.stat().st_size
    except OSError:
        raise HarnessError(
            PLAN_IDENTITY_MISSING,
            f"accepted plan file is missing: {path}",
            path=str(path),
        ) from None
    if not path.is_file() or size == 0:
        raise HarnessError(
            PLAN_IDENTITY_MISSING,
            f"accepted plan file is missing or empty: {path}",
            path=str(path),
        )
    actual = sha256_file(path)
    if actual is None:
        raise HarnessError(
            PLAN_IDENTITY_MISSING,
            f"accepted plan file is unreadable: {path}",
            path=str(path),
        )
    if actual != expected:
        raise HarnessError(
            PLAN_SHA_MISMATCH,
            "accepted plan sha256 does not match the file on disk",
            expected=expected,
            actual=actual,
            path=str(path),
        )
    return {"path": str(path), "sha256": actual, "size": size}


def git(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def resolve_commit(repo, ref: str) -> str | None:
    proc = git(repo, "rev-parse", f"{ref}^{{commit}}")
    sha = proc.stdout.strip()
    if proc.returncode != 0 or not sha:
        return None
    return sha


def commit_message_has_trailer(repo, sha: str, card_id: str) -> bool:
    proc = git(repo, "show", "-s", "--format=%B", sha)
    if proc.returncode != 0:
        return False
    trailer = f"{KANBAN_TASK_TRAILER_PREFIX}{card_id}"
    return trailer in proc.stdout.splitlines()


def verify_landing(
    repo, commit_sha: str, card_id: str, baseline_head: str
) -> list[str]:
    """Return violation strings; empty means the landing commit is acceptable."""
    violations: list[str] = []
    resolved = resolve_commit(repo, commit_sha)
    if resolved is None:
        violations.append("commit-unresolvable")
        return violations
    if not commit_message_has_trailer(repo, resolved, card_id):
        violations.append("trailer-missing")
    ancestry = git(repo, "merge-base", "--is-ancestor", baseline_head, resolved)
    if ancestry.returncode != 0:
        violations.append("commit-pre-baseline")
    return violations


def write_candidate_manifest(task_dir_path: Path, manifest: dict) -> dict:
    violations = validate_candidate_manifest(manifest)
    if violations:
        raise HarnessError(
            CANDIDATE_NOT_FROZEN,
            "candidate manifest is not a valid development-candidate.v1",
            violations=violations,
        )
    dest = candidate_dir(task_dir_path, manifest["candidate_commit"]) / "candidate.json"
    return _write_immutable_json(
        dest,
        manifest,
        code=CANDIDATE_CHANGED,
        message="candidate manifest already exists with different content",
        expected=_manifest_summary(manifest),
        existing_summary=_manifest_summary,
    )


def load_candidate_manifests(task_dir_path: Path) -> list[dict]:
    root = Path(task_dir_path) / "candidates"
    if not root.is_dir():
        return []
    found: list[dict] = []
    for entry in root.iterdir():
        data = load_json(entry / "candidate.json")
        if not isinstance(data, dict):
            continue
        if validate_candidate_manifest(data):
            continue
        found.append(data)
    found.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return found


def load_execute_reviews(task_dir_path: Path) -> list[dict]:
    root = reviews_dir(task_dir_path)
    found: list[dict] = []
    for path in _json_files(root):
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        if validate_execute_review(data):
            continue
        item = dict(data)
        item["_path"] = str(path)
        found.append(item)
    found.sort(key=_execute_review_sort_key, reverse=True)
    return found


def load_ui_evidence(task_dir_path: Path, candidate_commit: str) -> list[dict]:
    """Load v2 UI evidence for ``candidate_commit``. v1 files are skipped."""
    root = Path(task_dir_path) / "ui" / str(candidate_commit)
    found: list[dict] = []
    for path in _json_files(root):
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        if validate_ui_evidence(data):
            continue
        if data.get("candidate_commit") != candidate_commit:
            continue
        item = dict(data)
        item["_path"] = str(path)
        found.append(item)
    found.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return found


def write_review_evidence(run_dir: Path, evidence: dict) -> dict:
    dest = Path(run_dir) / REVIEW_EVIDENCE_FILENAME
    return _write_immutable_json(
        dest,
        evidence,
        code=EVIDENCE_IDENTITY_MISMATCH,
        message="review evidence already exists with different content",
        expected=_review_summary(evidence),
        existing_summary=_review_summary,
    )


def load_review_evidence(
    task_dir: Path, *, round: int, run_id: int, skill: str
) -> dict | None:
    dest = (
        review_round_run_dir(task_dir, round, run_id, skill)
        / REVIEW_EVIDENCE_FILENAME
    )
    data = load_json(dest)
    return data if isinstance(data, dict) else None


def require_successful_relay_result(
    result,
    *,
    expected_cwd: str,
    expected_mode: str,
    expected_model: str,
    expected_thinking: str,
    require_final_message: bool = False,
) -> list[str]:
    """Strict successful-relay gate on a ``delegate-relay.result.v1`` envelope."""
    violations = validate_relay_result(result)
    if not isinstance(result, dict):
        return violations
    status = result.get("status")
    if status != "completed":
        violations.append(f"status must be 'completed' (got {status!r})")
    if "exitCode" not in result:
        violations.append("exitCode is required and must be 0")
    else:
        code = result.get("exitCode")
        if not isinstance(code, int) or isinstance(code, bool) or code != 0:
            violations.append(f"exitCode must be 0 (got {code!r})")
    session = result.get("sessionId")
    if not isinstance(session, str) or not session.strip():
        violations.append(
            f"sessionId must be a non-empty string (got {session!r})"
        )
    cwd = result.get("cwd")
    if cwd != expected_cwd:
        violations.append(
            f"cwd must be {expected_cwd!r} (got {cwd!r})"
        )
    mode = result.get("mode")
    if mode != expected_mode:
        violations.append(
            f"mode must be {expected_mode!r} (got {mode!r})"
        )
    requested = result.get("requestedModel")
    if requested != expected_model:
        violations.append(
            f"requestedModel must be {expected_model!r} (got {requested!r})"
        )
    resolved = result.get("resolvedModel")
    if not isinstance(resolved, str) or not resolved.strip():
        violations.append(
            f"resolvedModel must be a non-empty string (got {resolved!r})"
        )
    thinking = result.get("thinking")
    if thinking != expected_thinking:
        violations.append(
            f"thinking must be {expected_thinking!r} (got {thinking!r})"
        )
    if require_final_message:
        final = result.get("finalMessage")
        if not isinstance(final, str) or not final.strip():
            violations.append(
                f"finalMessage must be a non-empty string (got {final!r})"
            )
    return violations


def fallback_eligible(result) -> bool:
    """True only for a failed provider/quota relay that may retry another model."""
    if not isinstance(result, dict):
        return False
    if result.get("status") == "unavailable":
        return False
    if result.get("sourceStatus") == "pi_unavailable":
        return False
    if result.get("status") != "failed":
        return False
    blob = _relay_error_blob(result).lower()
    return any(marker in blob for marker in _FALLBACK_MARKERS)


def extract_review_report(final_message: str) -> dict:
    """Parse one JSON/YAML review document from a relay ``finalMessage``."""
    if not isinstance(final_message, str):
        raise ValueError(
            f"final_message must be a string (got {type(final_message).__name__})"
        )
    text = _strip_one_markdown_fence(final_message)
    if not text:
        raise ValueError("review report is empty")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _load_strict_yaml(text)
    if not isinstance(data, dict):
        raise ValueError(
            f"review report must be a mapping (got {type(data).__name__})"
        )
    return data


def normalize_plan_review(
    report: dict,
    *,
    board: str,
    card_id: str,
    feature_id: str,
    review_run_id: int,
    round: int,
) -> dict:
    """Map a review-plan YAML document into harness ``development-plan-review.v1``."""
    _raise_identity_mismatch(
        report,
        board=board,
        card_id=card_id,
        feature_id=feature_id,
        review_run_id=review_run_id,
        round=round,
    )
    plan = report.get("plan") if isinstance(report.get("plan"), dict) else {}
    revisions = report.get("required_revisions")
    if revisions is None:
        revisions = []
    evidence = {
        "schema": PLAN_REVIEW_SCHEMA_ID,
        "board": board,
        "card_id": card_id,
        "feature_id": feature_id,
        "review_run_id": review_run_id,
        "round": round,
        "plan": {"path": plan.get("path"), "sha256": plan.get("sha256")},
        "verdict": report.get("verdict"),
        "summary": report.get("summary"),
        "required_revisions": revisions,
    }
    violations = validate_plan_review(evidence)
    if violations:
        raise ValueError("; ".join(violations))
    return evidence


def normalize_execute_review(
    report: dict,
    *,
    board: str,
    card_id: str,
    feature_id: str,
    review_run_id: int,
    round: int,
) -> dict:
    """Map a review-execute YAML document into harness execute-review JSON."""
    _raise_identity_mismatch(
        report,
        board=board,
        card_id=card_id,
        feature_id=feature_id,
        review_run_id=review_run_id,
        round=round,
    )
    accepted = report.get("accepted_plan")
    accepted_sha = (
        accepted.get("sha256") if isinstance(accepted, dict) else None
    )
    overall_raw = report.get("overall")
    if isinstance(overall_raw, dict):
        overall_verdict = overall_raw.get("verdict")
    else:
        overall_verdict = overall_raw
    evidence = {
        "schema": EXECUTE_REVIEW_SCHEMA_ID,
        "card_id": card_id,
        "review_run_id": review_run_id,
        "round": round,
        "candidate_commit": report.get("candidate_commit"),
        "accepted_plan_sha256": accepted_sha,
        "patch_gate": _gate_subset(report.get("patch_gate")),
        "plan_conformance_gate": _gate_subset(report.get("plan_conformance_gate")),
        "overall": {"verdict": overall_verdict},
    }
    violations = validate_execute_review(evidence)
    if violations:
        raise ValueError("; ".join(violations))
    return evidence


def verify_ui_evidence_binding(
    ev: dict,
    *,
    manifest: dict,
    card,
    run_id: int,
    attempt_number: int,
    plan: dict | None,
    relay_session_id: str | None = None,
    lease_records: list[dict] | None = None,
) -> list[str]:
    """Bind UI evidence v2 to the current candidate, card, run, and lease."""
    violations = validate_ui_evidence(ev)
    if not isinstance(ev, dict):
        return violations
    _bind_equal(violations, "board", ev.get("board"), manifest.get("board"))
    _bind_equal(violations, "card_id", ev.get("card_id"), manifest.get("card_id"))
    feature_id = getattr(card, "feature_id", None)
    _bind_equal(violations, "feature_id", ev.get("feature_id"), manifest.get("feature_id"))
    if feature_id is not None:
        _bind_equal(violations, "feature_id", ev.get("feature_id"), feature_id)
    stage = getattr(card, "stage", None)
    _bind_equal(violations, "stage", ev.get("stage"), manifest.get("stage"))
    if stage is not None:
        _bind_equal(violations, "stage", ev.get("stage"), stage)
    _bind_equal(violations, "run_id", ev.get("run_id"), run_id)
    _bind_equal(violations, "attempt_number", ev.get("attempt_number"), attempt_number)
    for key in ("candidate_commit", "diff_base", "diff_head"):
        _bind_equal(violations, key, ev.get(key), manifest.get(key))
    expected_plan = plan
    if expected_plan is None:
        card_plan = getattr(card, "accepted_plan", None)
        expected_plan = card_plan if card_plan is not None else manifest.get("accepted_plan")
    if not _same_plan_identity(ev.get("accepted_plan"), expected_plan):
        violations.append(
            "accepted_plan identity does not match the current card/manifest "
            f"(got {ev.get('accepted_plan')!r}, expected {_plan_pair(expected_plan)!r})"
        )
    if relay_session_id is not None:
        actual_session = ev.get("relay_session_id")
        if not isinstance(actual_session, str) or not actual_session.strip():
            violations.append(
                "relay_session_id must be a non-empty string when the "
                f"producing attempt has a session (got {actual_session!r})"
            )
        elif actual_session != relay_session_id:
            violations.append(
                "relay_session_id does not match the producing attempt "
                f"(got {actual_session!r}, expected {relay_session_id!r})"
            )
    if lease_records is not None:
        violations.extend(_bind_lease_record(ev, lease_records))
    return violations


def validate_relay_result(data: Any) -> list[str]:
    """Structural checks for ``delegate-relay.result.v1`` (design §14.3–14.4)."""
    if not isinstance(data, dict):
        return [f"relay result must be a mapping (got {type(data).__name__})"]
    violations: list[str] = []
    schema = data.get("schema")
    if schema != RELAY_RESULT_SCHEMA:
        violations.append(
            f"schema must be {RELAY_RESULT_SCHEMA!r} (got {schema!r})"
        )
    status = data.get("status")
    if status not in RELAY_RESULT_STATUSES:
        violations.append(
            "status must be one of "
            f"{list(RELAY_RESULT_STATUSES)} (got {status!r})"
        )
    if "exitCode" in data and data["exitCode"] is not None:
        code = data["exitCode"]
        if not isinstance(code, int) or isinstance(code, bool):
            violations.append(f"exitCode must be an int (got {code!r})")
    for key in ("sessionId", "threadId"):
        if key not in data or data[key] is None:
            continue
        if not isinstance(data[key], str):
            violations.append(f"{key} must be a string when present (got {data[key]!r})")
    if "autoHandoff" in data and data["autoHandoff"] is not None:
        if not isinstance(data["autoHandoff"], dict):
            violations.append(
                "autoHandoff must be a mapping when present "
                f"(got {type(data['autoHandoff']).__name__})"
            )
    return violations


def verify_auto_handoff_result(
    result: dict,
    *,
    expected_plan_path: str,
    out_dir: str,
) -> dict:
    """Require enabled Auto Handoff facts from a terminal relay result (§14.4)."""
    handoff = result.get("autoHandoff") if isinstance(result, dict) else None
    if not isinstance(handoff, dict):
        raise HarnessError(
            AUTO_HANDOFF_INVALID,
            "relay result is missing autoHandoff",
        )
    if handoff.get("enabled") is not True:
        raise HarnessError(
            AUTO_HANDOFF_INVALID,
            "autoHandoff.enabled must be true",
            enabled=handoff.get("enabled"),
        )
    plan_file = handoff.get("planFile")
    if not _same_path(plan_file, expected_plan_path):
        raise HarnessError(
            AUTO_HANDOFF_INVALID,
            "autoHandoff.planFile does not match the accepted plan path",
            expected=expected_plan_path,
            actual=plan_file,
        )
    expected_handoff_dir = str(Path(out_dir) / "auto-handoff")
    if not _same_path(handoff.get("handoffDir"), expected_handoff_dir):
        raise HarnessError(
            AUTO_HANDOFF_INVALID,
            "autoHandoff.handoffDir must be <out_dir>/auto-handoff",
            expected=expected_handoff_dir,
            actual=handoff.get("handoffDir"),
        )
    extension_root = handoff.get("extensionRoot")
    if not isinstance(extension_root, str) or not extension_root.strip():
        raise HarnessError(
            AUTO_HANDOFF_INVALID,
            "autoHandoff.extensionRoot must be a non-empty string",
            extensionRoot=extension_root,
        )
    return handoff


def review_round_from_events(events) -> int:
    """Native ``changes_requested`` count + 1 (design §18.3)."""
    count = 0
    for event in events or ():
        if getattr(event, "kind", None) == "changes_requested":
            count += 1
    return count + 1


def handoff_metadata_from_runs(runs) -> list[dict]:
    """Metadata of ``review_requested`` runs, newest-first; ``{}`` if absent."""
    found: list[dict] = []
    for run in runs or ():
        if getattr(run, "outcome", None) != "review_requested":
            continue
        metadata = getattr(run, "metadata", None)
        found.append(metadata if isinstance(metadata, dict) else {})
    found.reverse()
    return found


def _json_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*.json") if path.is_file())


def _execute_review_sort_key(item: dict) -> tuple:
    round_n = item.get("round")
    run_id = item.get("review_run_id")
    round_key = round_n if isinstance(round_n, int) and not isinstance(round_n, bool) else 0
    run_key = run_id if isinstance(run_id, int) and not isinstance(run_id, bool) else 0
    return (round_key, run_key, str(item.get("_path") or ""))


def _same_path(actual, expected) -> bool:
    if actual == expected:
        return True
    if not isinstance(actual, str) or not actual:
        return False
    try:
        return Path(actual) == Path(expected)
    except (TypeError, ValueError):
        return False


def _canonical_json(data) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _write_immutable_json(
    dest: Path,
    payload: dict,
    *,
    code: str,
    message: str,
    expected: dict,
    existing_summary,
) -> dict:
    existing = load_json(dest)
    if dest.exists():
        if isinstance(existing, dict) and _canonical_json(existing) == _canonical_json(
            payload
        ):
            return existing
        raise HarnessError(
            code,
            message,
            expected=expected,
            existing=existing_summary(existing) if isinstance(existing, dict) else existing,
        )
    write_json_atomic(dest, payload)
    return payload


def _manifest_summary(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return data
    return {
        "candidate_commit": data.get("candidate_commit"),
        "diff_base": data.get("diff_base"),
        "diff_head": data.get("diff_head"),
        "attempt_number": data.get("attempt_number"),
        "accepted_plan": data.get("accepted_plan"),
    }


def _review_summary(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return data
    return {
        "schema": data.get("schema"),
        "card_id": data.get("card_id"),
        "review_run_id": data.get("review_run_id"),
        "round": data.get("round"),
        "candidate_commit": data.get("candidate_commit"),
        "verdict": data.get("verdict"),
        "overall": data.get("overall"),
    }


def _relay_error_blob(result: dict) -> str:
    parts: list[str] = []
    error = result.get("error")
    if error is not None:
        parts.append(error if isinstance(error, str) else str(error))
    tail = result.get("stderrTail")
    if tail is not None:
        parts.append(tail if isinstance(tail, str) else str(tail))
    return " ".join(parts)


def _strip_one_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _load_strict_yaml(text: str) -> Any:
    yaml_mod = getattr(_contracts, "yaml", None)
    loader = getattr(_contracts, "_StrictSafeLoader", None)
    if yaml_mod is None or loader is None:
        raise ValueError("PyYAML is unavailable; cannot parse review YAML")
    try:
        return yaml_mod.load(text, Loader=loader)
    except yaml_mod.YAMLError as exc:
        raise ValueError(f"review report YAML is invalid: {exc}") from exc


def _raise_identity_mismatch(report: dict, **expected) -> None:
    if not isinstance(report, dict):
        raise ValueError(
            f"review report must be a mapping (got {type(report).__name__})"
        )
    for key in _IDENTITY_FIELDS:
        if key not in expected:
            continue
        if key not in report:
            continue
        got = report[key]
        if got is None:
            continue
        want = expected[key]
        if got != want:
            raise ValueError(f"identity mismatch: {key} {got!r} != {want!r}")


def _json_safe_findings(findings: Any) -> Any:
    if findings is None:
        return []
    if not isinstance(findings, list):
        return findings
    out: list[Any] = []
    for item in findings:
        try:
            json.dumps(item)
        except (TypeError, ValueError):
            out.append(str(item))
        else:
            out.append(item)
    return out


def _gate_subset(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {"verdict": None, "findings": []}
    return {
        "verdict": raw.get("verdict"),
        "findings": _json_safe_findings(raw.get("findings")),
    }


def _bind_equal(violations: list[str], field: str, actual, expected) -> None:
    if actual != expected:
        violations.append(
            f"{field} does not match current facts "
            f"(got {actual!r}, expected {expected!r})"
        )


def _plan_pair(value) -> tuple | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return (type(value).__name__,)
    return (value.get("path"), value.get("sha256"))


def _same_plan_identity(actual, expected) -> bool:
    return _plan_pair(actual) == _plan_pair(expected)


def _record_holder_run_id(record: dict):
    if "holder_run_id" in record:
        return record.get("holder_run_id")
    return record.get("run_id")


def _bind_lease_record(ev: dict, lease_records: list[dict]) -> list[str]:
    lease = ev.get("lease")
    if not isinstance(lease, dict):
        return ["lease must be a mapping to bind against lease records"]
    lease_id = lease.get("lease_id")
    matches = [
        record
        for record in lease_records
        if isinstance(record, dict) and record.get("lease_id") == lease_id
    ]
    if not matches:
        return [
            f"lease_id {lease_id!r} is not present in lease records"
        ]
    run_id = ev.get("run_id")
    claimed_holder = lease.get("holder_run_id")
    holders = [_record_holder_run_id(record) for record in matches]
    violations: list[str] = []
    if claimed_holder is not None and claimed_holder not in holders:
        violations.append(
            "evidence lease.holder_run_id does not match the lease records "
            f"(got {claimed_holder!r}, records hold {holders!r})"
        )
    if run_id not in holders:
        violations.append(
            "lease record holder_run_id does not match evidence run_id "
            f"(got {holders!r}, expected {run_id!r})"
        )
    return violations
