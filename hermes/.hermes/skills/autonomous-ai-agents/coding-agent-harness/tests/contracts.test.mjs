import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SCHEMA_DIR = join(ROOT, "schemas");

const {
  ADAPTER_RUN_FIELD_KEYS,
  ARTIFACT_ENTRY_FIELD_KEYS,
  ARTIFACT_FIELD_KEYS,
  ARTIFACT_JOB_FIELD_KEYS,
  ARTIFACT_SCHEMA_ID,
  ARTIFACT_WORKSPACE_FIELD_KEYS,
  CHECK_RESULT_FIELD_KEYS,
  CHECK_STATUSES,
  ERROR_KINDS,
  ERROR_OBJECT_FIELD_KEYS,
  JOB_SCHEMA_ID,
  OUTPUT_KINDS,
  RESULT_PATHS_FIELD_KEYS,
  RESULT_SCHEMA_ID,
  RESULT_WORKSPACE_FIELD_KEYS,
  STAGE_CONTRACTS,
  STAGES,
  STRUCTURED_OUTPUT_FIELD_KEYS,
  SUBMIT_TOOLS,
  parseCanonicalArtifact,
  typedError,
  validateArtifact,
  validateJob,
  validatePayload,
  validateResult,
  JOB_FIELD_KEYS,
  RESULT_FIELD_KEYS,
  PLAN_FIELD_KEYS,
  PLAN_REVIEW_FIELD_KEYS,
  IMPLEMENTATION_FIELD_KEYS,
  DIRECT_IMPLEMENTATION_FIELD_KEYS,
  EXECUTE_REVIEW_FIELD_KEYS,
} = await import("../src/contracts.mjs");

function clone(value) {
  return structuredClone(value);
}

