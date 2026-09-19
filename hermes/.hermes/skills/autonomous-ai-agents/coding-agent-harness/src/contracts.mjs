import { isAbsolute, resolve, sep } from "node:path";

export const JOB_SCHEMA_ID = "coding-agent.job.v1";
export const RESULT_SCHEMA_ID = "coding-agent.result.v1";
export const ARTIFACT_SCHEMA_ID = "coding-agent.artifact.v1";
export const EVENT_SCHEMA_ID = "coding-agent.event.v1";

export const PLAN_SCHEMA_ID = "plan.v1";
export const PLAN_REVIEW_SCHEMA_ID = "plan-review.v1";
export const IMPLEMENTATION_SCHEMA_ID = "implementation.v1";
export const DIRECT_IMPLEMENTATION_SCHEMA_ID = "direct-implementation.v1";
export const EXECUTE_REVIEW_SCHEMA_ID = "execute-review.v1";

export const STAGES = Object.freeze([
  "plan", "plan_review", "implement", "execute_review", "direct_implement",
]);
export const ADAPTERS = Object.freeze(["pi", "cursor"]);

export const SUBMIT_TOOLS = Object.freeze({
  plan: "submit_plan",
  plan_review: "submit_plan_review",
  implement: "submit_implementation",
  execute_review: "submit_execute_review",
  direct_implement: "submit_direct_implementation",
});

export const STAGE_CONTRACTS = Object.freeze({
  plan: Object.freeze({
    stage: "plan",
    profile: "planner",
    permission: "read-only",
    outputKind: "plan",
    outputSchema: PLAN_SCHEMA_ID,
    submitTool: SUBMIT_TOOLS.plan,
    session: "fresh_or_resume",
    verificationAllowed: false,
    verificationRequired: false,
  }),
  plan_review: Object.freeze({
    stage: "plan_review",
    profile: "plan-reviewer",
    permission: "read-only",
    outputKind: "plan-review",
    outputSchema: PLAN_REVIEW_SCHEMA_ID,
    submitTool: SUBMIT_TOOLS.plan_review,
    session: "fresh",
    verificationAllowed: false,
    verificationRequired: false,
  }),
  implement: Object.freeze({
    stage: "implement",
    profile: "implementer",
    permission: "write",
    outputKind: "implementation",
    outputSchema: IMPLEMENTATION_SCHEMA_ID,
    submitTool: SUBMIT_TOOLS.implement,
    session: "fresh_or_resume",
    verificationAllowed: true,
    verificationRequired: false,
  }),
  execute_review: Object.freeze({
    stage: "execute_review",
    profile: "execute-reviewer",
    permission: "read-only",
    outputKind: "execute-review",
    outputSchema: EXECUTE_REVIEW_SCHEMA_ID,
    submitTool: SUBMIT_TOOLS.execute_review,
    session: "fresh",
    verificationAllowed: false,
    verificationRequired: false,
  }),
  direct_implement: Object.freeze({
    stage: "direct_implement",
    profile: "implementer",
    permission: "write",
    outputKind: "direct-implementation",
    outputSchema: DIRECT_IMPLEMENTATION_SCHEMA_ID,
    submitTool: SUBMIT_TOOLS.direct_implement,
    session: "fresh_or_resume",
    verificationAllowed: true,
    verificationRequired: true,
  }),
});

export const JOB_FIELD_KEYS = Object.freeze([
  "schema", "jobId", "idempotencyKey", "taskId", "stage", "attempt",
  "workspace", "agent", "permissions", "inputs", "expectedOutput",
  "verification", "limits",
]);
export const WORKSPACE_FIELD_KEYS = Object.freeze([
  "repoRoot", "branch", "expectedHead", "requireCleanAtStart",
]);
export const AGENT_FIELD_KEYS = Object.freeze([
  "adapter", "profile", "model", "thinking", "sessionId",
]);
export const PERMISSIONS_FIELD_KEYS = Object.freeze(["mode"]);
export const INPUT_FIELD_KEYS = Object.freeze(["kind", "path", "sha256"]);
export const EXPECTED_OUTPUT_FIELD_KEYS = Object.freeze(["kind", "schema"]);
export const JOB_CHECK_FIELD_KEYS = Object.freeze([
  "id", "argv", "cwd", "timeoutSeconds", "expectedExitCode",
]);
export const LIMITS_FIELD_KEYS = Object.freeze(["timeoutSeconds"]);

export const RESULT_FIELD_KEYS = Object.freeze([
  "schema", "jobId", "idempotencyKey", "jobSha256", "taskId", "stage",
  "status", "adapter", "resolvedModel", "sessionId", "startedAt", "finishedAt",
  "structuredOutput", "artifacts", "touchedFiles", "checks", "usage",
  "workspace", "error", "paths",
]);
export const RESULT_WORKSPACE_FIELD_KEYS = Object.freeze([
  "repoRoot", "branchBefore", "branchAfter", "headBefore", "headAfter",
  "snapshotBeforeSha256", "snapshotAfterSha256",
]);
export const RESULT_PATHS_FIELD_KEYS = Object.freeze([
  "events", "stderr", "final", "adapterRuns",
]);
export const ADAPTER_RUN_FIELD_KEYS = Object.freeze([
  "phase", "result", "events", "stderr", "final",
]);
export const ARTIFACT_ENTRY_FIELD_KEYS = Object.freeze([
  "kind", "path", "sha256", "schema", "canonical",
]);
export const STRUCTURED_OUTPUT_FIELD_KEYS = Object.freeze(["kind", "payload"]);
export const ERROR_OBJECT_FIELD_KEYS = Object.freeze(["kind", "message", "details"]);
export const CHECK_RESULT_FIELD_KEYS = Object.freeze([
  "id", "status", "argv", "cwd", "expectedExitCode", "exitCode", "signal",
  "startedAt", "finishedAt", "stdoutPath", "stderrPath",
]);
export const ARTIFACT_FIELD_KEYS = Object.freeze([
  "schema", "kind", "job", "sessionId", "inputs", "workspace", "payload",
]);
export const ARTIFACT_JOB_FIELD_KEYS = Object.freeze([
  "jobId", "idempotencyKey", "taskId", "stage", "attempt", "jobSha256",
]);
export const ARTIFACT_WORKSPACE_FIELD_KEYS = Object.freeze([
  "repoRoot", "branch", "head", "baselineSnapshotSha256",
]);
export const STRUCTURED_INPUT_KINDS = Object.freeze([
  "plan", "plan-review", "implementation",
]);
export const OUTPUT_KIND_TO_STAGE = Object.freeze({
  plan: "plan",
  "plan-review": "plan_review",
  implementation: "implement",
  "execute-review": "execute_review",
  "direct-implementation": "direct_implement",
});

