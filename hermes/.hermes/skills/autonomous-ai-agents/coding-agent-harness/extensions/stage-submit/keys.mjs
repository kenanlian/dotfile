/**
 * Transport field lists for coding-agent-harness stage submit tools.
 * Must stay equal to src/contracts.mjs field-key constants.
 */
export const SUBMIT_PLAN = "submit_plan";
export const SUBMIT_PLAN_REVIEW = "submit_plan_review";
export const SUBMIT_IMPLEMENTATION = "submit_implementation";
export const SUBMIT_EXECUTE_REVIEW = "submit_execute_review";

export const PLAN_SCHEMA_ID = "plan.v1";
export const PLAN_REVIEW_SCHEMA_ID = "plan-review.v1";
export const IMPLEMENTATION_SCHEMA_ID = "implementation.v1";
export const EXECUTE_REVIEW_SCHEMA_ID = "execute-review.v1";

export const PLAN_FIELD_KEYS = Object.freeze([
  "schema",
  "outcome",
  "title",
  "goal",
  "architecture",
  "techStack",
  "requirements",
  "contracts",
  "workPackages",
  "verification",
  "risks",
  "blockingIssues",
]);

export const PLAN_REVIEW_FIELD_KEYS = Object.freeze([
  "schema",
  "verdict",
  "summary",
  "findings",
]);

export const IMPLEMENTATION_FIELD_KEYS = Object.freeze([
  "schema",
  "outcome",
  "summary",
  "completedWorkPackages",
  "deviations",
  "residualRisks",
  "blockingIssues",
]);

export const EXECUTE_REVIEW_FIELD_KEYS = Object.freeze([
  "schema",
  "verdict",
  "summary",
  "findings",
  "acceptanceCoverage",
]);

export const REQUIREMENT_FIELD_KEYS = Object.freeze(["id", "text"]);
export const CONTRACT_FIELD_KEYS = Object.freeze(["id", "requirementIds", "text"]);
export const WORK_PACKAGE_FIELD_KEYS = Object.freeze([
  "id", "title", "objective", "dependsOn", "contractIds", "fileChanges",
  "steps", "verificationIds",
]);
export const FILE_CHANGE_FIELD_KEYS = Object.freeze(["action", "path"]);
export const PLAN_VERIFICATION_FIELD_KEYS = Object.freeze([
  "id", "kind", "cwd", "argv", "expected", "contractIds",
]);
export const RISK_FIELD_KEYS = Object.freeze(["risk", "mitigation"]);
export const PLAN_REVIEW_FINDING_FIELD_KEYS = Object.freeze([
  "severity", "location", "problem", "requiredChange",
]);
export const DEVIATION_FIELD_KEYS = Object.freeze(["workPackageId", "summary"]);
export const EXECUTE_REVIEW_FINDING_FIELD_KEYS = Object.freeze([
  "severity", "file", "line", "problem", "requiredChange",
]);
