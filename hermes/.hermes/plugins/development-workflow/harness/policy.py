"""Read-only policy registry for direct / write-plan / execute-plan (design §13).

Relay Skill, mode, model routing, Auto Handoff, and adapter capability
requirements are derived here. Tools must not let the model override these
values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ADAPTER_CAPABILITY_MISSING, failure

MAX_REVIEW_ROUNDS = 3

PI_RELAY_SCRIPT_RELPATH = (
    "skills/autonomous-ai-agents/pi-delegate/scripts/relay.mjs"
)

_DIRECT_REVIEW_MODEL = "zai-coding-cn/glm-5.3"
_STAGE_IMPLEMENT_MODEL = "kimi-coding/k3"
_STAGE_IMPLEMENT_FALLBACK = "zai-coding-cn/glm-5.3"
_THINKING = "high"
_EXECUTION_OPS = ("execution", "rework")


@dataclass(frozen=True)
class StagePolicy:
    """Per-stage derived workflow policy (not stored on the Card)."""

    stage: str
    implement_skill: str
    review_skill: str | None
    review_lane: bool
    ui_execution: str
    auto_handoff: bool
    completion_owner: str
    max_review_rounds: int


POLICIES: dict[str, StagePolicy] = {
    "direct": StagePolicy(
        stage="direct",
        implement_skill="delegate-work",
        review_skill=None,
        review_lane=False,
        ui_execution="implement",
        auto_handoff=False,
        completion_owner="implement",
        max_review_rounds=MAX_REVIEW_ROUNDS,
    ),
    "write-plan": StagePolicy(
        stage="write-plan",
        implement_skill="write-plan",
        review_skill="review-plan",
        review_lane=True,
        ui_execution="none",
        auto_handoff=False,
        completion_owner="review",
        max_review_rounds=MAX_REVIEW_ROUNDS,
    ),
    "execute-plan": StagePolicy(
        stage="execute-plan",
        implement_skill="execute-plan",
        review_skill="review-execute-candidate",
        review_lane=True,
        ui_execution="implement",
        auto_handoff=True,
        completion_owner="review",
        max_review_rounds=MAX_REVIEW_ROUNDS,
    ),
}


@dataclass(frozen=True)
class RelaySpec:
    """Commissioning values derived from stage + operation + adapter."""

    skill: str
    skill_script_relpath: str
    mode: str
    model: str
    fallback_model: str | None
    thinking: str
    auto_handoff: bool
    review: bool
    resume_session_supported: bool


def resolve_relay_spec(
    *,
    stage: str,
    operation: str,
    coding_agent: str,
    review: bool = False,
) -> RelaySpec:
    """Derive Relay commissioning for a stage/operation (design §13/§14).

    Raises ``HarnessError(ADAPTER_CAPABILITY_MISSING)`` for non-pi agents.
    """
    if coding_agent != "pi":
        raise failure(
            ADAPTER_CAPABILITY_MISSING,
            f"coding_agent {coding_agent!r} is unsupported in v1 (pi only)",
            coding_agent=coding_agent,
        )
    policy = POLICIES.get(stage)
    if policy is None:
        raise failure(
            ADAPTER_CAPABILITY_MISSING,
            f"unknown stage {stage!r}",
            stage=stage,
        )
    if review:
        if not policy.review_skill:
            raise failure(
                ADAPTER_CAPABILITY_MISSING,
                f"stage {stage!r} has no review skill",
                stage=stage,
            )
        skill = policy.review_skill
        mode = "read"
        auto_handoff = False
        model: str = _DIRECT_REVIEW_MODEL
        fallback: str | None = None
    else:
        skill = policy.implement_skill
        mode = "write"
        auto_handoff = bool(
            policy.auto_handoff and operation in _EXECUTION_OPS
        )
        if stage == "direct":
            model = _DIRECT_REVIEW_MODEL
            fallback = None
        else:
            model = _STAGE_IMPLEMENT_MODEL
            fallback = _STAGE_IMPLEMENT_FALLBACK
    return RelaySpec(
        skill=skill,
        skill_script_relpath=PI_RELAY_SCRIPT_RELPATH,
        mode=mode,
        model=model,
        fallback_model=fallback,
        thinking=_THINKING,
        auto_handoff=auto_handoff,
        review=review,
        resume_session_supported=True,
    )


def _auto_handoff_root() -> Path | None:
    candidates = []
    env = (os.environ.get("PI_AUTO_HANDOFF_ROOT") or "").strip()
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(Path.home() / "Secret-Projects" / "pi-auto-handoff")
    for candidate in candidates:
        if (
            (candidate / "package.json").is_file()
            and (candidate / "src" / "index.ts").is_file()
        ):
            return candidate
    return None


def check_adapter_capability(
    coding_agent: str,
    *,
    hermes_home: Path | str,
    auto_handoff_required: bool,
) -> list[str]:
    """Return capability problems for ``coding_agent`` under ``hermes_home``."""
    issues: list[str] = []
    if coding_agent != "pi":
        issues.append(
            f"coding_agent {coding_agent!r} is unsupported in v1 (pi only)"
        )
        return issues
    home = Path(hermes_home)
    relay = home / PI_RELAY_SCRIPT_RELPATH
    if not relay.is_file():
        issues.append(f"pi relay script missing: {relay}")
    if auto_handoff_required:
        root = _auto_handoff_root()
        if root is None:
            issues.append(
                "auto-handoff extension root not found (expected "
                "~/Secret-Projects/pi-auto-handoff or PI_AUTO_HANDOFF_ROOT, "
                "with package.json and src/index.ts)"
            )
    return issues


def adapter_skill(coding_agent: str) -> str:
    """Relay adapter skill for ``coding_agent``. v1 supports Pi only."""
    if coding_agent == "pi":
        return "pi-delegate"
    raise failure(
        ADAPTER_CAPABILITY_MISSING,
        f"coding_agent {coding_agent!r} is unsupported in v1 (pi only)",
        coding_agent=coding_agent,
    )


def pinned_worker_skills(coding_agent: str) -> list[str]:
    """Skills force-loaded onto managed development workers."""
    return ["development-orchestrator", adapter_skill(coding_agent)]
