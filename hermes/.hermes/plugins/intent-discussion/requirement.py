"""Requirement document rendering and atomic persistence."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SCHEMA = "intent-discussion.requirement.v1"


class RequirementError(Exception):
    """Invalid requirement payload or persistence precondition."""


def write_requirement(
    repo: str,
    slug: str,
    title: str,
    goal: str,
    context: str,
    behaviors: Sequence[str],
    decisions: Sequence[Mapping[str, Any]],
    non_goals: Sequence[str],
    constraints: Sequence[str],
    auto_acceptance: Sequence[str],
    manual_acceptance: Sequence[Mapping[str, Any]],
    open_questions: Sequence[str],
    overwrite: bool = False,
) -> dict[str, Any]:
    repo_path = _validate_repo(repo)
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        raise RequirementError("slug must match ^[a-z0-9][a-z0-9-]{0,63}$")
    if not isinstance(goal, str) or not goal.strip():
        raise RequirementError("goal must be a non-empty string")
    _require_str_list(behaviors, "behaviors")
    _require_str_list(non_goals, "non_goals")
    _require_str_list(constraints, "constraints")
    _require_str_list(auto_acceptance, "auto_acceptance")
    _require_str_list(open_questions, "open_questions")
    _require_object_list(decisions, ("decision", "rationale"), "decisions")
    _require_object_list(
        manual_acceptance, ("scenario", "expected", "evidence"), "manual_acceptance"
    )
    if len(auto_acceptance) + len(manual_acceptance) < 1:
        raise RequirementError("auto_acceptance and manual_acceptance together need at least one item")

    status = "draft" if open_questions else "ready"
    dest = repo_path / ".dev" / "requirements" / f"{slug}.md"
    if dest.exists() and not overwrite:
        raise RequirementError(f"requirement already exists: {dest}")

    created = (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    text = _render(
        slug=slug,
        title=title,
        status=status,
        created=created,
        goal=goal,
        context=context,
        behaviors=behaviors,
        decisions=decisions,
        non_goals=non_goals,
        constraints=constraints,
        auto_acceptance=auto_acceptance,
        manual_acceptance=manual_acceptance,
        open_questions=open_questions,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(dest, text)
    raw = dest.read_bytes()
    return {
        "path": str(dest),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "status": status,
        "bytes": len(raw),
    }


def _validate_repo(repo: str) -> Path:
    if not isinstance(repo, str) or not repo:
        raise RequirementError("repo must be an absolute path")
    repo_path = Path(repo)
    if not repo_path.is_absolute():
        raise RequirementError("repo must be an absolute path")
    if not repo_path.exists():
        raise RequirementError("repo does not exist")
    if not repo_path.is_dir():
        raise RequirementError("repo must be a directory")
    return repo_path


def _require_str_list(value: Sequence[str], name: str) -> None:
    if not isinstance(value, (list, tuple)):
        raise RequirementError(f"{name} must be a list")
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise RequirementError(f"{name}[{index}] must be a string")


def _require_object_list(
    value: Sequence[Mapping[str, Any]], keys: tuple[str, ...], name: str
) -> None:
    if not isinstance(value, (list, tuple)):
        raise RequirementError(f"{name} must be a list")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise RequirementError(f"{name}[{index}] must be an object")
        missing = [key for key in keys if key not in item]
        if missing:
            raise RequirementError(f"{name}[{index}] missing keys: {', '.join(missing)}")
        for key in keys:
            if not isinstance(item[key], str):
                raise RequirementError(f"{name}[{index}].{key} must be a string")


def _render(
    *,
    slug: str,
    title: str,
    status: str,
    created: str,
    goal: str,
    context: str,
    behaviors: Sequence[str],
    decisions: Sequence[Mapping[str, Any]],
    non_goals: Sequence[str],
    constraints: Sequence[str],
    auto_acceptance: Sequence[str],
    manual_acceptance: Sequence[Mapping[str, Any]],
    open_questions: Sequence[str],
) -> str:
    sections = [
        "---",
        f"schema: {SCHEMA}",
        f"slug: {slug}",
        f"title: {title}",
        f"status: {status}",
        f"created: {created}",
        "---",
        "",
        f"# {title}",
        "",
        "## 目标",
        "",
        goal,
        "",
        "## 背景与现状",
        "",
        context,
        "",
        "## 行为规格",
        "",
        _string_list(behaviors),
        "",
        "## 已决决策",
        "",
        _decision_list(decisions),
        "",
        "## 非目标",
        "",
        _string_list(non_goals),
        "",
        "## 约束",
        "",
        _string_list(constraints, empty="无"),
        "",
        "## 自动验收",
        "",
        _string_list(auto_acceptance),
        "",
        "## 人工验收",
        "",
        _manual_list(manual_acceptance),
        "",
        "## 开放问题",
        "",
        _string_list(open_questions, empty="无"),
        "",
    ]
    return "\n".join(sections)


def _string_list(items: Sequence[str], empty: str = "") -> str:
    if not items:
        return empty
    return "\n".join(f"- {item}" for item in items)


def _decision_list(items: Sequence[Mapping[str, Any]]) -> str:
    if not items:
        return ""
    return "\n".join(
        f"- **{item['decision']}** — {item['rationale']}" for item in items
    )


def _manual_list(items: Sequence[Mapping[str, Any]]) -> str:
    if not items:
        return ""
    blocks = []
    for item in items:
        blocks.append(
            f"- {item['scenario']}\n"
            f"  - expected: {item['expected']}\n"
            f"  - evidence: {item['evidence']}"
        )
    return "\n".join(blocks)


def _atomic_write(path: Path, text: str) -> None:
    data = text.encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
