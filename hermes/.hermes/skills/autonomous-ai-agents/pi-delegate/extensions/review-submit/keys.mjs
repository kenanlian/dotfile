/**
 * Transport field lists for the review-submit tools.
 *
 * These literals must stay equal to harness `contracts.py`
 * `PLAN_REVIEW_KEYS` / `EXECUTE_REVIEW_KEYS`. The extension TypeBox schemas
 * are a transport mirror; harness C18 validation is authoritative.
 */
export const SUBMIT_PLAN_REVIEW = "submit_plan_review";
export const SUBMIT_EXECUTE_REVIEW = "submit_execute_review";

export const PLAN_REVIEW_SCHEMA_ID = "development-plan-review.v1";
export const EXECUTE_REVIEW_SCHEMA_ID = "development-execute-review.v1";

/** Equal to contracts.py PLAN_REVIEW_KEYS. */
export const PLAN_REVIEW_FIELD_KEYS = Object.freeze([
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
]);

/** Equal to contracts.py EXECUTE_REVIEW_KEYS. No ui_evidence (L13). */
export const EXECUTE_REVIEW_FIELD_KEYS = Object.freeze([
  "schema",
  "card_id",
  "review_run_id",
  "round",
  "candidate_commit",
  "accepted_plan_sha256",
  "patch_gate",
  "plan_conformance_gate",
  "overall",
]);

export const GATE_FIELD_KEYS = Object.freeze(["verdict", "findings"]);
export const PLAN_PATH_FIELD_KEYS = Object.freeze(["path", "sha256"]);
export const OVERALL_FIELD_KEYS = Object.freeze(["verdict"]);