export const PLAN_FIELD_KEYS = Object.freeze([
  "schema", "outcome", "title", "goal", "architecture", "techStack",
  "requirements", "contracts", "workPackages", "verification", "risks",
  "blockingIssues",
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

export const PLAN_REVIEW_FIELD_KEYS = Object.freeze([
  "schema", "verdict", "summary", "findings",
]);
export const PLAN_REVIEW_FINDING_FIELD_KEYS = Object.freeze([
  "severity", "location", "problem", "requiredChange",
]);

export const IMPLEMENTATION_FIELD_KEYS = Object.freeze([
  "schema", "outcome", "summary", "completedWorkPackages", "deviations",
  "residualRisks", "blockingIssues",
]);
export const DIRECT_IMPLEMENTATION_FIELD_KEYS = Object.freeze([
  "schema", "outcome", "summary", "residualRisks", "blockingIssues",
]);
export const DEVIATION_FIELD_KEYS = Object.freeze(["workPackageId", "summary"]);

export const EXECUTE_REVIEW_FIELD_KEYS = Object.freeze([
  "schema", "verdict", "summary", "findings", "acceptanceCoverage",
]);
export const EXECUTE_REVIEW_FINDING_FIELD_KEYS = Object.freeze([
  "severity", "file", "line", "problem", "requiredChange",
]);

export const INPUT_KINDS = Object.freeze([
  "requirement", "plan", "plan-review", "implementation", "evidence",
]);
export const OUTPUT_KINDS = Object.freeze([
  "plan", "plan-review", "implementation", "execute-review", "direct-implementation",
]);
export const THINKING_LEVELS = Object.freeze([
  "off", "minimal", "low", "medium", "high", "xhigh", "max",
]);
export const RESULT_STATUSES = Object.freeze([
  "completed", "failed", "timed_out", "aborted", "unavailable",
]);
export const CHECK_STATUSES = Object.freeze([
  "passed", "failed", "timed_out", "unavailable",
]);
export const REVIEW_VERDICTS = Object.freeze(["approved", "request_changes", "blocked"]);
export const OUTCOMES = Object.freeze(["completed", "blocked"]);
export const FILE_ACTIONS = Object.freeze(["create", "modify", "delete"]);
export const PLAN_CHECK_KINDS = Object.freeze(["focused", "integration", "smoke"]);
export const PROFILES = Object.freeze([
  "planner", "plan-reviewer", "implementer", "execute-reviewer",
]);
export const PERMISSION_MODES = Object.freeze(["read-only", "write"]);

export const ERROR_KINDS = new Set([
  "invalid_job",
  "idempotency_conflict",
  "run_in_progress",
  "workspace_mismatch",
  "input_hash_mismatch",
  "permission_mismatch",
  "adapter_unavailable",
  "adapter_failed",
  "agent_not_settled",
  "session_mismatch",
  "structured_output_missing",
  "structured_output_duplicate",
  "structured_output_invalid",
  "read_only_violation",
  "artifact_write_failed",
  "extension_manifest_mismatch",
  "aborted",
  "timed_out",
]);

const SAFE_MODEL = /^[A-Za-z0-9][A-Za-z0-9._:@/-]*$/;
const CURSOR_MODEL_SLUG = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;
const SHA1 = /^[a-f0-9]{40}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;

export function typedError(kind, path, message, details) {
  const error = { kind, path, message };
  if (details !== undefined) error.details = details;
  return error;
}

function fail(path, message) {
  return { ok: false, error: typedError("invalid_job", path, message) };
}

function ok(value) {
  return { ok: true, value };
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function joinPath(base, key) {
  if (base === "" || base === "/") return `/${key}`;
  return `${base}/${key}`;
}

function exactObject(value, keys, path, optionalKeys = []) {
  if (!isPlainObject(value)) return fail(path, "expected object");
  const actual = Object.keys(value);
  for (const key of actual) {
    if (!keys.includes(key)) {
      return fail(joinPath(path, key), `unknown field ${key}`);
    }
  }
  for (const key of keys) {
    if (optionalKeys.includes(key)) continue;
    if (!Object.hasOwn(value, key)) {
      return fail(path, `expected exact keys [${keys.join(", ")}]`);
    }
  }
  return null;
}

function nonEmptyString(value, path) {
  if (typeof value !== "string" || value.length === 0) {
    return fail(path, "expected non-empty string");
  }
  return null;
}

function booleanValue(value, path) {
  if (typeof value !== "boolean") return fail(path, "expected boolean");
  return null;
}

function integerInRange(value, path, min, max) {
  if (!Number.isInteger(value) || value < min || value > max) {
    return fail(path, `expected integer ${min}..${max}`);
  }
  return null;
}

function enumValue(value, path, allowed) {
  if (!allowed.includes(value)) {
    return fail(path, `expected one of ${allowed.join(", ")}`);
  }
  return null;
}

function absolutePath(value, path) {
  const empty = nonEmptyString(value, path);
  if (empty) return empty;
  if (!isAbsolute(value)) return fail(path, "expected absolute path");
  return null;
}

function sha256Digest(value, path) {
  if (typeof value !== "string" || !SHA256.test(value)) {
    return fail(path, "expected 64-character lowercase hex SHA-256");
  }
  return null;
}

function gitHead(value, path) {
  if (typeof value !== "string" || !(SHA1.test(value) || SHA256.test(value))) {
    return fail(path, "expected 40- or 64-character lowercase hex Git SHA");
  }
  return null;
}

function providerQualifiedModel(value, path) {
  if (typeof value !== "string" || !SAFE_MODEL.test(value)) {
    return fail(path, "model does not match the relay safe-model character set");
  }
  const slash = value.indexOf("/");
  if (slash <= 0 || slash === value.length - 1) {
    return fail(path, "model must be provider-qualified (provider/model)");
  }
  return null;
}

function cursorModelSlug(value, path) {
  if (typeof value !== "string" || !CURSOR_MODEL_SLUG.test(value)) {
    return fail(path, "model does not match the Cursor model slug character set");
  }
  return null;
}

function stringArray(value, path, { allowEmpty = true, nonEmptyItems = true } = {}) {
  if (!Array.isArray(value)) return fail(path, "expected array");
  if (!allowEmpty && value.length === 0) return fail(path, "expected non-empty array");
  for (let i = 0; i < value.length; i += 1) {
    const itemPath = joinPath(path, String(i));
    if (typeof value[i] !== "string") return fail(itemPath, "expected string");
    if (nonEmptyItems && value[i].length === 0) return fail(itemPath, "expected non-empty string");
  }
  return null;
}

function uniqueStrings(values, path) {
  const seen = new Set();
  for (let i = 0; i < values.length; i += 1) {
    if (seen.has(values[i])) return fail(joinPath(path, String(i)), `duplicate id ${values[i]}`);
    seen.add(values[i]);
  }
  return null;
}

function pathContained(child, parent) {
  const resolvedParent = resolve(parent);
  const resolvedChild = resolve(child);
  if (resolvedChild === resolvedParent) return true;
  const prefix = resolvedParent.endsWith(sep) ? resolvedParent : `${resolvedParent}${sep}`;
  return resolvedChild.startsWith(prefix);
}

export function isRepoRelativePath(value) {
  if (typeof value !== "string" || value.length === 0) return false;
  if (isAbsolute(value) || value.startsWith("/") || value.includes("\\")) return false;
  const parts = value.split("/");
  if (parts.some((part) => part === "" || part === "." || part === "..")) return false;
  return true;
}

function repoRelativePath(value, path) {
  if (!isRepoRelativePath(value)) {
    return fail(path, "expected repo-relative path without .. escape");
  }
  return null;
}

function isoTimestamp(value, path) {
  if (typeof value !== "string" || !ISO_TIMESTAMP.test(value)) {
    return fail(path, "expected ISO-8601 UTC timestamp");
  }
  return null;
}

function nullableIdentity(value, path, { allowNull }) {
  if (value === null) {
    if (!allowNull) return fail(path, "identity must not be null");
    return null;
  }
  return nonEmptyString(value, path);
}

export function validateJob(value) {
  const objectError = exactObject(value, JOB_FIELD_KEYS, "");
  if (objectError) return objectError;
  if (value.schema !== JOB_SCHEMA_ID) return fail("/schema", `expected ${JOB_SCHEMA_ID}`);
  for (const key of ["jobId", "idempotencyKey", "taskId"]) {
    const err = nonEmptyString(value[key], `/${key}`);
    if (err) return err;
  }
  const stageErr = enumValue(value.stage, "/stage", STAGES);
  if (stageErr) return stageErr;
  const attemptErr = integerInRange(value.attempt, "/attempt", 1, Number.MAX_SAFE_INTEGER);
  if (attemptErr) return attemptErr;

  const workspaceErr = exactObject(value.workspace, WORKSPACE_FIELD_KEYS, "/workspace");
  if (workspaceErr) return workspaceErr;
  const repoErr = absolutePath(value.workspace.repoRoot, "/workspace/repoRoot");
  if (repoErr) return repoErr;
  const branchErr = nonEmptyString(value.workspace.branch, "/workspace/branch");
  if (branchErr) return branchErr;
  const headErr = gitHead(value.workspace.expectedHead, "/workspace/expectedHead");
  if (headErr) return headErr;
  const cleanErr = booleanValue(value.workspace.requireCleanAtStart, "/workspace/requireCleanAtStart");
  if (cleanErr) return cleanErr;

  const agentErr = exactObject(value.agent, AGENT_FIELD_KEYS, "/agent");
  if (agentErr) return agentErr;
  const adapterErr = enumValue(value.agent.adapter, "/agent/adapter", ADAPTERS);
  if (adapterErr) return adapterErr;
  const thinkingErr = enumValue(value.agent.thinking, "/agent/thinking", THINKING_LEVELS);
  if (thinkingErr) return thinkingErr;
  const modelErr = value.agent.adapter === "cursor"
    ? cursorModelSlug(value.agent.model, "/agent/model")
    : providerQualifiedModel(value.agent.model, "/agent/model");
  if (modelErr) return modelErr;
  if (value.agent.sessionId !== null) {
    const sessionErr = nonEmptyString(value.agent.sessionId, "/agent/sessionId");
    if (sessionErr) return sessionErr;
  }

  const permErr = exactObject(value.permissions, PERMISSIONS_FIELD_KEYS, "/permissions");
  if (permErr) return permErr;
  const modeErr = enumValue(value.permissions.mode, "/permissions/mode", PERMISSION_MODES);
  if (modeErr) return modeErr;

  const outputErr = exactObject(value.expectedOutput, EXPECTED_OUTPUT_FIELD_KEYS, "/expectedOutput");
  if (outputErr) return outputErr;

  const limitsErr = exactObject(value.limits, LIMITS_FIELD_KEYS, "/limits");
  if (limitsErr) return limitsErr;
  if (value.limits.timeoutSeconds !== null) {
    const timeoutErr = integerInRange(value.limits.timeoutSeconds, "/limits/timeoutSeconds", 1, 2147483);
    if (timeoutErr) return timeoutErr;
  }

  const contract = STAGE_CONTRACTS[value.stage];
  if (value.agent.profile !== contract.profile) {
    return fail("/agent/profile", `expected ${contract.profile} for stage ${value.stage}`);
  }
  if (value.permissions.mode !== contract.permission) {
    return fail("/permissions/mode", `expected ${contract.permission} for stage ${value.stage}`);
  }
  if (
    value.expectedOutput.kind !== contract.outputKind
    || value.expectedOutput.schema !== contract.outputSchema
  ) {
    return fail("/expectedOutput", `expected ${contract.outputKind}/${contract.outputSchema}`);
  }
  if (contract.session === "fresh" && value.agent.sessionId !== null) {
    return fail("/agent/sessionId", "reviewer jobs must be fresh (sessionId:null)");
  }

  if (!Array.isArray(value.inputs)) return fail("/inputs", "expected array");
  const seenPaths = new Set();
  const counts = Object.create(null);
  for (let i = 0; i < value.inputs.length; i += 1) {
    const itemPath = `/inputs/${i}`;
    const itemErr = exactObject(value.inputs[i], INPUT_FIELD_KEYS, itemPath);
    if (itemErr) return itemErr;
    const kindErr = enumValue(value.inputs[i].kind, `${itemPath}/kind`, INPUT_KINDS);
    if (kindErr) return kindErr;
    const pathErr = absolutePath(value.inputs[i].path, `${itemPath}/path`);
    if (pathErr) return pathErr;
    const hashErr = sha256Digest(value.inputs[i].sha256, `${itemPath}/sha256`);
    if (hashErr) return hashErr;
    if (seenPaths.has(value.inputs[i].path)) {
      return fail(`${itemPath}/path`, "input paths must be unique");
    }
    seenPaths.add(value.inputs[i].path);
    counts[value.inputs[i].kind] = (counts[value.inputs[i].kind] || 0) + 1;
  }
  const cardinalityErr = validateInputCardinality(value.stage, counts);
  if (cardinalityErr) return cardinalityErr;

  if (!Array.isArray(value.verification)) return fail("/verification", "expected array");
  if (!contract.verificationAllowed && value.verification.length > 0) {
    return fail("/verification", "verification is only allowed on implement and direct_implement jobs");
  }
  if (contract.verificationRequired && value.verification.length === 0) {
    return fail("/verification", `${value.stage} jobs require a non-empty verification array`);
  }
  const checkIds = new Set();
  for (let i = 0; i < value.verification.length; i += 1) {
    const itemPath = `/verification/${i}`;
    const itemErr = exactObject(value.verification[i], JOB_CHECK_FIELD_KEYS, itemPath);
    if (itemErr) return itemErr;
    const idErr = nonEmptyString(value.verification[i].id, `${itemPath}/id`);
    if (idErr) return idErr;
    if (checkIds.has(value.verification[i].id)) {
      return fail(`${itemPath}/id`, `duplicate check id ${value.verification[i].id}`);
    }
    checkIds.add(value.verification[i].id);
    const argvErr = stringArray(value.verification[i].argv, `${itemPath}/argv`, { allowEmpty: false });
    if (argvErr) return argvErr;
    const cwdErr = absolutePath(value.verification[i].cwd, `${itemPath}/cwd`);
    if (cwdErr) return cwdErr;
    if (!pathContained(value.verification[i].cwd, value.workspace.repoRoot)) {
      return fail(`${itemPath}/cwd`, "cwd must equal repoRoot or be inside it");
    }
    const timeoutErr = integerInRange(
      value.verification[i].timeoutSeconds,
      `${itemPath}/timeoutSeconds`,
      1,
      86400,
    );
    if (timeoutErr) return timeoutErr;
    const exitErr = integerInRange(
      value.verification[i].expectedExitCode,
      `${itemPath}/expectedExitCode`,
      0,
      255,
    );
    if (exitErr) return exitErr;
  }

  return ok(value);
}

function validateInputCardinality(stage, counts) {
  const requirement = counts.requirement || 0;
  const plan = counts.plan || 0;
  const implementation = counts.implementation || 0;
  if (stage === "plan" && requirement < 1) {
    return fail("/inputs", "plan jobs require at least one requirement input");
  }
  if (stage === "plan_review") {
    if (requirement < 1 || plan !== 1) {
      return fail("/inputs", "plan_review jobs require >=1 requirement and exactly 1 plan");
    }
  }
  if (stage === "implement" && plan !== 1) {
    return fail("/inputs", "implement jobs require exactly 1 plan input");
  }
  if (stage === "direct_implement") {
    const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
    if (requirement !== 1 || total !== 1) {
      return fail("/inputs", "direct_implement jobs require exactly 1 requirement input and no plan");
    }
  }
  if (stage === "execute_review") {
    if (requirement < 1 || plan !== 1 || implementation !== 1) {
      return fail("/inputs", "execute_review jobs require >=1 requirement, exactly 1 plan, and exactly 1 implementation");
    }
  }
  return null;
}

export function validatePayload(kind, value, options = {}) {
  if (kind === "plan") return validatePlanPayload(value);
  if (kind === "plan-review") return validatePlanReviewPayload(value);
  if (kind === "implementation") return validateImplementationPayload(value, options.planPayload);
  if (kind === "direct-implementation") return validateDirectImplementationPayload(value);
  if (kind === "execute-review") return validateExecuteReviewPayload(value);
  return fail("/kind", `unknown payload kind ${kind}`);
}

function prefixFail(result, prefix) {
  if (result.ok) return result;
  const raw = result.error.path || "";
  const path = raw === "" || raw === "/" ? prefix : `${prefix}${raw.startsWith("/") ? raw : `/${raw}`}`;
  return {
    ok: false,
    error: typedError(result.error.kind, path, result.error.message, result.error.details),
  };
}

export function validateArtifact(value, options = {}) {
  if (!isPlainObject(value)) return fail("", "expected object");
  if (value.schema !== ARTIFACT_SCHEMA_ID) {
    return fail("/schema", `expected ${ARTIFACT_SCHEMA_ID}`);
  }
  const objectError = exactObject(value, ARTIFACT_FIELD_KEYS, "");
  if (objectError) return objectError;
  const kindErr = enumValue(value.kind, "/kind", OUTPUT_KINDS);
  if (kindErr) return kindErr;
  if (options.expectedKind && value.kind !== options.expectedKind) {
    return fail("/kind", `expected canonical Artifact kind ${options.expectedKind}`);
  }

  const jobErr = exactObject(value.job, ARTIFACT_JOB_FIELD_KEYS, "/job");
  if (jobErr) return jobErr;
  for (const key of ["jobId", "idempotencyKey", "taskId"]) {
    const err = nonEmptyString(value.job[key], `/job/${key}`);
    if (err) return err;
  }
  const expectedStage = OUTPUT_KIND_TO_STAGE[value.kind];
  if (value.job.stage !== expectedStage) {
    return fail("/job/stage", `expected ${expectedStage} for kind ${value.kind}`);
  }
  const attemptErr = integerInRange(value.job.attempt, "/job/attempt", 1, Number.MAX_SAFE_INTEGER);
  if (attemptErr) return attemptErr;
  const jobHashErr = sha256Digest(value.job.jobSha256, "/job/jobSha256");
  if (jobHashErr) return jobHashErr;

  const sessionErr = nonEmptyString(value.sessionId, "/sessionId");
  if (sessionErr) return sessionErr;

  if (!Array.isArray(value.inputs)) return fail("/inputs", "expected array");
  for (let i = 0; i < value.inputs.length; i += 1) {
    const itemPath = `/inputs/${i}`;
    const itemErr = exactObject(value.inputs[i], INPUT_FIELD_KEYS, itemPath);
    if (itemErr) return itemErr;
    const inputKindErr = enumValue(value.inputs[i].kind, `${itemPath}/kind`, INPUT_KINDS);
    if (inputKindErr) return inputKindErr;
    const pathErr = absolutePath(value.inputs[i].path, `${itemPath}/path`);
    if (pathErr) return pathErr;
    const hashErr = sha256Digest(value.inputs[i].sha256, `${itemPath}/sha256`);
    if (hashErr) return hashErr;
  }

  const workspaceErr = exactObject(value.workspace, ARTIFACT_WORKSPACE_FIELD_KEYS, "/workspace");
  if (workspaceErr) return workspaceErr;
  const repoErr = absolutePath(value.workspace.repoRoot, "/workspace/repoRoot");
  if (repoErr) return repoErr;
  const branchErr = nonEmptyString(value.workspace.branch, "/workspace/branch");
  if (branchErr) return branchErr;
  const headErr = gitHead(value.workspace.head, "/workspace/head");
  if (headErr) return headErr;
  const baselineErr = sha256Digest(value.workspace.baselineSnapshotSha256, "/workspace/baselineSnapshotSha256");
  if (baselineErr) return baselineErr;

  const payloadResult = validatePayload(value.kind, value.payload, { planPayload: options.planPayload });
  if (!payloadResult.ok) return prefixFail(payloadResult, "/payload");
  return ok(value);
}

export function parseCanonicalArtifact(text, options = {}) {
  if (typeof text !== "string") return fail("", "structured input is not valid JSON");
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return fail("", "structured input is not valid JSON");
  }
  return validateArtifact(parsed, options);
}

function validatePlanPayload(value) {
  const objectError = exactObject(value, PLAN_FIELD_KEYS, "");
  if (objectError) return objectError;
  if (value.schema !== PLAN_SCHEMA_ID) return fail("/schema", `expected ${PLAN_SCHEMA_ID}`);
  const outcomeErr = enumValue(value.outcome, "/outcome", OUTCOMES);
  if (outcomeErr) return outcomeErr;
  for (const key of ["title", "goal", "architecture"]) {
    const err = nonEmptyString(value[key], `/${key}`);
    if (err) return err;
  }
  const stackErr = stringArray(value.techStack, "/techStack");
  if (stackErr) return stackErr;
  if (!Array.isArray(value.requirements)) return fail("/requirements", "expected array");
  if (!Array.isArray(value.contracts)) return fail("/contracts", "expected array");
  if (!Array.isArray(value.workPackages)) return fail("/workPackages", "expected array");
  if (!Array.isArray(value.verification)) return fail("/verification", "expected array");
  if (!Array.isArray(value.risks)) return fail("/risks", "expected array");
  const blockersErr = stringArray(value.blockingIssues, "/blockingIssues", { nonEmptyItems: true });
  if (blockersErr) return blockersErr;

  const requirementIds = [];
  for (let i = 0; i < value.requirements.length; i += 1) {
    const path = `/requirements/${i}`;
    const err = exactObject(value.requirements[i], REQUIREMENT_FIELD_KEYS, path);
    if (err) return err;
    const idErr = nonEmptyString(value.requirements[i].id, `${path}/id`);
    if (idErr) return idErr;
    const textErr = nonEmptyString(value.requirements[i].text, `${path}/text`);
    if (textErr) return textErr;
    requirementIds.push(value.requirements[i].id);
  }
  const reqUnique = uniqueStrings(requirementIds, "/requirements");
  if (reqUnique) return reqUnique;

  const contractIds = [];
  for (let i = 0; i < value.contracts.length; i += 1) {
    const path = `/contracts/${i}`;
    const err = exactObject(value.contracts[i], CONTRACT_FIELD_KEYS, path);
    if (err) return err;
    const idErr = nonEmptyString(value.contracts[i].id, `${path}/id`);
    if (idErr) return idErr;
    const textErr = nonEmptyString(value.contracts[i].text, `${path}/text`);
    if (textErr) return textErr;
    const refsErr = stringArray(value.contracts[i].requirementIds, `${path}/requirementIds`, { allowEmpty: false });
    if (refsErr) return refsErr;
    for (let j = 0; j < value.contracts[i].requirementIds.length; j += 1) {
      if (!requirementIds.includes(value.contracts[i].requirementIds[j])) {
        return fail(`${path}/requirementIds/${j}`, `unknown requirement ${value.contracts[i].requirementIds[j]}`);
      }
    }
    contractIds.push(value.contracts[i].id);
  }
  const contractUnique = uniqueStrings(contractIds, "/contracts");
  if (contractUnique) return contractUnique;

  const workPackageIds = [];
  for (let i = 0; i < value.workPackages.length; i += 1) {
    const path = `/workPackages/${i}`;
    const wp = value.workPackages[i];
    const err = exactObject(wp, WORK_PACKAGE_FIELD_KEYS, path);
    if (err) return err;
    for (const key of ["id", "title", "objective"]) {
      const fieldErr = nonEmptyString(wp[key], `${path}/${key}`);
      if (fieldErr) return fieldErr;
    }
    const dependsErr = stringArray(wp.dependsOn, `${path}/dependsOn`);
    if (dependsErr) return dependsErr;
    const contractsErr = stringArray(wp.contractIds, `${path}/contractIds`, { allowEmpty: false });
    if (contractsErr) return contractsErr;
    for (let j = 0; j < wp.contractIds.length; j += 1) {
      if (!contractIds.includes(wp.contractIds[j])) {
        return fail(`${path}/contractIds/${j}`, `unknown contract ${wp.contractIds[j]}`);
      }
    }
    if (!Array.isArray(wp.fileChanges)) return fail(`${path}/fileChanges`, "expected array");
    for (let j = 0; j < wp.fileChanges.length; j += 1) {
      const filePath = `${path}/fileChanges/${j}`;
      const fileErr = exactObject(wp.fileChanges[j], FILE_CHANGE_FIELD_KEYS, filePath);
      if (fileErr) return fileErr;
      const actionErr = enumValue(wp.fileChanges[j].action, `${filePath}/action`, FILE_ACTIONS);
      if (actionErr) return actionErr;
      const relErr = repoRelativePath(wp.fileChanges[j].path, `${filePath}/path`);
      if (relErr) return relErr;
    }
    const stepsErr = stringArray(wp.steps, `${path}/steps`, { allowEmpty: false });
    if (stepsErr) return stepsErr;
    const verErr = stringArray(wp.verificationIds, `${path}/verificationIds`, { allowEmpty: false });
    if (verErr) return verErr;
    workPackageIds.push(wp.id);
  }
  const wpUnique = uniqueStrings(workPackageIds, "/workPackages");
  if (wpUnique) return wpUnique;
  for (let i = 0; i < value.workPackages.length; i += 1) {
    const wp = value.workPackages[i];
    for (let j = 0; j < wp.dependsOn.length; j += 1) {
      if (wp.dependsOn[j] === wp.id) {
        return fail(`/workPackages/${i}/dependsOn/${j}`, "dependsOn must not include self");
      }
      if (!workPackageIds.includes(wp.dependsOn[j])) {
        return fail(`/workPackages/${i}/dependsOn/${j}`, `unknown work package ${wp.dependsOn[j]}`);
      }
    }
  }
  const cycle = findCycle(value.workPackages);
  if (cycle) return fail("/workPackages", `dependsOn cycle: ${cycle.join(" -> ")}`);

  const verificationIds = [];
  for (let i = 0; i < value.verification.length; i += 1) {
    const path = `/verification/${i}`;
    const item = value.verification[i];
    const err = exactObject(item, PLAN_VERIFICATION_FIELD_KEYS, path);
    if (err) return err;
    const idErr = nonEmptyString(item.id, `${path}/id`);
    if (idErr) return idErr;
    const kindErr = enumValue(item.kind, `${path}/kind`, PLAN_CHECK_KINDS);
    if (kindErr) return kindErr;
    if (item.cwd !== "." ) {
      const cwdErr = repoRelativePath(item.cwd, `${path}/cwd`);
      if (cwdErr) return cwdErr;
    }
    const argvErr = stringArray(item.argv, `${path}/argv`, { allowEmpty: false });
    if (argvErr) return argvErr;
    const expectedErr = nonEmptyString(item.expected, `${path}/expected`);
    if (expectedErr) return expectedErr;
    const refsErr = stringArray(item.contractIds, `${path}/contractIds`, { allowEmpty: false });
    if (refsErr) return refsErr;
    for (let j = 0; j < item.contractIds.length; j += 1) {
      if (!contractIds.includes(item.contractIds[j])) {
        return fail(`${path}/contractIds/${j}`, `unknown contract ${item.contractIds[j]}`);
      }
    }
    verificationIds.push(item.id);
  }
  const vUnique = uniqueStrings(verificationIds, "/verification");
  if (vUnique) return vUnique;
  for (let i = 0; i < value.workPackages.length; i += 1) {
    const wp = value.workPackages[i];
    for (let j = 0; j < wp.verificationIds.length; j += 1) {
      if (!verificationIds.includes(wp.verificationIds[j])) {
        return fail(`/workPackages/${i}/verificationIds/${j}`, `unknown verification ${wp.verificationIds[j]}`);
      }
    }
  }

  for (let i = 0; i < value.risks.length; i += 1) {
    const path = `/risks/${i}`;
    const err = exactObject(value.risks[i], RISK_FIELD_KEYS, path);
    if (err) return err;
    const riskErr = nonEmptyString(value.risks[i].risk, `${path}/risk`);
    if (riskErr) return riskErr;
    const mitErr = nonEmptyString(value.risks[i].mitigation, `${path}/mitigation`);
    if (mitErr) return mitErr;
  }

  if (value.outcome === "blocked") {
    if (value.blockingIssues.length === 0) {
      return fail("/blockingIssues", "blocked plans require a non-empty blockingIssues list");
    }
    return ok(value);
  }
  if (value.blockingIssues.length !== 0) {
    return fail("/blockingIssues", "completed plans require blockingIssues=[]");
  }
  if (
    value.requirements.length === 0
    || value.contracts.length === 0
    || value.workPackages.length === 0
    || value.verification.length === 0
  ) {
    return fail("", "completed plans require non-empty requirements, contracts, workPackages, and verification");
  }
  const referencedRequirements = new Set(value.contracts.flatMap((item) => item.requirementIds));
  for (const id of requirementIds) {
    if (!referencedRequirements.has(id)) {
      return fail("/requirements", `requirement ${id} is not referenced by any contract`);
    }
  }
  const wpContracts = new Set(value.workPackages.flatMap((item) => item.contractIds));
  const vContracts = new Set(value.verification.flatMap((item) => item.contractIds));
  for (const id of contractIds) {
    if (!wpContracts.has(id)) return fail("/contracts", `contract ${id} is not covered by any work package`);
    if (!vContracts.has(id)) return fail("/verification", `contract ${id} is not covered by any verification`);
  }
  return ok(value);
}

function findCycle(workPackages) {
  const byId = new Map(workPackages.map((item) => [item.id, item]));
  const visiting = new Set();
  const visited = new Set();
  const stack = [];
  function dfs(id) {
    if (visiting.has(id)) return [...stack.slice(stack.indexOf(id)), id];
    if (visited.has(id)) return null;
    visiting.add(id);
    stack.push(id);
    for (const dep of byId.get(id).dependsOn) {
      const found = dfs(dep);
      if (found) return found;
    }
    stack.pop();
    visiting.delete(id);
    visited.add(id);
    return null;
  }
  for (const item of workPackages) {
    const found = dfs(item.id);
    if (found) return found;
  }
  return null;
}

function validatePlanReviewPayload(value) {
  const objectError = exactObject(value, PLAN_REVIEW_FIELD_KEYS, "");
  if (objectError) return objectError;
  if (value.schema !== PLAN_REVIEW_SCHEMA_ID) return fail("/schema", `expected ${PLAN_REVIEW_SCHEMA_ID}`);
  const verdictErr = enumValue(value.verdict, "/verdict", REVIEW_VERDICTS);
  if (verdictErr) return verdictErr;
  const summaryErr = nonEmptyString(value.summary, "/summary");
  if (summaryErr) return summaryErr;
  if (!Array.isArray(value.findings)) return fail("/findings", "expected array");
  let blocking = 0;
  for (let i = 0; i < value.findings.length; i += 1) {
    const path = `/findings/${i}`;
    const err = exactObject(value.findings[i], PLAN_REVIEW_FINDING_FIELD_KEYS, path);
    if (err) return err;
    const sevErr = enumValue(value.findings[i].severity, `${path}/severity`, ["blocking", "warning"]);
    if (sevErr) return sevErr;
    for (const key of ["location", "problem", "requiredChange"]) {
      const fieldErr = nonEmptyString(value.findings[i][key], `${path}/${key}`);
      if (fieldErr) return fieldErr;
    }
    if (value.findings[i].severity === "blocking") blocking += 1;
  }
  if (value.verdict === "approved" && blocking > 0) {
    return fail("/findings", "approved reviews must not contain blocking findings");
  }
  if (value.verdict !== "approved" && blocking === 0) {
    return fail("/findings", `${value.verdict} reviews require at least one blocking finding`);
  }
  return ok(value);
}

function validateImplementationPayload(value, planPayload) {
  const objectError = exactObject(value, IMPLEMENTATION_FIELD_KEYS, "");
  if (objectError) return objectError;
  if (value.schema !== IMPLEMENTATION_SCHEMA_ID) {
    return fail("/schema", `expected ${IMPLEMENTATION_SCHEMA_ID}`);
  }
  const outcomeErr = enumValue(value.outcome, "/outcome", OUTCOMES);
  if (outcomeErr) return outcomeErr;
  const summaryErr = nonEmptyString(value.summary, "/summary");
  if (summaryErr) return summaryErr;
  const completedErr = stringArray(value.completedWorkPackages, "/completedWorkPackages");
  if (completedErr) return completedErr;
  const uniqueCompleted = uniqueStrings(value.completedWorkPackages, "/completedWorkPackages");
  if (uniqueCompleted) return uniqueCompleted;
  const residualErr = stringArray(value.residualRisks, "/residualRisks");
  if (residualErr) return residualErr;
  const blockersErr = stringArray(value.blockingIssues, "/blockingIssues", { nonEmptyItems: true });
  if (blockersErr) return blockersErr;
  if (!Array.isArray(value.deviations)) return fail("/deviations", "expected array");
  const planIds = Array.isArray(planPayload?.workPackages)
    ? planPayload.workPackages.map((item) => item.id)
    : null;
  if (!planIds) return fail("/completedWorkPackages", "canonical plan payload is required");
  for (let i = 0; i < value.completedWorkPackages.length; i += 1) {
    if (!planIds.includes(value.completedWorkPackages[i])) {
      return fail(`/completedWorkPackages/${i}`, `unknown work package ${value.completedWorkPackages[i]}`);
    }
  }
  for (let i = 0; i < value.deviations.length; i += 1) {
    const path = `/deviations/${i}`;
    const err = exactObject(value.deviations[i], DEVIATION_FIELD_KEYS, path);
    if (err) return err;
    const wpErr = nonEmptyString(value.deviations[i].workPackageId, `${path}/workPackageId`);
    if (wpErr) return wpErr;
    const sumErr = nonEmptyString(value.deviations[i].summary, `${path}/summary`);
    if (sumErr) return sumErr;
    if (!planIds.includes(value.deviations[i].workPackageId)) {
      return fail(`${path}/workPackageId`, `unknown work package ${value.deviations[i].workPackageId}`);
    }
  }
  if (value.outcome === "completed") {
    if (value.blockingIssues.length !== 0) {
      return fail("/blockingIssues", "completed implementations require blockingIssues=[]");
    }
    if (value.completedWorkPackages.length !== planIds.length
      || planIds.some((id) => !value.completedWorkPackages.includes(id))) {
      return fail("/completedWorkPackages", "completed implementations must cover every planned work package");
    }
  } else if (value.blockingIssues.length === 0) {
    return fail("/blockingIssues", "blocked implementations require a non-empty blockingIssues list");
  }
  return ok(value);
}

function validateDirectImplementationPayload(value) {
  const objectError = exactObject(value, DIRECT_IMPLEMENTATION_FIELD_KEYS, "");
  if (objectError) return objectError;
  if (value.schema !== DIRECT_IMPLEMENTATION_SCHEMA_ID) {
    return fail("/schema", `expected ${DIRECT_IMPLEMENTATION_SCHEMA_ID}`);
  }
  const outcomeErr = enumValue(value.outcome, "/outcome", OUTCOMES);
  if (outcomeErr) return outcomeErr;
  const summaryErr = nonEmptyString(value.summary, "/summary");
  if (summaryErr) return summaryErr;
  const residualErr = stringArray(value.residualRisks, "/residualRisks");
  if (residualErr) return residualErr;
  const blockersErr = stringArray(value.blockingIssues, "/blockingIssues", { nonEmptyItems: true });
  if (blockersErr) return blockersErr;
  if (value.outcome === "completed") {
    if (value.blockingIssues.length !== 0) {
      return fail("/blockingIssues", "completed direct implementations require blockingIssues=[]");
    }
  } else if (value.blockingIssues.length === 0) {
    return fail("/blockingIssues", "blocked direct implementations require a non-empty blockingIssues list");
  }
  return ok(value);
}

function validateExecuteReviewPayload(value) {
  const objectError = exactObject(value, EXECUTE_REVIEW_FIELD_KEYS, "");
  if (objectError) return objectError;
  if (value.schema !== EXECUTE_REVIEW_SCHEMA_ID) {
    return fail("/schema", `expected ${EXECUTE_REVIEW_SCHEMA_ID}`);
  }
  const verdictErr = enumValue(value.verdict, "/verdict", REVIEW_VERDICTS);
  if (verdictErr) return verdictErr;
  const summaryErr = nonEmptyString(value.summary, "/summary");
  if (summaryErr) return summaryErr;
  const coverageErr = stringArray(value.acceptanceCoverage, "/acceptanceCoverage");
  if (coverageErr) return coverageErr;
  if (!Array.isArray(value.findings)) return fail("/findings", "expected array");
  let blocking = 0;
  for (let i = 0; i < value.findings.length; i += 1) {
    const path = `/findings/${i}`;
    const item = value.findings[i];
    const err = exactObject(item, EXECUTE_REVIEW_FINDING_FIELD_KEYS, path);
    if (err) return err;
    const sevErr = enumValue(item.severity, `${path}/severity`, ["blocking", "warning"]);
    if (sevErr) return sevErr;
    const fileErr = repoRelativePath(item.file, `${path}/file`);
    if (fileErr) return fileErr;
    const lineErr = integerInRange(item.line, `${path}/line`, 0, Number.MAX_SAFE_INTEGER);
    if (lineErr) return lineErr;
    for (const key of ["problem", "requiredChange"]) {
      const fieldErr = nonEmptyString(item[key], `${path}/${key}`);
      if (fieldErr) return fieldErr;
    }
    if (item.severity === "blocking") blocking += 1;
  }
  if (value.verdict === "approved" && blocking > 0) {
    return fail("/findings", "approved reviews must not contain blocking findings");
  }
  if (value.verdict !== "approved" && blocking === 0) {
    return fail("/findings", `${value.verdict} reviews require at least one blocking finding`);
  }
  return ok(value);
}

export function validateResult(value) {
  const objectError = exactObject(value, RESULT_FIELD_KEYS, "", ["resolvedModel"]);
  if (objectError) return objectError;
  if (value.schema !== RESULT_SCHEMA_ID) return fail("/schema", `expected ${RESULT_SCHEMA_ID}`);
  const statusErr = enumValue(value.status, "/status", RESULT_STATUSES);
  if (statusErr) return statusErr;
  const adapterErr = enumValue(value.adapter, "/adapter", ADAPTERS);
  if (adapterErr) return adapterErr;
  if (Object.hasOwn(value, "resolvedModel") && value.resolvedModel !== null) {
    const resolvedErr = nonEmptyString(value.resolvedModel, "/resolvedModel");
    if (resolvedErr) return resolvedErr;
  }
  const completed = value.status === "completed";
  for (const key of ["jobId", "idempotencyKey", "taskId"]) {
    const err = nullableIdentity(value[key], `/${key}`, { allowNull: !completed });
    if (err) return err;
  }
  if (value.stage === null) {
    if (completed) return fail("/stage", "completed results require a stage");
  } else {
    const stageErr = enumValue(value.stage, "/stage", STAGES);
    if (stageErr) return stageErr;
  }
  const shaErr = sha256Digest(value.jobSha256, "/jobSha256");
  if (shaErr) return shaErr;
  if (completed) {
    const sessionErr = nonEmptyString(value.sessionId, "/sessionId");
    if (sessionErr) return sessionErr;
  } else if (value.sessionId !== null) {
    const sessionErr = nonEmptyString(value.sessionId, "/sessionId");
    if (sessionErr) return sessionErr;
  }
  const startedErr = isoTimestamp(value.startedAt, "/startedAt");
  if (startedErr) return startedErr;
  const finishedErr = isoTimestamp(value.finishedAt, "/finishedAt");
  if (finishedErr) return finishedErr;

  if (value.structuredOutput === null) {
    if (completed) return fail("/structuredOutput", "completed results require structuredOutput");
  } else {
    const soErr = exactObject(value.structuredOutput, STRUCTURED_OUTPUT_FIELD_KEYS, "/structuredOutput");
    if (soErr) return soErr;
    const kindErr = enumValue(value.structuredOutput.kind, "/structuredOutput/kind", OUTPUT_KINDS);
    if (kindErr) return kindErr;
    if (!isPlainObject(value.structuredOutput.payload)) {
      return fail("/structuredOutput/payload", "expected object");
    }
  }

  if (!Array.isArray(value.artifacts)) return fail("/artifacts", "expected array");
  for (let i = 0; i < value.artifacts.length; i += 1) {
    const path = `/artifacts/${i}`;
    const err = exactObject(value.artifacts[i], ARTIFACT_ENTRY_FIELD_KEYS, path);
    if (err) return err;
    const kindErr = enumValue(
      value.artifacts[i].kind,
      `${path}/kind`,
      [...OUTPUT_KINDS, "plan-markdown"],
    );
    if (kindErr) return kindErr;
    const pathErr = absolutePath(value.artifacts[i].path, `${path}/path`);
    if (pathErr) return pathErr;
    const hashErr = sha256Digest(value.artifacts[i].sha256, `${path}/sha256`);
    if (hashErr) return hashErr;
    const schemaErr = nonEmptyString(value.artifacts[i].schema, `${path}/schema`);
    if (schemaErr) return schemaErr;
    const canonicalErr = booleanValue(value.artifacts[i].canonical, `${path}/canonical`);
    if (canonicalErr) return canonicalErr;
  }

  const touchedErr = stringArray(value.touchedFiles, "/touchedFiles", { nonEmptyItems: true });
  if (touchedErr) return touchedErr;
  if (!Array.isArray(value.checks)) return fail("/checks", "expected array");
  for (let i = 0; i < value.checks.length; i += 1) {
    const path = `/checks/${i}`;
    const err = exactObject(value.checks[i], CHECK_RESULT_FIELD_KEYS, path);
    if (err) return err;
    const idErr = nonEmptyString(value.checks[i].id, `${path}/id`);
    if (idErr) return idErr;
    const statusCheck = enumValue(value.checks[i].status, `${path}/status`, CHECK_STATUSES);
    if (statusCheck) return statusCheck;
    const argvErr = stringArray(value.checks[i].argv, `${path}/argv`, { allowEmpty: false });
    if (argvErr) return argvErr;
    const cwdErr = absolutePath(value.checks[i].cwd, `${path}/cwd`);
    if (cwdErr) return cwdErr;
    const expectedErr = integerInRange(value.checks[i].expectedExitCode, `${path}/expectedExitCode`, 0, 255);
    if (expectedErr) return expectedErr;
    if (value.checks[i].exitCode !== null) {
      const exitErr = integerInRange(value.checks[i].exitCode, `${path}/exitCode`, 0, 255);
      if (exitErr) return exitErr;
    }
    if (value.checks[i].signal !== null) {
      const signalErr = nonEmptyString(value.checks[i].signal, `${path}/signal`);
      if (signalErr) return signalErr;
    }
    const started = isoTimestamp(value.checks[i].startedAt, `${path}/startedAt`);
    if (started) return started;
    const finished = isoTimestamp(value.checks[i].finishedAt, `${path}/finishedAt`);
    if (finished) return finished;
    const stdoutErr = absolutePath(value.checks[i].stdoutPath, `${path}/stdoutPath`);
    if (stdoutErr) return stdoutErr;
    const stderrErr = absolutePath(value.checks[i].stderrPath, `${path}/stderrPath`);
    if (stderrErr) return stderrErr;
  }
  if (!isPlainObject(value.usage)) return fail("/usage", "expected object");

  const wsErr = exactObject(value.workspace, RESULT_WORKSPACE_FIELD_KEYS, "/workspace");
  if (wsErr) return wsErr;
  const repoErr = absolutePath(value.workspace.repoRoot, "/workspace/repoRoot");
  if (repoErr) return repoErr;
  for (const key of ["branchBefore", "branchAfter"]) {
    const err = nonEmptyString(value.workspace[key], `/workspace/${key}`);
    if (err) return err;
  }
  for (const key of ["headBefore", "headAfter"]) {
    const err = gitHead(value.workspace[key], `/workspace/${key}`);
    if (err) return err;
  }
  for (const key of ["snapshotBeforeSha256", "snapshotAfterSha256"]) {
    const err = sha256Digest(value.workspace[key], `/workspace/${key}`);
    if (err) return err;
  }

  if (value.error === null) {
    if (!completed && value.status !== "unavailable") {
      // failed/timed_out/aborted should carry a typed error; unavailable may too.
    }
  } else {
    const errObj = exactObject(value.error, ERROR_OBJECT_FIELD_KEYS, "/error");
    if (errObj) return errObj;
    if (!ERROR_KINDS.has(value.error.kind)) return fail("/error/kind", "unknown error kind");
    const msgErr = nonEmptyString(value.error.message, "/error/message");
    if (msgErr) return msgErr;
    if (!isPlainObject(value.error.details)) return fail("/error/details", "expected object");
  }
  if (completed && value.error !== null) {
    return fail("/error", "completed results require error=null");
  }
  if (!completed && value.error === null && value.status !== "unavailable") {
    return fail("/error", "non-completed results require a typed error");
  }

  const pathsErr = exactObject(value.paths, RESULT_PATHS_FIELD_KEYS, "/paths");
  if (pathsErr) return pathsErr;
  for (const key of ["events", "stderr", "final"]) {
    const err = absolutePath(value.paths[key], `/paths/${key}`);
    if (err) return err;
  }
  if (!Array.isArray(value.paths.adapterRuns)) return fail("/paths/adapterRuns", "expected array");
  for (let i = 0; i < value.paths.adapterRuns.length; i += 1) {
    const path = `/paths/adapterRuns/${i}`;
    const err = exactObject(value.paths.adapterRuns[i], ADAPTER_RUN_FIELD_KEYS, path);
    if (err) return err;
    const phaseErr = enumValue(value.paths.adapterRuns[i].phase, `${path}/phase`, ["primary", "output-recovery"]);
    if (phaseErr) return phaseErr;
    for (const key of ["result", "events", "stderr", "final"]) {
      const fieldErr = absolutePath(value.paths.adapterRuns[i][key], `${path}/${key}`);
      if (fieldErr) return fieldErr;
    }
  }
  return ok(value);
}
