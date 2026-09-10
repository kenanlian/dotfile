"""Card, decision, candidate, review, and UI evidence contracts.

Parses and validates ``development-stage.v2`` bodies plus the related
append-only JSON comment and artifact schemas. Structural parse failures
raise ``ContractError``; key-set, enum, and value violations are returned
as string lists from the validators (design §11.4, §12.4, §16.1, §17.3,
§18.2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:  # PyYAML ships with Hermes (plugin manifests need it); degrade loudly if absent.
    import yaml
except ImportError:  # pragma: no cover - defensive
    yaml = None  # type: ignore[assignment]


STAGE_SCHEMA_ID = "development-stage.v2"
STAGES = ("direct", "write-plan", "execute-plan")
INTENTS = ("draft", "converged")
UI_STATES = ("pending", "required", "not-required")
CODING_AGENTS = ("pi", "cursor", "codex", "opencode")

CARD_FRONTMATTER_KEYS = (
    "schema",
    "feature_id",
    "stage",
    "intent",
    "ui_acceptance",
    "manual_acceptance",
    "coding_agent",
    "accepted_plan",
)

CARD_SECTIONS = (
    "Goal",
    "Observable acceptance",
    "Included scope",
    "Non-goals",
    "Settled decisions",
    "Open decisions",
    "Repository grounding",
    "Authority boundaries",
)

SUBSTANTIVE_SECTIONS = (
    "Goal",
    "Observable acceptance",
    "Included scope",
    "Authority boundaries",
)

DECISION_SCHEMA_ID = "development-decision.v1"
DECISION_KINDS = (
    "intent-decision",
    "amendment",
    "manual-verdict",
    "round-authorization",
)
_DECISION_KIND_FIELDS = {
    "intent-decision": frozenset(),
    "amendment": frozenset(),
    "manual-verdict": frozenset({"verdict", "candidate_commit"}),
    "round-authorization": frozenset({"round", "candidate_commit"}),
}
MANUAL_VERDICTS = ("PASS", "FAIL")

CANDIDATE_SCHEMA_ID = "development-candidate.v1"
CANDIDATE_KEYS = (
    "schema",
    "board",
    "card_id",
    "feature_id",
    "stage",
    "implement_run_id",
    "attempt_number",
    "candidate_commit",
    "diff_base",
    "diff_head",
    "accepted_plan",
    "created_at",
)
CANDIDATE_STAGES = ("direct", "execute-plan")

EXECUTE_REVIEW_SCHEMA_ID = "development-execute-review.v1"
EXECUTE_REVIEW_KEYS = (
    "schema",
    "card_id",
    "review_run_id",
    "round",
    "candidate_commit",
    "accepted_plan_sha256",
    "patch_gate",
    "plan_conformance_gate",
    "overall",
)
GATE_VERDICTS = ("pass", "fail")
OVERALL_VERDICTS = ("pass", "revise", "blocked")
GATE_KEYS = ("verdict", "findings")

PLAN_REVIEW_SCHEMA_ID = "development-plan-review.v1"
PLAN_REVIEW_KEYS = (
    "schema",
    "board",
    "card_id",
    "feature_id",
    "review_run_id",
    "round",
    "plan",
    "verdict",
    "summary",
    "required_revisions",
)
PLAN_REVIEW_VERDICTS = ("pass", "revise")

UI_EVIDENCE_SCHEMA_ID = "development-ui-evidence.v2"
UI_EVIDENCE_KEYS = (
    "schema",
    "board",
    "card_id",
    "feature_id",
    "stage",
    "run_id",
    "attempt_number",
    "candidate_commit",
    "diff_base",
    "diff_head",
    "accepted_plan",
    "relay_session_id",
    "artifacts",
    "lease",
    "scenarios",
    "verdict",
    "automation_boundary",
    "cleanup",
    "created_at",
)
UI_EVIDENCE_STAGES = ("direct", "execute-plan")
UI_VERDICTS = ("PASS", "FAIL", "BLOCKED")
_UI_LEASE_KEYS = (
    "resource",
    "lease_id",
    "holder_run_id",
    "acquired_at",
    "released_at",
)
_UI_SCENARIO_KEYS = ("name", "verdict")

_FEATURE_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$")
_ACCEPTED_PLAN_KEYS = ("card_id", "path", "sha256")
_CANDIDATE_PLAN_KEYS = ("path", "sha256")


class ContractError(ValueError):
    """Raised when a body does not parse as development-stage.v2 structure."""


@dataclass(frozen=True)
class StageCard:
    """Parsed ``development-stage.v2`` frontmatter plus fixed sections."""

    frontmatter: dict
    sections: dict

    @property
    def stage(self) -> Any:
        return self.frontmatter.get("stage")

    @property
    def feature_id(self) -> Any:
        return self.frontmatter.get("feature_id")

    @property
    def intent(self) -> Any:
        return self.frontmatter.get("intent")

    @property
    def ui_acceptance(self) -> Any:
        return self.frontmatter.get("ui_acceptance")

    @property
    def manual_acceptance(self) -> Any:
        return self.frontmatter.get("manual_acceptance")

    @property
    def coding_agent(self) -> Any:
        return self.frontmatter.get("coding_agent")

    @property
    def accepted_plan(self) -> Any:
        return self.frontmatter.get("accepted_plan")


# ---------------------------------------------------------------------------
# Strict YAML frontmatter parsing (duplicate keys rejected)
# ---------------------------------------------------------------------------

if yaml is not None:

    class _StrictSafeLoader(yaml.SafeLoader):
        """SafeLoader variant that rejects duplicate mapping keys."""

    def _construct_unique_mapping(loader, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    f"duplicate frontmatter key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _StrictSafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
    )


def _split_frontmatter(body: str) -> tuple[dict[str, Any], str]:
    """Split a body into (frontmatter mapping, markdown remainder).

    Raises ContractError with a precise message on any parse failure.
    """
    if yaml is None:  # pragma: no cover - defensive
        raise ContractError("PyYAML is unavailable; cannot parse frontmatter")
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractError(
            "body must start with a '---' YAML frontmatter block"
        )
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break
    if close_idx is None:
        raise ContractError("frontmatter is not closed with a second '---' line")
    raw = "\n".join(lines[1:close_idx])
    try:
        data = yaml.load(raw, Loader=_StrictSafeLoader)
    except yaml.YAMLError as exc:
        raise ContractError(f"frontmatter YAML is invalid: {exc}") from exc
    if data is None:
        raise ContractError("frontmatter is empty")
    if not isinstance(data, dict):
        raise ContractError(
            f"frontmatter must be a YAML mapping (got {type(data).__name__})"
        )
    for key in data:
        if not isinstance(key, str):
            raise ContractError(
                f"frontmatter keys must be strings (got {key!r})"
            )
    return data, "\n".join(lines[close_idx + 1 :])


def _try_split_frontmatter(body: str) -> tuple[dict[str, Any], str] | None:
    """Tolerant frontmatter split: ``None`` on any failure, never raises."""
    if not isinstance(body, str) or not body.strip():
        return None
    try:
        return _split_frontmatter(body)
    except (ContractError, Exception):
        return None


def card_schema_id(body: str) -> str | None:
    """Return the literal frontmatter ``schema`` string, or ``None``.

    Frontmatter-only: no section parsing. Never raises.
    """
    split = _try_split_frontmatter(body)
    if split is None:
        return None
    frontmatter, _remainder = split
    schema = frontmatter.get("schema")
    if isinstance(schema, str):
        return schema
    return None


def _split_sections(markdown: str) -> dict[str, str]:
    """Parse the fixed level-1 sections from the post-frontmatter markdown.

    Enforces: no stray content before the first heading, exactly the required
    headings, in order, each exactly once. Returns heading name -> content.
    """
    found: list[str] = []
    sections: dict[str, str] = {}
    current: str | None = None
    buffers: dict[str, list[str]] = {}
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current = match.group(1).strip()
            found.append(current)
            buffers[current] = []
            continue
        if current is None:
            if line.strip():
                raise ContractError(
                    "body contains content before the first '# Goal' section"
                )
            continue  # tolerate blank lines between frontmatter and sections
        buffers[current].append(line)
    if not found:
        raise ContractError("body has no level-1 '#' sections")
    if found != list(CARD_SECTIONS):
        expected = ", ".join(f"'# {name}'" for name in CARD_SECTIONS)
        actual = ", ".join(f"'# {name}'" for name in found)
        raise ContractError(
            "body sections must be exactly the eight fixed sections in order; "
            f"expected [{expected}]; found [{actual}]"
        )
    for name in CARD_SECTIONS:
        sections[name] = "\n".join(buffers[name]).strip()
    return sections


def parse_stage_body(body: str) -> StageCard:
    """Parse a ``development-stage.v2`` body into a ``StageCard``.

    Raises ``ContractError`` only for structural failures (missing frontmatter,
    invalid YAML, non-mapping, or section shape/order). Key-set, enum, and
    value violations are reported by ``validate_stage_card``.
    """
    if not isinstance(body, str) or not body.strip():
        raise ContractError("body is required and must be a non-empty string")
    frontmatter, markdown = _split_frontmatter(body)
    sections = _split_sections(markdown)
    return StageCard(frontmatter=frontmatter, sections=sections)


def _exact_keys(data: dict[str, Any], expected: tuple[str, ...], *, label: str) -> list[str]:
    violations: list[str] = []
    actual = set(data)
    wanted = set(expected)
    for key in sorted(actual - wanted):
        violations.append(
            f"unknown {label} key {key!r}; allowed keys: " + ", ".join(expected)
        )
    for key in expected:
        if key not in data:
            violations.append(f"missing required {label} key {key!r}")
    return violations


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_absolute_path(value: Any) -> bool:
    return isinstance(value, str) and value != "" and Path(value).is_absolute()


def validate_accepted_plan_identity(value: Any) -> list[str]:
    """Validate an Accepted Plan identity mapping (card_id / path / sha256)."""
    violations: list[str] = []
    if not isinstance(value, dict):
        violations.append(
            "accepted_plan must be a mapping with keys card_id, path, sha256 "
            f"(got {type(value).__name__})"
        )
        return violations
    violations.extend(_exact_keys(value, _ACCEPTED_PLAN_KEYS, label="accepted_plan"))
    card_id = value.get("card_id")
    if "card_id" in value and (not isinstance(card_id, str) or not card_id.strip()):
        violations.append(
            f"accepted_plan.card_id must be a non-empty string (got {card_id!r})"
        )
    path = value.get("path")
    if "path" in value and not _is_absolute_path(path):
        violations.append(
            "accepted_plan.path must be an absolute path string "
            f"(got {path!r})"
        )
    sha256 = value.get("sha256")
    if "sha256" in value and not (
        isinstance(sha256, str) and _SHA256_RE.fullmatch(sha256)
    ):
        violations.append(
            "accepted_plan.sha256 must be a 64-character lowercase hex digest "
            f"(got {sha256!r})"
        )
    return violations


def validate_stage_card(
    card: StageCard, *, require: Literal["draft", "converged"]
) -> list[str]:
    """Return contract violations for a parsed stage Card (design §11.4)."""
    if require not in INTENTS:
        raise ValueError(f"require must be one of {list(INTENTS)} (got {require!r})")

    frontmatter = card.frontmatter
    sections = card.sections
    violations: list[str] = []

    violations.extend(_exact_keys(frontmatter, CARD_FRONTMATTER_KEYS, label="frontmatter"))

    schema = frontmatter.get("schema")
    if "schema" in frontmatter and schema != STAGE_SCHEMA_ID:
        violations.append(
            f"frontmatter schema must be {STAGE_SCHEMA_ID!r} (got {schema!r})"
        )

    feature_id = frontmatter.get("feature_id")
    if "feature_id" in frontmatter and not (
        isinstance(feature_id, str) and _FEATURE_ID_RE.fullmatch(feature_id)
    ):
        violations.append(
            "feature_id must be kebab-case "
            r"^[a-z0-9]+(-[a-z0-9]+)*$ "
            f"(got {feature_id!r})"
        )

    stage = frontmatter.get("stage")
    if "stage" in frontmatter and stage not in STAGES:
        violations.append(
            f"stage must be one of {list(STAGES)} (got {stage!r})"
        )

    intent = frontmatter.get("intent")
    if "intent" in frontmatter and intent not in INTENTS:
        violations.append(
            f"intent must be one of {list(INTENTS)} (got {intent!r})"
        )
    if intent != require:
        violations.append(
            f"intent must be {require!r} (got {intent!r})"
        )

    ui = frontmatter.get("ui_acceptance")
    if "ui_acceptance" in frontmatter and ui not in UI_STATES:
        violations.append(
            "ui_acceptance must be one of "
            f"{list(UI_STATES)} (got {ui!r})"
        )

    agent = frontmatter.get("coding_agent")
    if "coding_agent" in frontmatter and agent not in CODING_AGENTS:
        violations.append(
            "coding_agent must be one of "
            f"{list(CODING_AGENTS)} (got {agent!r})"
        )

    manual = frontmatter.get("manual_acceptance")
    if "manual_acceptance" in frontmatter:
        if not isinstance(manual, list):
            violations.append(
                "manual_acceptance must be a list of non-empty strings "
                f"(got {type(manual).__name__})"
            )
        else:
            if any(not isinstance(item, str) or not item.strip() for item in manual):
                violations.append(
                    "manual_acceptance items must be non-empty strings "
                    f"(got {manual!r})"
                )
            if manual and ui != "required":
                violations.append(
                    "manual_acceptance may be non-empty only when "
                    "ui_acceptance is 'required'"
                )

    accepted_plan = frontmatter.get("accepted_plan")
    if stage in ("direct", "write-plan"):
        if "accepted_plan" in frontmatter and accepted_plan is not None:
            violations.append(
                f"accepted_plan must be null for stage {stage!r} "
                f"(got {accepted_plan!r})"
            )
    elif stage == "execute-plan":
        if accepted_plan is None:
            if require == "converged":
                violations.append(
                    "execute-plan converged Cards require an accepted_plan "
                    "identity mapping"
                )
        else:
            violations.extend(validate_accepted_plan_identity(accepted_plan))

    if require == "converged":
        if ui == "pending":
            violations.append(
                "ui_acceptance must be classified as 'required' or "
                "'not-required' when intent is converged (got 'pending')"
            )
        for section in SUBSTANTIVE_SECTIONS:
            content = sections.get(section)
            if not content:
                violations.append(
                    f"'# {section}' section is empty; a dispatchable Card needs "
                    "substantive content"
                )
            elif content == "None":
                violations.append(
                    f"'# {section}' must be substantive (non-empty, not the "
                    "literal 'None')"
                )
        open_decisions = sections.get("Open decisions")
        if open_decisions is None:
            violations.append("'# Open decisions' section is missing")
        elif open_decisions != "None":
            violations.append(
                "'# Open decisions' must be exactly 'None' before dispatch (got: "
                f"{open_decisions!r})"
            )

    return violations


def encode_decision_comment(
    kind: str,
    *,
    card_id: str,
    feature_id: str,
    stage: str,
    decision: str,
    decided_by: str,
    affects_accepted_plan: bool | None = None,
    candidate_commit: str | None = None,
    verdict: str | None = None,
    round: int | None = None,
    created_note: str | None = None,
) -> str:
    """Encode a compact single-JSON-object Kanban decision comment body."""
    payload: dict[str, Any] = {
        "schema": DECISION_SCHEMA_ID,
        "kind": kind,
        "card_id": card_id,
        "feature_id": feature_id,
        "stage": stage,
        "decision": decision,
        "decided_by": decided_by,
    }
    if affects_accepted_plan is not None:
        payload["affects_accepted_plan"] = bool(affects_accepted_plan)
    if candidate_commit is not None:
        payload["candidate_commit"] = candidate_commit
    if verdict is not None:
        payload["verdict"] = verdict
    if round is not None:
        payload["round"] = round
    if created_note is not None:
        payload["created_note"] = created_note
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_decision_comment(body: str) -> dict[str, Any] | None:
    """Parse a decision comment body, or ``None`` if it is not one."""
    if not isinstance(body, str) or not body.strip():
        return None
    try:
        data = json.loads(body.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != DECISION_SCHEMA_ID:
        return None
    return data


def validate_decision(data: dict[str, Any]) -> list[str]:
    """Kind-specific decision comment field rules (design §12.4)."""
    violations: list[str] = []
    if not isinstance(data, dict):
        return [f"decision must be a mapping (got {type(data).__name__})"]
    schema = data.get("schema")
    if schema != DECISION_SCHEMA_ID:
        violations.append(
            f"decision schema must be {DECISION_SCHEMA_ID!r} (got {schema!r})"
        )
    kind = data.get("kind")
    if kind not in DECISION_KINDS:
        violations.append(
            f"kind must be one of {list(DECISION_KINDS)} (got {kind!r})"
        )
    for field in ("card_id", "feature_id", "stage", "decision", "decided_by"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            violations.append(f"{field} must be a non-empty string (got {value!r})")
    stage = data.get("stage")
    if isinstance(stage, str) and stage not in STAGES:
        violations.append(f"stage must be one of {list(STAGES)} (got {stage!r})")

    used = _DECISION_KIND_FIELDS.get(kind, frozenset())
    for field in ("verdict", "candidate_commit", "round"):
        if field not in used and field in data:
            violations.append(f"{field} must be absent for kind {kind!r}")

    if kind == "manual-verdict":
        verdict = data.get("verdict")
        if verdict not in MANUAL_VERDICTS:
            violations.append(
                "manual-verdict requires verdict exactly 'PASS' or 'FAIL' "
                f"(got {verdict!r})"
            )
        commit = data.get("candidate_commit")
        if not (isinstance(commit, str) and _SHA1_RE.fullmatch(commit)):
            violations.append(
                "manual-verdict requires candidate_commit as a 40-character "
                f"lowercase hex digest (got {commit!r})"
            )
    if kind == "amendment":
        flag = data.get("affects_accepted_plan")
        if not isinstance(flag, bool):
            violations.append(
                "amendment requires affects_accepted_plan as a boolean "
                f"(got {flag!r})"
            )
    if kind == "round-authorization":
        round_n = data.get("round")
        if not (_is_int(round_n) and round_n >= 1):
            violations.append(
                "round-authorization requires round as an int >= 1 "
                f"(got {round_n!r})"
            )
        commit = data.get("candidate_commit")
        if not (isinstance(commit, str) and _SHA1_RE.fullmatch(commit)):
            violations.append(
                "round-authorization requires candidate_commit as a "
                f"40-character lowercase hex digest (got {commit!r})"
            )
    return violations


def _validate_sha1_field(data: dict[str, Any], key: str, violations: list[str]) -> None:
    value = data.get(key)
    if key in data and not (isinstance(value, str) and _SHA1_RE.fullmatch(value)):
        violations.append(
            f"{key} must be a 40-character lowercase hex digest (got {value!r})"
        )


def validate_candidate_manifest(data: Any) -> list[str]:
    """Validate a ``development-candidate.v1`` mapping (design §16.1)."""
    if not isinstance(data, dict):
        return [f"candidate manifest must be a mapping (got {type(data).__name__})"]
    violations = _exact_keys(data, CANDIDATE_KEYS, label="candidate")
    schema = data.get("schema")
    if "schema" in data and schema != CANDIDATE_SCHEMA_ID:
        violations.append(
            f"schema must be {CANDIDATE_SCHEMA_ID!r} (got {schema!r})"
        )
    stage = data.get("stage")
    if "stage" in data and stage not in CANDIDATE_STAGES:
        violations.append(
            f"stage must be one of {list(CANDIDATE_STAGES)} (got {stage!r})"
        )
    run_id = data.get("implement_run_id")
    if "implement_run_id" in data and not _is_int(run_id):
        violations.append(
            f"implement_run_id must be an int (got {run_id!r})"
        )
    attempt = data.get("attempt_number")
    if "attempt_number" in data and not (_is_int(attempt) and attempt >= 1):
        violations.append(
            f"attempt_number must be an int >= 1 (got {attempt!r})"
        )
    for key in ("candidate_commit", "diff_base", "diff_head"):
        _validate_sha1_field(data, key, violations)
    if (
        isinstance(data.get("diff_head"), str)
        and isinstance(data.get("candidate_commit"), str)
        and data["diff_head"] != data["candidate_commit"]
    ):
        violations.append("diff_head must equal candidate_commit")
    accepted_plan = data.get("accepted_plan")
    if "accepted_plan" in data and accepted_plan is not None:
        if not isinstance(accepted_plan, dict):
            violations.append(
                "accepted_plan must be null or a mapping with keys path, sha256 "
                f"(got {type(accepted_plan).__name__})"
            )
        else:
            violations.extend(
                _exact_keys(accepted_plan, _CANDIDATE_PLAN_KEYS, label="accepted_plan")
            )
            path = accepted_plan.get("path")
            if "path" in accepted_plan and path is not None and not _is_absolute_path(path):
                violations.append(
                    "accepted_plan.path must be null or an absolute path string "
                    f"(got {path!r})"
                )
            sha256 = accepted_plan.get("sha256")
            if "sha256" in accepted_plan and sha256 is not None and not (
                isinstance(sha256, str) and _SHA256_RE.fullmatch(sha256)
            ):
                violations.append(
                    "accepted_plan.sha256 must be null or a 64-character "
                    f"lowercase hex digest (got {sha256!r})"
                )
    return violations


def _validate_gate(name: str, value: Any, violations: list[str]) -> str | None:
    if not isinstance(value, dict):
        violations.append(
            f"{name} must be a mapping with keys verdict, findings "
            f"(got {type(value).__name__})"
        )
        return None
    violations.extend(_exact_keys(value, GATE_KEYS, label=name))
    verdict = value.get("verdict")
    if "verdict" in value and verdict not in GATE_VERDICTS:
        violations.append(
            f"{name}.verdict must be one of {list(GATE_VERDICTS)} (got {verdict!r})"
        )
    findings = value.get("findings")
    if "findings" in value and not isinstance(findings, list):
        violations.append(
            f"{name}.findings must be a list (got {type(findings).__name__})"
        )
    return verdict if verdict in GATE_VERDICTS else None


def validate_execute_review(data: Any) -> list[str]:
    """Validate a ``development-execute-review.v1`` mapping (design §18.2)."""
    if not isinstance(data, dict):
        return [f"execute review must be a mapping (got {type(data).__name__})"]
    violations = _exact_keys(data, EXECUTE_REVIEW_KEYS, label="execute-review")
    schema = data.get("schema")
    if "schema" in data and schema != EXECUTE_REVIEW_SCHEMA_ID:
        violations.append(
            f"schema must be {EXECUTE_REVIEW_SCHEMA_ID!r} (got {schema!r})"
        )
    round_n = data.get("round")
    if "round" in data and not (_is_int(round_n) and round_n >= 1):
        violations.append(f"round must be an int >= 1 (got {round_n!r})")
    patch_verdict = _validate_gate("patch_gate", data.get("patch_gate"), violations)
    plan_verdict = _validate_gate(
        "plan_conformance_gate", data.get("plan_conformance_gate"), violations
    )
    overall = data.get("overall")
    overall_verdict = None
    if "overall" in data:
        if not isinstance(overall, dict) or "verdict" not in overall:
            violations.append(
                "overall must be a mapping with a verdict of "
                f"{list(OVERALL_VERDICTS)}"
            )
        else:
            overall_verdict = overall.get("verdict")
            if overall_verdict not in OVERALL_VERDICTS:
                violations.append(
                    "overall.verdict must be one of "
                    f"{list(OVERALL_VERDICTS)} (got {overall_verdict!r})"
                )
    if (
        patch_verdict == "fail" or plan_verdict == "fail"
    ) and overall_verdict != "revise":
        violations.append(
            "overall.verdict must be 'revise' when either gate verdict is 'fail'"
        )
    if overall_verdict == "pass" and (
        patch_verdict != "pass" or plan_verdict != "pass"
    ):
        violations.append(
            "overall.verdict 'pass' requires both patch_gate and "
            "plan_conformance_gate verdicts to be 'pass'"
        )
    sha256 = data.get("accepted_plan_sha256")
    if "accepted_plan_sha256" in data and not (
        isinstance(sha256, str) and _SHA256_RE.fullmatch(sha256)
    ):
        violations.append(
            "accepted_plan_sha256 must be a 64-character lowercase hex digest "
            f"(got {sha256!r})"
        )
    return violations


def _validate_path_sha256(
    value: Any, *, label: str, require_absolute_path: bool = True
) -> list[str]:
    violations: list[str] = []
    if not isinstance(value, dict):
        violations.append(
            f"{label} must be a mapping with keys path, sha256 "
            f"(got {type(value).__name__})"
        )
        return violations
    violations.extend(_exact_keys(value, _CANDIDATE_PLAN_KEYS, label=label))
    path = value.get("path")
    if "path" in value:
        if require_absolute_path:
            if not _is_absolute_path(path):
                violations.append(
                    f"{label}.path must be an absolute path string (got {path!r})"
                )
        elif not isinstance(path, str) or not path.strip():
            violations.append(
                f"{label}.path must be a non-empty string (got {path!r})"
            )
    sha256 = value.get("sha256")
    if "sha256" in value and not (
        isinstance(sha256, str) and _SHA256_RE.fullmatch(sha256)
    ):
        violations.append(
            f"{label}.sha256 must be a 64-character lowercase hex digest "
            f"(got {sha256!r})"
        )
    return violations


def validate_plan_review(data: Any) -> list[str]:
    """Validate a ``development-plan-review.v1`` mapping (blocker 5)."""
    if not isinstance(data, dict):
        return [f"plan review must be a mapping (got {type(data).__name__})"]
    violations = _exact_keys(data, PLAN_REVIEW_KEYS, label="plan-review")
    schema = data.get("schema")
    if "schema" in data and schema != PLAN_REVIEW_SCHEMA_ID:
        violations.append(
            f"schema must be {PLAN_REVIEW_SCHEMA_ID!r} (got {schema!r})"
        )
    for field in ("board", "card_id", "feature_id", "summary"):
        value = data.get(field)
        if field in data and (not isinstance(value, str) or not value.strip()):
            violations.append(
                f"{field} must be a non-empty string (got {value!r})"
            )
    review_run_id = data.get("review_run_id")
    if "review_run_id" in data and not _is_int(review_run_id):
        violations.append(
            f"review_run_id must be an int (got {review_run_id!r})"
        )
    round_n = data.get("round")
    if "round" in data and not (_is_int(round_n) and round_n >= 1):
        violations.append(f"round must be an int >= 1 (got {round_n!r})")
    if "plan" in data:
        violations.extend(
            _validate_path_sha256(data.get("plan"), label="plan")
        )
    verdict = data.get("verdict")
    if "verdict" in data and verdict not in PLAN_REVIEW_VERDICTS:
        violations.append(
            f"verdict must be one of {list(PLAN_REVIEW_VERDICTS)} (got {verdict!r})"
        )
    revisions = data.get("required_revisions")
    if "required_revisions" in data:
        if not isinstance(revisions, list) or any(
            not isinstance(item, str) for item in revisions
        ):
            violations.append("required_revisions must be a list of strings")
    return violations


def validate_ui_evidence(data: Any) -> list[str]:
    """Validate a ``development-ui-evidence.v2`` mapping (design §17.3)."""
    if not isinstance(data, dict):
        return [f"ui evidence must be a mapping (got {type(data).__name__})"]
    violations = _exact_keys(data, UI_EVIDENCE_KEYS, label="ui-evidence")
    schema = data.get("schema")
    if "schema" in data and schema != UI_EVIDENCE_SCHEMA_ID:
        violations.append(
            f"schema must be {UI_EVIDENCE_SCHEMA_ID!r} (got {schema!r})"
        )
    for field in ("board", "card_id", "feature_id", "created_at"):
        value = data.get(field)
        if field in data and (not isinstance(value, str) or not value.strip()):
            violations.append(
                f"{field} must be a non-empty string (got {value!r})"
            )
    stage = data.get("stage")
    if "stage" in data and stage not in UI_EVIDENCE_STAGES:
        violations.append(
            f"stage must be one of {list(UI_EVIDENCE_STAGES)} (got {stage!r})"
        )
    run_id = data.get("run_id")
    if "run_id" in data and not _is_int(run_id):
        violations.append(f"run_id must be an int (got {run_id!r})")
    attempt = data.get("attempt_number")
    if "attempt_number" in data and not (_is_int(attempt) and attempt >= 1):
        violations.append(
            f"attempt_number must be an int >= 1 (got {attempt!r})"
        )
    for key in ("candidate_commit", "diff_base", "diff_head"):
        _validate_sha1_field(data, key, violations)
    if (
        isinstance(data.get("diff_head"), str)
        and isinstance(data.get("candidate_commit"), str)
        and data["diff_head"] != data["candidate_commit"]
    ):
        violations.append("diff_head must equal candidate_commit")
    accepted_plan = data.get("accepted_plan")
    if "accepted_plan" in data and accepted_plan is not None:
        violations.extend(
            _validate_path_sha256(accepted_plan, label="accepted_plan")
        )
    relay = data.get("relay_session_id")
    if "relay_session_id" in data and relay is not None:
        if not isinstance(relay, str) or not relay.strip():
            violations.append(
                "relay_session_id must be a non-empty string or null "
                f"(got {relay!r})"
            )
    artifacts = data.get("artifacts")
    if "artifacts" in data:
        if not isinstance(artifacts, list):
            violations.append(
                f"artifacts must be a list (got {type(artifacts).__name__})"
            )
        else:
            for index, item in enumerate(artifacts):
                violations.extend(
                    _validate_path_sha256(
                        item,
                        label=f"artifacts[{index}]",
                        require_absolute_path=False,
                    )
                )
    lease = data.get("lease")
    if "lease" in data:
        if not isinstance(lease, dict):
            violations.append(
                "lease must be a mapping with keys resource, lease_id, "
                f"holder_run_id, acquired_at, released_at (got {type(lease).__name__})"
            )
        else:
            violations.extend(_exact_keys(lease, _UI_LEASE_KEYS, label="lease"))
            resource = lease.get("resource")
            if "resource" in lease and (
                not isinstance(resource, str) or not resource.strip()
            ):
                violations.append(
                    f"lease.resource must be a non-empty string (got {resource!r})"
                )
            lease_id = lease.get("lease_id")
            if "lease_id" in lease and (
                not isinstance(lease_id, str) or not lease_id.strip()
            ):
                violations.append(
                    f"lease.lease_id must be a non-empty string (got {lease_id!r})"
                )
            holder = lease.get("holder_run_id")
            if "holder_run_id" in lease and not _is_int(holder):
                violations.append(
                    f"lease.holder_run_id must be an int (got {holder!r})"
                )
            for stamp in ("acquired_at", "released_at"):
                value = lease.get(stamp)
                if stamp in lease and (
                    not isinstance(value, str) or not value.strip()
                ):
                    violations.append(
                        f"lease.{stamp} must be a non-empty string (got {value!r})"
                    )
    scenarios = data.get("scenarios")
    if "scenarios" in data:
        if not (isinstance(scenarios, list) and scenarios):
            violations.append("scenarios must be a non-empty list")
        elif any(not isinstance(item, dict) for item in scenarios):
            violations.append(
                "scenarios items must be mappings with keys name, verdict"
            )
        else:
            for index, item in enumerate(scenarios):
                label = f"scenarios[{index}]"
                violations.extend(_exact_keys(item, _UI_SCENARIO_KEYS, label=label))
                name = item.get("name")
                if "name" in item and (not isinstance(name, str) or not name.strip()):
                    violations.append(
                        f"{label}.name must be a non-empty string (got {name!r})"
                    )
                scenario_verdict = item.get("verdict")
                if "verdict" in item and scenario_verdict not in UI_VERDICTS:
                    violations.append(
                        f"{label}.verdict must be one of {list(UI_VERDICTS)} "
                        f"(got {scenario_verdict!r})"
                    )
    verdict = data.get("verdict")
    if "verdict" in data and verdict not in UI_VERDICTS:
        violations.append(
            f"verdict must be one of {list(UI_VERDICTS)} (got {verdict!r})"
        )
    for field in ("automation_boundary", "cleanup"):
        value = data.get(field)
        if field in data and (not isinstance(value, str) or not value.strip()):
            violations.append(
                f"{field} must be a non-empty string (got {value!r})"
            )
    return violations