function setPath(target, path, value) {
  const parts = path.replace(/^\//, "").split("/");
  let cursor = target;
  for (let i = 0; i < parts.length - 1; i += 1) {
    cursor = cursor[parts[i]];
  }
  cursor[parts[parts.length - 1]] = value;
  return target;
}

function deletePath(target, path) {
  const parts = path.replace(/^\//, "").split("/");
  let cursor = target;
  for (let i = 0; i < parts.length - 1; i += 1) {
    cursor = cursor[parts[i]];
  }
  delete cursor[parts[parts.length - 1]];
  return target;
}

function validPlanJob() {
  return {
    schema: JOB_SCHEMA_ID,
    jobId: "job_456",
    idempotencyKey: "task_123:plan:1",
    taskId: "task_123",
    stage: "plan",
    attempt: 1,
    workspace: {
      repoRoot: "/abs/repo",
      branch: "main",
      expectedHead: "a".repeat(40),
      requireCleanAtStart: true,
    },
    agent: {
      adapter: "pi",
      profile: "planner",
      model: "zai-coding-cn/glm-5.3",
      thinking: "high",
      sessionId: null,
    },
    permissions: { mode: "read-only" },
    inputs: [
      { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
    ],
    expectedOutput: { kind: "plan", schema: "plan.v1" },
    verification: [],
    limits: { timeoutSeconds: null },
  };
}

function validPlanReviewJob() {
  const job = validPlanJob();
  job.jobId = "job_review";
  job.idempotencyKey = "task_123:plan_review:1";
  job.stage = "plan_review";
  job.agent.profile = "plan-reviewer";
  job.inputs = [
    { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
    { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
  ];
  job.expectedOutput = { kind: "plan-review", schema: "plan-review.v1" };
  return job;
}

function validImplementJob() {
  const job = validPlanJob();
  job.jobId = "job_impl";
  job.idempotencyKey = "task_123:implement:1";
  job.stage = "implement";
  job.agent.profile = "implementer";
  job.agent.model = "kimi-coding/k3";
  job.permissions.mode = "write";
  job.inputs = [
    { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
  ];
  job.expectedOutput = { kind: "implementation", schema: "implementation.v1" };
  job.verification = [
    {
      id: "check-unit",
      argv: ["node", "--test", "tests/unit.test.mjs"],
      cwd: "/abs/repo",
      timeoutSeconds: 120,
      expectedExitCode: 0,
    },
  ];
  return job;
}

function validExecuteReviewJob() {
  const job = validPlanJob();
  job.jobId = "job_exec_review";
  job.idempotencyKey = "task_123:execute_review:1";
  job.stage = "execute_review";
  job.agent.profile = "execute-reviewer";
  job.inputs = [
    { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
    { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
    { kind: "implementation", path: "/abs/implementation.json", sha256: "d".repeat(64) },
  ];
  job.expectedOutput = { kind: "execute-review", schema: "execute-review.v1" };
  return job;
}

function validDirectImplementJob() {
  const job = validPlanJob();
  job.jobId = "job_direct";
  job.idempotencyKey = "task_123:direct_implement:1";
  job.stage = "direct_implement";
  job.agent.profile = "implementer";
  job.agent.model = "kimi-coding/k3";
  job.permissions.mode = "write";
  job.inputs = [
    { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
  ];
  job.expectedOutput = { kind: "direct-implementation", schema: "direct-implementation.v1" };
  job.verification = [
    {
      id: "check-unit",
      argv: ["node", "--test", "tests/unit.test.mjs"],
      cwd: "/abs/repo",
      timeoutSeconds: 120,
      expectedExitCode: 0,
    },
  ];
  return job;
}

function validPlanPayload() {
  return {
    schema: "plan.v1",
    outcome: "completed",
    title: "Greet helper",
    goal: "Add a greet function",
    architecture: "Single module plus unit test",
    techStack: ["Node.js"],
    requirements: [{ id: "R1", text: "greet returns a greeting" }],
    contracts: [
      { id: "C1", requirementIds: ["R1"], text: "greet(name) returns Hello, name" },
    ],
    workPackages: [
      {
        id: "WP-01",
        title: "Implement greet",
        objective: "Add greet and a test",
        dependsOn: [],
        contractIds: ["C1"],
        fileChanges: [{ action: "modify", path: "src/greet.mjs" }],
        steps: ["Write greet", "Write test"],
        verificationIds: ["V1"],
      },
    ],
    verification: [
      {
        id: "V1",
        kind: "focused",
        cwd: ".",
        argv: ["node", "--test", "test/greet.test.mjs"],
        expected: "tests pass",
        contractIds: ["C1"],
      },
    ],
    risks: [{ risk: "none material", mitigation: "keep scope tiny" }],
    blockingIssues: [],
  };
}

function validPlanReviewPayload() {
  return {
    schema: "plan-review.v1",
    verdict: "approved",
    summary: "Plan is complete.",
    findings: [],
  };
}

function validImplementationPayload() {
  return {
    schema: "implementation.v1",
    outcome: "completed",
    summary: "Implemented greet.",
    completedWorkPackages: ["WP-01"],
    deviations: [],
    residualRisks: [],
    blockingIssues: [],
  };
}

function validDirectImplementationPayload() {
  return {
    schema: "direct-implementation.v1",
    outcome: "completed",
    summary: "Implemented the requirement.",
    residualRisks: [],
    blockingIssues: [],
  };
}

function validExecuteReviewPayload() {
  return {
    schema: "execute-review.v1",
    verdict: "approved",
    summary: "Implementation matches the plan.",
    findings: [],
    acceptanceCoverage: ["C1: covered by greet test"],
  };
}

function validPlanArtifact() {
  return {
    schema: ARTIFACT_SCHEMA_ID,
    kind: "plan",
    job: {
      jobId: "job_plan",
      idempotencyKey: "task_123:plan:1",
      taskId: "task_123",
      stage: "plan",
      attempt: 1,
      jobSha256: "c".repeat(64),
    },
    sessionId: "sess-plan",
    inputs: [
      { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
    ],
    workspace: {
      repoRoot: "/abs/repo",
      branch: "main",
      head: "a".repeat(40),
      baselineSnapshotSha256: "d".repeat(64),
    },
    payload: validPlanPayload(),
  };
}

function validImplementationArtifact(planPayload = validPlanPayload()) {
  return {
    schema: ARTIFACT_SCHEMA_ID,
    kind: "implementation",
    job: {
      jobId: "job_impl",
      idempotencyKey: "task_123:implement:1",
      taskId: "task_123",
      stage: "implement",
      attempt: 1,
      jobSha256: "e".repeat(64),
    },
    sessionId: "sess-impl",
    inputs: [
      { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
    ],
    workspace: {
      repoRoot: "/abs/repo",
      branch: "main",
      head: "a".repeat(40),
      baselineSnapshotSha256: "d".repeat(64),
    },
    payload: validImplementationPayload(),
  };
}

function validCompletedResult() {
  return {
    schema: RESULT_SCHEMA_ID,
    jobId: "job_456",
    idempotencyKey: "task_123:plan:1",
    jobSha256: "e".repeat(64),
    taskId: "task_123",
    stage: "plan",
    status: "completed",
    adapter: "pi",
    sessionId: "sess-1",
    startedAt: "2026-09-14T00:00:00.000Z",
    finishedAt: "2026-09-14T00:01:00.000Z",
    structuredOutput: { kind: "plan", payload: validPlanPayload() },
    artifacts: [
      {
        kind: "plan",
        path: "/abs/out/artifacts/plan-attempt-1.json",
        sha256: "f".repeat(64),
        schema: "coding-agent.artifact.v1",
        canonical: true,
      },
    ],
    touchedFiles: [],
    checks: [],
    usage: {},
    workspace: {
      repoRoot: "/abs/repo",
      branchBefore: "main",
      branchAfter: "main",
      headBefore: "a".repeat(40),
      headAfter: "a".repeat(40),
      snapshotBeforeSha256: "1".repeat(64),
      snapshotAfterSha256: "1".repeat(64),
    },
    error: null,
    paths: {
      events: "/abs/out/events.jsonl",
      stderr: "/abs/out/stderr.log",
      final: "/abs/out/final.txt",
      adapterRuns: [
        {
          phase: "primary",
          result: "/abs/out/adapter/primary/result.json",
          events: "/abs/out/adapter/primary/events.jsonl",
          stderr: "/abs/out/adapter/primary/stderr.txt",
          final: "/abs/out/adapter/primary/final.txt",
        },
      ],
    },
  };
}

function assertInvalidJob(value, expectedPath) {
  const result = validateJob(value);
  assert.equal(result.ok, false, `expected invalid job at ${expectedPath}`);
  assert.equal(result.error.kind, "invalid_job");
  assert.equal(result.error.path, expectedPath);
  assert.equal(typeof result.error.message, "string");
  assert.ok(result.error.message.length > 0);
}

function loadSchema(name) {
  return JSON.parse(readFileSync(join(SCHEMA_DIR, name), "utf8"));
}

test("valid fixtures for every stage pass without repair", () => {
  for (const job of [
    validPlanJob(),
    validPlanReviewJob(),
    validImplementJob(),
    validExecuteReviewJob(),
    validDirectImplementJob(),
  ]) {
    const original = clone(job);
    const result = validateJob(job);
    assert.equal(result.ok, true, result.error && result.error.message);
    assert.deepEqual(job, original);
    assert.deepEqual(result.value, original);
  }
});

test("stage matrix rejects mismatched profile, mode, output, and session", () => {
  const cases = [
    { mutate: (job) => setPath(job, "/agent/profile", "implementer"), path: "/agent/profile" },
    { mutate: (job) => setPath(job, "/permissions/mode", "write"), path: "/permissions/mode" },
    { mutate: (job) => setPath(job, "/expectedOutput/kind", "implementation"), path: "/expectedOutput" },
    { mutate: (job) => setPath(job, "/expectedOutput/schema", "implementation.v1"), path: "/expectedOutput" },
    { mutate: (job) => setPath(job, "/stage", "not-a-stage"), path: "/stage" },
  ];
  for (const item of cases) {
    assertInvalidJob(item.mutate(validPlanJob()), item.path);
  }
  assertInvalidJob(setPath(validPlanReviewJob(), "/agent/sessionId", "sess-1"), "/agent/sessionId");
  assertInvalidJob(setPath(validExecuteReviewJob(), "/agent/sessionId", "sess-1"), "/agent/sessionId");
});

test("reviewer jobs may resume only as null sessionId; planner/implementer may resume", () => {
  const planner = setPath(validPlanJob(), "/agent/sessionId", "sess-plan");
  assert.equal(validateJob(planner).ok, true);
  const implementer = setPath(validImplementJob(), "/agent/sessionId", "sess-impl");
  assert.equal(validateJob(implementer).ok, true);
  const direct = setPath(validDirectImplementJob(), "/agent/sessionId", "sess-direct");
  assert.equal(validateJob(direct).ok, true);
});

test("verification is allowed only on implement and must be unique and well-formed", () => {
  assertInvalidJob(
    setPath(validPlanJob(), "/verification", [{
      id: "check-unit",
      argv: ["node", "--test"],
      cwd: "/abs/repo",
      timeoutSeconds: 10,
      expectedExitCode: 0,
    }]),
    "/verification",
  );
  const missingId = validImplementJob();
  missingId.verification.push({
    id: "check-unit",
    argv: ["node", "--test"],
    cwd: "/abs/repo",
    timeoutSeconds: 10,
    expectedExitCode: 0,
  });
  assertInvalidJob(missingId, "/verification/1/id");
  const emptyArgv = validImplementJob();
  emptyArgv.verification[0].argv = [];
  assertInvalidJob(emptyArgv, "/verification/0/argv");
  const relativeCwd = validImplementJob();
  relativeCwd.verification[0].cwd = "src";
  assertInvalidJob(relativeCwd, "/verification/0/cwd");
  const escapedCwd = validImplementJob();
  escapedCwd.verification[0].cwd = "/abs/elsewhere";
  assertInvalidJob(escapedCwd, "/verification/0/cwd");
});

test("input cardinality, uniqueness, hashes, and absolute paths fail closed", () => {
  assertInvalidJob(setPath(validPlanJob(), "/inputs", []), "/inputs");
  const twoPlans = validPlanReviewJob();
  twoPlans.inputs.push({ kind: "plan", path: "/abs/plan-2.json", sha256: "9".repeat(64) });
  assertInvalidJob(twoPlans, "/inputs");
  const missingRequirement = validExecuteReviewJob();
  missingRequirement.inputs = missingRequirement.inputs.filter((item) => item.kind !== "requirement");
  assertInvalidJob(missingRequirement, "/inputs");
  const duplicatePath = validPlanReviewJob();
  duplicatePath.inputs[1].path = duplicatePath.inputs[0].path;
  assertInvalidJob(duplicatePath, "/inputs/1/path");
  assertInvalidJob(setPath(validPlanJob(), "/inputs/0/path", "relative.md"), "/inputs/0/path");
  assertInvalidJob(setPath(validPlanJob(), "/inputs/0/sha256", "deadbeef"), "/inputs/0/sha256");
  assertInvalidJob(setPath(validPlanJob(), "/workspace/expectedHead", "not-a-sha"), "/workspace/expectedHead");
  assertInvalidJob(setPath(validPlanJob(), "/workspace/repoRoot", "repo"), "/workspace/repoRoot");
});

test("unknown fields, empty identity, and bad model fail with invalid_job", () => {
  assertInvalidJob(setPath(validPlanJob(), "/extra", true), "/extra");
  assertInvalidJob(setPath(validPlanJob(), "/workspace/extra", true), "/workspace/extra");
  assertInvalidJob(setPath(validPlanJob(), "/jobId", ""), "/jobId");
  assertInvalidJob(setPath(validPlanJob(), "/agent/model", "glm-5.3"), "/agent/model");
  assertInvalidJob(setPath(validPlanJob(), "/agent/model", "bad model"), "/agent/model");
  assertInvalidJob(setPath(validPlanJob(), "/agent/thinking", "turbo"), "/agent/thinking");
  assertInvalidJob(setPath(validPlanJob(), "/agent/adapter", "codex"), "/agent/adapter");
  assertInvalidJob(deletePath(validPlanJob(), "/limits/timeoutSeconds"), "/limits");
});

test("typedError factory is stable and error kinds cover the protocol set", () => {
  const error = typedError("invalid_job", "/stage", "bad stage");
  assert.deepEqual(error, { kind: "invalid_job", path: "/stage", message: "bad stage" });
  for (const kind of [
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
    "aborted",
    "timed_out",
  ]) {
    assert.ok(ERROR_KINDS.has(kind), kind);
  }
});

test("submit tool names and stage contracts are exact", () => {
  assert.deepEqual([...STAGES], ["plan", "plan_review", "implement", "execute_review", "direct_implement"]);
  assert.deepEqual(SUBMIT_TOOLS, {
    plan: "submit_plan",
    plan_review: "submit_plan_review",
    implement: "submit_implementation",
    execute_review: "submit_execute_review",
    direct_implement: "submit_direct_implementation",
  });
  assert.equal(STAGE_CONTRACTS.plan.profile, "planner");
  assert.equal(STAGE_CONTRACTS.plan.permission, "read-only");
  assert.equal(STAGE_CONTRACTS.implement.permission, "write");
  assert.equal(STAGE_CONTRACTS.plan_review.session, "fresh");
  assert.equal(STAGE_CONTRACTS.execute_review.session, "fresh");
  assert.equal(STAGE_CONTRACTS.direct_implement.profile, "implementer");
  assert.equal(STAGE_CONTRACTS.direct_implement.permission, "write");
  assert.equal(STAGE_CONTRACTS.direct_implement.outputKind, "direct-implementation");
  assert.equal(STAGE_CONTRACTS.direct_implement.outputSchema, "direct-implementation.v1");
  assert.equal(STAGE_CONTRACTS.direct_implement.submitTool, "submit_direct_implementation");
  assert.equal(STAGE_CONTRACTS.direct_implement.session, "fresh_or_resume");
  assert.equal(STAGE_CONTRACTS.direct_implement.verificationAllowed, true);
  assert.equal(STAGE_CONTRACTS.direct_implement.verificationRequired, true);
});

test("direct_implement requires requirement-only input, non-empty checks, and typed payload", () => {
  const okJob = validateJob(validDirectImplementJob());
  assert.equal(okJob.ok, true, okJob.error && okJob.error.message);

  const emptyChecks = validDirectImplementJob();
  emptyChecks.verification = [];
  assertInvalidJob(emptyChecks, "/verification");

  const withPlan = validDirectImplementJob();
  withPlan.inputs = [
    { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
    { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
  ];
  assertInvalidJob(withPlan, "/inputs");

  const planOnly = validDirectImplementJob();
  planOnly.inputs = [{ kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) }];
  assertInvalidJob(planOnly, "/inputs");

  const okPayload = validatePayload("direct-implementation", validDirectImplementationPayload());
  assert.equal(okPayload.ok, true, okPayload.error && okPayload.error.message);

  const completedWithBlockers = validDirectImplementationPayload();
  completedWithBlockers.blockingIssues = ["still blocked"];
  assert.equal(validatePayload("direct-implementation", completedWithBlockers).ok, false);

  const blockedEmpty = validDirectImplementationPayload();
  blockedEmpty.outcome = "blocked";
  assert.equal(validatePayload("direct-implementation", blockedEmpty).ok, false);

  const blockedOk = validDirectImplementationPayload();
  blockedOk.outcome = "blocked";
  blockedOk.blockingIssues = ["cannot proceed"];
  assert.equal(validatePayload("direct-implementation", blockedOk).ok, true);

  const extraField = validDirectImplementationPayload();
  extraField.completedWorkPackages = ["WP-01"];
  assert.equal(validatePayload("direct-implementation", extraField).ok, false);
});

test("coding-agent-job.v1 JSON Schema encodes direct_implement stage semantics", () => {
  const schema = loadSchema("coding-agent-job.v1.schema.json");
  const valid = validDirectImplementJob();
  assert.equal(validateJob(valid).ok, true);
  assert.equal(schemaAccepts(schema, valid), true);

  const cases = [
    (() => {
      const job = validDirectImplementJob();
      job.verification = [];
      return job;
    })(),
    (() => {
      const job = validDirectImplementJob();
      job.inputs = [
        { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
        { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
      ];
      return job;
    })(),
    (() => {
      const job = validDirectImplementJob();
      job.inputs = [{ kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) }];
      return job;
    })(),
    (() => {
      const job = validDirectImplementJob();
      job.agent.profile = "planner";
      return job;
    })(),
    (() => {
      const job = validDirectImplementJob();
      job.permissions.mode = "read-only";
      return job;
    })(),
    (() => {
      const job = validDirectImplementJob();
      job.expectedOutput = { kind: "implementation", schema: "implementation.v1" };
      return job;
    })(),
  ];
  for (const job of cases) {
    assert.equal(validateJob(job).ok, false, JSON.stringify(job));
    assert.equal(schemaAccepts(schema, job), false, JSON.stringify(job));
  }

  const plan = validPlanJob();
  assert.equal(validateJob(plan).ok, true);
  assert.equal(schemaAccepts(schema, plan), true);
});

test("direct-implementation JSON Schema matches runtime outcome and non-empty string rules", () => {
  const schema = loadSchema("direct-implementation.v1.schema.json");
  const completed = validDirectImplementationPayload();
  assert.equal(validatePayload("direct-implementation", completed).ok, true);
  assert.equal(schemaAccepts(schema, completed), true);

  const blockedOk = validDirectImplementationPayload();
  blockedOk.outcome = "blocked";
  blockedOk.blockingIssues = ["cannot proceed"];
  assert.equal(validatePayload("direct-implementation", blockedOk).ok, true);
  assert.equal(schemaAccepts(schema, blockedOk), true);

  const invalids = [
    (() => {
      const payload = validDirectImplementationPayload();
      payload.blockingIssues = ["still blocked"];
      return payload;
    })(),
    (() => {
      const payload = validDirectImplementationPayload();
      payload.outcome = "blocked";
      return payload;
    })(),
    (() => {
      const payload = validDirectImplementationPayload();
      payload.summary = "";
      return payload;
    })(),
    (() => {
      const payload = validDirectImplementationPayload();
      payload.residualRisks = [""];
      return payload;
    })(),
    (() => {
      const payload = validDirectImplementationPayload();
      payload.outcome = "blocked";
      payload.blockingIssues = [""];
      return payload;
    })(),
  ];
  for (const payload of invalids) {
    assert.equal(validatePayload("direct-implementation", payload).ok, false, JSON.stringify(payload));
    assert.equal(schemaAccepts(schema, payload), false, JSON.stringify(payload));
  }
});

test("plan payload graph, coverage, and path rules", () => {
  const ok = validatePayload("plan", validPlanPayload());
  assert.equal(ok.ok, true, ok.error && ok.error.message);
  const blocked = validPlanPayload();
  blocked.outcome = "blocked";
  blocked.blockingIssues = ["need product owner"];
  blocked.workPackages = [];
  blocked.verification = [];
  blocked.contracts = [];
  blocked.requirements = [];
  assert.equal(validatePayload("plan", blocked).ok, true);

  const completedWithBlockers = validPlanPayload();
  completedWithBlockers.blockingIssues = ["still blocked"];
  assert.equal(validatePayload("plan", completedWithBlockers).ok, false);
  assert.equal(validatePayload("plan", completedWithBlockers).error.kind, "invalid_job");

  const cycle = validPlanPayload();
  cycle.workPackages.push({
    id: "WP-02",
    title: "Second",
    objective: "depends on self cycle",
    dependsOn: ["WP-01"],
    contractIds: ["C1"],
    fileChanges: [{ action: "create", path: "src/other.mjs" }],
    steps: ["do it"],
    verificationIds: ["V1"],
  });
  cycle.workPackages[0].dependsOn = ["WP-02"];
  assert.equal(validatePayload("plan", cycle).ok, false);
  assert.match(validatePayload("plan", cycle).error.path, /dependsOn|workPackages/);

  const absPath = validPlanPayload();
  absPath.workPackages[0].fileChanges[0].path = "/etc/passwd";
  assert.equal(validatePayload("plan", absPath).ok, false);
  assert.equal(validatePayload("plan", absPath).error.path, "/workPackages/0/fileChanges/0/path");

  const uncovered = validPlanPayload();
  uncovered.requirements.push({ id: "R2", text: "orphan" });
  assert.equal(validatePayload("plan", uncovered).ok, false);
});

test("review and implementation cross-field rules", () => {
  assert.equal(validatePayload("plan-review", validPlanReviewPayload()).ok, true);
  const approvedBlocking = validPlanReviewPayload();
  approvedBlocking.findings = [{
    severity: "blocking",
    location: "architecture",
    problem: "missing",
    requiredChange: "add it",
  }];
  assert.equal(validatePayload("plan-review", approvedBlocking).ok, false);

  const requestChanges = validPlanReviewPayload();
  requestChanges.verdict = "request_changes";
  requestChanges.findings = approvedBlocking.findings;
  assert.equal(validatePayload("plan-review", requestChanges).ok, true);

  const impl = validatePayload("implementation", validImplementationPayload(), {
    planPayload: validPlanPayload(),
  });
  assert.equal(impl.ok, true, impl.error && impl.error.message);
  const incomplete = validImplementationPayload();
  incomplete.completedWorkPackages = [];
  assert.equal(validatePayload("implementation", incomplete, { planPayload: validPlanPayload() }).ok, false);

  const blockedImpl = validImplementationPayload();
  blockedImpl.outcome = "blocked";
  blockedImpl.blockingIssues = ["cannot write"];
  blockedImpl.completedWorkPackages = [];
  assert.equal(validatePayload("implementation", blockedImpl, { planPayload: validPlanPayload() }).ok, true);

  assert.equal(validatePayload("execute-review", validExecuteReviewPayload()).ok, true);
  const execAbs = validExecuteReviewPayload();
  execAbs.verdict = "request_changes";
  execAbs.findings = [{
    severity: "blocking",
    file: "../escape",
    line: 1,
    problem: "bad path",
    requiredChange: "fix",
  }];
  assert.equal(validatePayload("execute-review", execAbs).ok, false);
});

test("completed results require identity; failed results may null identity", () => {
  const completed = validateResult(validCompletedResult());
  assert.equal(completed.ok, true, completed.error && completed.error.message);
  const missingId = validCompletedResult();
  missingId.jobId = null;
  assert.equal(validateResult(missingId).ok, false);
  const failed = validCompletedResult();
  failed.status = "failed";
  failed.jobId = null;
  failed.idempotencyKey = null;
  failed.taskId = null;
  failed.stage = null;
  failed.structuredOutput = null;
  failed.artifacts = [];
  failed.error = { kind: "invalid_job", message: "bad job", details: { path: "/stage" } };
  assert.equal(validateResult(failed).ok, true, validateResult(failed).error && validateResult(failed).error.message);
});

test("JSON schemas match runtime top-level required and property sets", () => {
  const cases = [
    ["coding-agent-job.v1.schema.json", JOB_FIELD_KEYS],
    ["coding-agent-result.v1.schema.json", RESULT_FIELD_KEYS],
    ["plan.v1.schema.json", PLAN_FIELD_KEYS],
    ["plan-review.v1.schema.json", PLAN_REVIEW_FIELD_KEYS],
    ["implementation.v1.schema.json", IMPLEMENTATION_FIELD_KEYS],
    ["direct-implementation.v1.schema.json", DIRECT_IMPLEMENTATION_FIELD_KEYS],
    ["execute-review.v1.schema.json", EXECUTE_REVIEW_FIELD_KEYS],
  ];
  for (const [file, keys] of cases) {
    const schema = loadSchema(file);
    assert.deepEqual(Object.keys(schema.properties), [...keys], file);
    assert.deepEqual(schema.required, [...keys], file);
    assert.equal(schema.additionalProperties, false, file);
  }
});

test("canonical artifacts reject malformed wrappers, wrong kinds, and nested payload errors", () => {
  const valid = validateArtifact(validPlanArtifact(), { expectedKind: "plan" });
  assert.equal(valid.ok, true, valid.error && valid.error.message);
  assert.deepEqual(Object.keys(valid.value), [...ARTIFACT_FIELD_KEYS]);
  assert.deepEqual(Object.keys(valid.value.job), [...ARTIFACT_JOB_FIELD_KEYS]);
  assert.deepEqual(Object.keys(valid.value.workspace), [...ARTIFACT_WORKSPACE_FIELD_KEYS]);

  const parsed = parseCanonicalArtifact(JSON.stringify(validPlanArtifact()), { expectedKind: "plan" });
  assert.equal(parsed.ok, true, parsed.error && parsed.error.message);
  assert.equal(parseCanonicalArtifact("not-json", { expectedKind: "plan" }).ok, false);

  const bare = parseCanonicalArtifact(JSON.stringify(validPlanPayload()), { expectedKind: "plan" });
  assert.equal(bare.ok, false);
  assert.equal(bare.error.path, "/schema");

  const wrongKind = validateArtifact(validImplementationArtifact(), { expectedKind: "plan" });
  assert.equal(wrongKind.ok, false);
  assert.equal(wrongKind.error.path, "/kind");

  const stageMismatch = validPlanArtifact();
  stageMismatch.job.stage = "implement";
  assert.equal(validateArtifact(stageMismatch, { expectedKind: "plan" }).ok, false);

  const badHash = validPlanArtifact();
  badHash.job.jobSha256 = "not-a-digest";
  assert.equal(validateArtifact(badHash, { expectedKind: "plan" }).ok, false);

  const emptySession = validPlanArtifact();
  emptySession.sessionId = "";
  assert.equal(validateArtifact(emptySession, { expectedKind: "plan" }).ok, false);

  const badPayload = validPlanArtifact();
  badPayload.payload.schema = "nope";
  const nested = validateArtifact(badPayload, { expectedKind: "plan" });
  assert.equal(nested.ok, false);
  assert.equal(nested.error.path, "/payload/schema");

  const impl = validateArtifact(validImplementationArtifact(), {
    expectedKind: "implementation",
    planPayload: validPlanPayload(),
  });
  assert.equal(impl.ok, true, impl.error && impl.error.message);
  const implWithoutPlan = validateArtifact(validImplementationArtifact(), { expectedKind: "implementation" });
  assert.equal(implWithoutPlan.ok, false);
});

test("result schema recursively mirrors validateResult nested keys, enums, and invalid values", () => {
  const schema = loadSchema("coding-agent-result.v1.schema.json");
  const exactNodes = [
    { pointer: "", keys: RESULT_FIELD_KEYS },
    { pointer: "/structuredOutput", keys: STRUCTURED_OUTPUT_FIELD_KEYS },
    { pointer: "/artifacts", keys: ARTIFACT_ENTRY_FIELD_KEYS, items: true },
    { pointer: "/checks", keys: CHECK_RESULT_FIELD_KEYS, items: true },
    { pointer: "/workspace", keys: RESULT_WORKSPACE_FIELD_KEYS },
    { pointer: "/error", keys: ERROR_OBJECT_FIELD_KEYS },
    { pointer: "/paths", keys: RESULT_PATHS_FIELD_KEYS },
    { pointer: "/paths/adapterRuns", keys: ADAPTER_RUN_FIELD_KEYS, items: true },
  ];
  for (const item of exactNodes) {
    let node = schema;
    for (const part of item.pointer.split("/").filter(Boolean)) node = node.properties[part];
    if (item.items) node = node.items;
    assert.equal(node.additionalProperties, false, item.pointer || "/");
    assert.deepEqual(Object.keys(node.properties), [...item.keys], item.pointer || "/");
    assert.deepEqual(node.required, [...item.keys], item.pointer || "/");
  }

  assert.equal(schema.properties.usage.additionalProperties, undefined);
  assert.equal(schema.properties.structuredOutput.properties.payload.additionalProperties, undefined);
  assert.equal(schema.properties.error.properties.details.additionalProperties, undefined);

  assert.deepEqual(schema.properties.status.enum, ["completed", "failed", "timed_out", "aborted", "unavailable"]);
  assert.deepEqual(schema.properties.artifacts.items.properties.kind.enum, [...OUTPUT_KINDS, "plan-markdown"]);
  assert.deepEqual(schema.properties.checks.items.properties.status.enum, [...CHECK_STATUSES]);
  assert.deepEqual(
    [...schema.properties.error.properties.kind.enum].sort(),
    [...ERROR_KINDS].sort(),
  );
  assert.deepEqual(
    schema.properties.paths.properties.adapterRuns.items.properties.phase.enum,
    ["primary", "output-recovery"],
  );

  const completed = validCompletedResult();
  assert.equal(validateResult(completed).ok, true);
  assert.equal(schemaAccepts(schema, completed), true, "schema should accept a runtime-valid completed result");

  const failed = validCompletedResult();
  failed.status = "failed";
  failed.structuredOutput = null;
  failed.error = { kind: "invalid_job", message: "bad job", details: { path: "/stage" } };
  assert.equal(validateResult(failed).ok, true);
  assert.equal(schemaAccepts(schema, failed), true);

  const invalids = [
    (value) => { value.artifacts[0].extra = true; },
    (value) => { delete value.artifacts[0].sha256; },
    (value) => { value.artifacts[0].kind = "secret"; },
    (value) => { value.artifacts[0].path = "relative.json"; },
    (value) => { value.artifacts[0].sha256 = "abc"; },
    (value) => { value.artifacts[0].canonical = "yes"; },
    (value) => {
      value.checks = [{
        id: "check-unit",
        status: "ok",
        argv: ["node"],
        cwd: "/abs/repo",
        expectedExitCode: 0,
        exitCode: 0,
        signal: null,
        startedAt: "2026-09-14T00:00:00.000Z",
        finishedAt: "2026-09-14T00:00:01.000Z",
        stdoutPath: "/abs/out/stdout.txt",
        stderrPath: "/abs/out/stderr.txt",
      }];
    },
    (value) => { value.workspace.extra = true; },
    (value) => { value.workspace.repoRoot = "repo"; },
    (value) => { value.workspace.headBefore = "not-a-git-sha"; },
    (value) => { value.startedAt = "today"; },
    (value) => { value.usage = []; },
    (value) => { value.structuredOutput.payload = "string"; },
    (value) => { value.error = { kind: "nope", message: "x", details: {} }; value.status = "failed"; value.structuredOutput = null; },
    (value) => { value.paths.adapterRuns[0].phase = "retry"; },
    (value) => { value.paths.adapterRuns[0].result = "relative.json"; },
    (value) => { value.paths.events = "events.jsonl"; },
  ];
  for (const mutate of invalids) {
    const value = validCompletedResult();
    mutate(value);
    const runtime = validateResult(value);
    assert.equal(runtime.ok, false, `runtime should reject ${mutate}`);
    assert.equal(schemaAccepts(schema, value), false, `schema should reject a document runtime rejects`);
  }
});

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function matchesJsonType(type, value) {
  if (type === "null") return value === null;
  if (type === "object") return isPlainObject(value);
  if (type === "array") return Array.isArray(value);
  if (type === "string") return typeof value === "string";
  if (type === "boolean") return typeof value === "boolean";
  if (type === "number") return typeof value === "number" && Number.isFinite(value);
  if (type === "integer") return Number.isInteger(value);
  return false;
}

function schemaAccepts(schema, value) {
  const errors = [];
  applyJsonSchema(schema, value, "", errors);
  return errors.length === 0;
}

function applyJsonSchema(schema, value, path, errors) {
  if (!schema || typeof schema !== "object") return;
  if (schema.type) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((type) => matchesJsonType(type, value))) {
      errors.push(`${path || "/"} type`);
      return;
    }
  }
  if (Object.hasOwn(schema, "const") && value !== schema.const) errors.push(`${path || "/"} const`);
  if (schema.enum && !schema.enum.includes(value)) errors.push(`${path || "/"} enum`);
  if (typeof value === "string") {
    if (schema.minLength && value.length < schema.minLength) errors.push(`${path || "/"} minLength`);
    if (schema.pattern && !new RegExp(schema.pattern, "u").test(value)) errors.push(`${path || "/"} pattern`);
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(`${path || "/"} minimum`);
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(`${path || "/"} maximum`);
  }
  if (isPlainObject(value)) {
    if (schema.required) {
      for (const key of schema.required) {
        if (!Object.hasOwn(value, key)) errors.push(`${path}/${key} required`);
      }
    }
    if (schema.additionalProperties === false && schema.properties) {
      for (const key of Object.keys(value)) {
        if (!Object.hasOwn(schema.properties, key)) errors.push(`${path}/${key} additional`);
      }
    }
    if (schema.properties) {
      for (const [key, child] of Object.entries(schema.properties)) {
        if (Object.hasOwn(value, key)) applyJsonSchema(child, value[key], `${path}/${key}`, errors);
      }
    }
  }
  if (Array.isArray(value) && schema.items) {
    if (schema.minItems !== undefined && value.length < schema.minItems) {
      errors.push(`${path || "/"} minItems`);
    }
    if (schema.maxItems !== undefined && value.length > schema.maxItems) {
      errors.push(`${path || "/"} maxItems`);
    }
    value.forEach((item, index) => applyJsonSchema(schema.items, item, `${path}/${index}`, errors));
  } else if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) {
      errors.push(`${path || "/"} minItems`);
    }
    if (schema.maxItems !== undefined && value.length > schema.maxItems) {
      errors.push(`${path || "/"} maxItems`);
    }
  }
  if (schema.if) {
    const probe = [];
    applyJsonSchema(schema.if, value, path, probe);
    if (probe.length === 0) {
      if (schema.then) applyJsonSchema(schema.then, value, path, errors);
    } else if (schema.else) {
      applyJsonSchema(schema.else, value, path, errors);
    }
  }
  if (Array.isArray(schema.allOf)) {
    for (const part of schema.allOf) applyJsonSchema(part, value, path, errors);
  }
}
