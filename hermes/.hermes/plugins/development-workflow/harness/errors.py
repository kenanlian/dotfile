"""Stable structured rejection contract for Development Workflow tools.

Error codes match design §21. Schema identifiers live in ``contracts``.
"""

from __future__ import annotations

import json
from typing import Any

ORIGIN_ROLE_REQUIRED = "ORIGIN_ROLE_REQUIRED"
IMPLEMENT_ROLE_REQUIRED = "IMPLEMENT_ROLE_REQUIRED"
REVIEW_ROLE_REQUIRED = "REVIEW_ROLE_REQUIRED"
RUN_OWNERSHIP_LOST = "RUN_OWNERSHIP_LOST"
RUN_NOT_OWNED = "RUN_NOT_OWNED"
CARD_CONTRACT_INVALID = "CARD_CONTRACT_INVALID"
DRAFT_NOT_DISPATCHABLE = "DRAFT_NOT_DISPATCHABLE"
FEATURE_STAGE_CONFLICT = "FEATURE_STAGE_CONFLICT"
WORKSPACE_INVALID = "WORKSPACE_INVALID"
ADAPTER_CAPABILITY_MISSING = "ADAPTER_CAPABILITY_MISSING"
PLAN_IDENTITY_MISSING = "PLAN_IDENTITY_MISSING"
PLAN_SHA_MISMATCH = "PLAN_SHA_MISMATCH"
BRIEF_MISSING = "BRIEF_MISSING"
RELAY_ATTEMPT_UNCERTAIN = "RELAY_ATTEMPT_UNCERTAIN"
AUTO_HANDOFF_REQUIRED = "AUTO_HANDOFF_REQUIRED"
AUTO_HANDOFF_INVALID = "AUTO_HANDOFF_INVALID"
CANDIDATE_NOT_FROZEN = "CANDIDATE_NOT_FROZEN"
CANDIDATE_CHANGED = "CANDIDATE_CHANGED"
EVIDENCE_IDENTITY_MISMATCH = "EVIDENCE_IDENTITY_MISMATCH"
REVIEW_GATE_INCOMPLETE = "REVIEW_GATE_INCOMPLETE"
UI_RESOURCE_BUSY = "UI_RESOURCE_BUSY"
UI_ACCEPTANCE_INCOMPLETE = "UI_ACCEPTANCE_INCOMPLETE"
MANUAL_ACCEPTANCE_PENDING = "MANUAL_ACCEPTANCE_PENDING"
ROUND_LIMIT_REACHED = "ROUND_LIMIT_REACHED"
HARNESS_INCOMPATIBLE = "HARNESS_INCOMPATIBLE"
HARNESS_STATE_UNAVAILABLE = "HARNESS_STATE_UNAVAILABLE"


class HarnessError(Exception):
    """Structured harness failure with a stable machine-readable payload."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        current_state: dict[str, Any] | None = None,
        allowed_actions: list[str] | None = None,
        remediation: str | None = None,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.current_state = current_state
        self.allowed_actions = allowed_actions
        self.remediation = remediation
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "code": self.code,
            "message": self.message,
        }
        if self.current_state is not None:
            payload["current_state"] = self.current_state
        if self.allowed_actions is not None:
            payload["allowed_actions"] = self.allowed_actions
        if self.remediation is not None:
            payload["remediation"] = self.remediation
        if self.details:
            payload["details"] = dict(self.details)
        return payload


def ok_result(data: dict[str, Any]) -> str:
    """JSON success envelope; ``ok: True`` always wins over caller data."""
    payload = dict(data)
    payload["ok"] = True
    return json.dumps(payload, ensure_ascii=False)


def error_result(err: HarnessError) -> str:
    """JSON rejection envelope from a ``HarnessError``."""
    return json.dumps(err.to_payload(), ensure_ascii=False)


def failure(code: str, message: str, **kw: Any) -> HarnessError:
    """Build a ``HarnessError`` without raising it."""
    return HarnessError(code, message, **kw)
