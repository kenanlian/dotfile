import { test } from "node:test";
import assert from "node:assert/strict";
import { realpathSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  EXECUTE_REVIEW_FIELD_KEYS as CONTRACT_EXECUTE_REVIEW_KEYS,
  IMPLEMENTATION_FIELD_KEYS as CONTRACT_IMPLEMENTATION_KEYS,
  DIRECT_IMPLEMENTATION_FIELD_KEYS as CONTRACT_DIRECT_IMPLEMENTATION_KEYS,
  PLAN_FIELD_KEYS as CONTRACT_PLAN_KEYS,
  PLAN_REVIEW_FIELD_KEYS as CONTRACT_PLAN_REVIEW_KEYS,
  STAGE_CONTRACTS,
  SUBMIT_TOOLS,
} from "../src/contracts.mjs";
import { compileBrief } from "../src/prompts.mjs";
import {
  DIRECT_IMPLEMENTATION_FIELD_KEYS,
  EXECUTE_REVIEW_FIELD_KEYS,
  IMPLEMENTATION_FIELD_KEYS,
  PLAN_FIELD_KEYS,
  PLAN_REVIEW_FIELD_KEYS,
  SUBMIT_DIRECT_IMPLEMENTATION,
  SUBMIT_EXECUTE_REVIEW,
  SUBMIT_IMPLEMENTATION,
  SUBMIT_PLAN,
  SUBMIT_PLAN_REVIEW,
  ATTESTATION_VERSION,
  EXPECT_EXTENSIONS_ENV,
  buildAttestationLine,
  parseExpectedExtensions,
} from "../extensions/stage-submit/keys.mjs";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const EXT_ROOT = join(TEST_DIR, "..", "extensions", "stage-submit");
const SCHEMA_DIR = join(TEST_DIR, "..", "schemas");

function piPackageRoot() {
  const bin = realpathSync(join(process.env.HOME || "", ".local", "bin", "pi"));
  return join(dirname(bin), "..", "..");
}

async function loadStageSubmit() {
  const loaderUrl = pathToFileURL(join(piPackageRoot(), "dist/core/extensions/loader.js")).href;
  const { loadExtensions } = await import(loaderUrl);
  return loadExtensions([EXT_ROOT], TEST_DIR);
}

async function typeboxCheck() {
  const valueUrl = pathToFileURL(join(piPackageRoot(), "node_modules/typebox/build/value/index.mjs")).href;
  const { Check } = await import(valueUrl);
  return Check;
}

function validPlanPayload() {
  return {
    schema: "plan.v1",
    outcome: "completed",
    title: 'Greet: "hello" 你好',
    goal: "Add greet\nwith a newline",
    architecture: "Single module",
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
    risks: [{ risk: "none", mitigation: "keep tiny" }],
    blockingIssues: [],
  };
}

function validPlanReviewPayload() {
  return {
    schema: "plan-review.v1",
    verdict: "approved",
    summary: 'Looks good: "quotes" and 你好',
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
    summary: "Matches plan.",
    findings: [],
    acceptanceCoverage: ["C1: greet test"],
  };
}

function sampleJob(stage) {
  const contract = STAGE_CONTRACTS[stage];
  const inputs = stage === "plan"
    ? [{ kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) }]
    : stage === "plan_review"
      ? [
        { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
        { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
      ]
      : stage === "implement"
        ? [{ kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) }]
        : stage === "direct_implement"
          ? [{ kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) }]
        : [
          { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
          { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
          { kind: "implementation", path: "/abs/impl.json", sha256: "d".repeat(64) },
        ];
  return {
    jobId: "job_1",
    idempotencyKey: `task: ${stage}:1`,
    taskId: "task_1",
    stage,
    attempt: 1,
    workspace: {
      repoRoot: "/abs/repo",
      branch: "main",
      expectedHead: "a".repeat(40),
    },
    agent: {
      profile: contract.profile,
      model: "zai-coding-cn/glm-5.3",
      thinking: "high",
    },
    permissions: { mode: contract.permission },
    inputs,
  };
}

test("stage-submit extension loads five terminating tools", async () => {
  const loaded = await loadStageSubmit();
  assert.deepEqual(loaded.errors, []);
  assert.equal(loaded.extensions.length, 1);
  const tools = loaded.extensions[0].tools;
  for (const name of [
    SUBMIT_PLAN,
    SUBMIT_PLAN_REVIEW,
    SUBMIT_IMPLEMENTATION,
    SUBMIT_EXECUTE_REVIEW,
    SUBMIT_DIRECT_IMPLEMENTATION,
  ]) {
    assert.ok(tools.has(name), name);
    const tool = tools.get(name);
    const parameters = tool.definition.parameters;
    const arms = parameters.anyOf || parameters.oneOf || [parameters];
    for (const arm of arms) {
      assert.equal(arm.additionalProperties, false, name);
    }
  }
});

test("keys match contracts and JSON schema property order", () => {
  assert.deepEqual([...PLAN_FIELD_KEYS], [...CONTRACT_PLAN_KEYS]);
  assert.deepEqual([...PLAN_REVIEW_FIELD_KEYS], [...CONTRACT_PLAN_REVIEW_KEYS]);
  assert.deepEqual([...IMPLEMENTATION_FIELD_KEYS], [...CONTRACT_IMPLEMENTATION_KEYS]);
  assert.deepEqual([...DIRECT_IMPLEMENTATION_FIELD_KEYS], [...CONTRACT_DIRECT_IMPLEMENTATION_KEYS]);
  assert.deepEqual([...EXECUTE_REVIEW_FIELD_KEYS], [...CONTRACT_EXECUTE_REVIEW_KEYS]);
  assert.equal(SUBMIT_PLAN, SUBMIT_TOOLS.plan);
  assert.equal(SUBMIT_PLAN_REVIEW, SUBMIT_TOOLS.plan_review);
  assert.equal(SUBMIT_IMPLEMENTATION, SUBMIT_TOOLS.implement);
  assert.equal(SUBMIT_EXECUTE_REVIEW, SUBMIT_TOOLS.execute_review);
  assert.equal(SUBMIT_DIRECT_IMPLEMENTATION, SUBMIT_TOOLS.direct_implement);
  const planSchema = JSON.parse(readFileSync(join(SCHEMA_DIR, "plan.v1.schema.json"), "utf8"));
  assert.deepEqual(Object.keys(planSchema.properties), [...PLAN_FIELD_KEYS]);
});

test("attestation helpers emit a grep-stable JSON line", () => {
  assert.equal(EXPECT_EXTENSIONS_ENV, "PI_HARNESS_EXPECT_EXTENSIONS");
  const line = buildAttestationLine("stage-submit,auto-handoff");
  assert.match(line, /"harnessAttestation"/);
  const parsed = JSON.parse(line);
  assert.equal(parsed.type, "session_start");
  assert.equal(parsed.harnessAttestation.version, ATTESTATION_VERSION);
  assert.deepEqual(parsed.harnessAttestation.expected, ["stage-submit", "auto-handoff"]);
  assert.deepEqual(parseExpectedExtensions("stage-submit"), ["stage-submit"]);
});

test("valid payloads terminate and round-trip details, including unicode", async () => {
  const loaded = await loadStageSubmit();
  const tools = loaded.extensions[0].tools;
  const cases = [
    [SUBMIT_PLAN, validPlanPayload(), PLAN_FIELD_KEYS],
    [SUBMIT_PLAN_REVIEW, validPlanReviewPayload(), PLAN_REVIEW_FIELD_KEYS],
    [SUBMIT_IMPLEMENTATION, validImplementationPayload(), IMPLEMENTATION_FIELD_KEYS],
    [SUBMIT_DIRECT_IMPLEMENTATION, validDirectImplementationPayload(), DIRECT_IMPLEMENTATION_FIELD_KEYS],
    [SUBMIT_EXECUTE_REVIEW, validExecuteReviewPayload(), EXECUTE_REVIEW_FIELD_KEYS],
  ];
  for (const [name, payload, keys] of cases) {
    const tool = tools.get(name);
    const parameters = tool.definition.parameters;
    const properties = parameters.properties
      || (parameters.anyOf && parameters.anyOf[0].properties)
      || (parameters.oneOf && parameters.oneOf[0].properties);
    assert.deepEqual(Object.keys(properties), [...keys]);
    const result = await tool.definition.execute("call-1", payload);
    assert.equal(result.terminate, true);
    assert.deepEqual(result.details, payload);
    assert.equal(Buffer.compare(Buffer.from(JSON.stringify(result.details)), Buffer.from(JSON.stringify(payload))), 0);
  }
});

test("schema-invalid payloads do not execute", async () => {
  const loaded = await loadStageSubmit();
  const Check = await typeboxCheck();
  const tool = loaded.extensions[0].tools.get(SUBMIT_PLAN_REVIEW);
  const invalid = { ...validPlanReviewPayload(), extra: true };
  assert.equal(Check(tool.definition.parameters, invalid), false);
  let executed = false;
  const original = tool.definition.execute;
  tool.definition.execute = async (...args) => {
    executed = true;
    return original(...args);
  };
  if (Check(tool.definition.parameters, invalid)) {
    await tool.definition.execute("call-bad", invalid);
  }
  assert.equal(executed, false);
});

test("direct implementation TypeBox rejects payloads runtime rejects", async () => {
  const loaded = await loadStageSubmit();
  const Check = await typeboxCheck();
  const tool = loaded.extensions[0].tools.get(SUBMIT_DIRECT_IMPLEMENTATION);
  const schema = tool.definition.parameters;
  assert.equal(Check(schema, validDirectImplementationPayload()), true);
  const blockedOk = {
    ...validDirectImplementationPayload(),
    outcome: "blocked",
    blockingIssues: ["cannot proceed"],
  };
  assert.equal(Check(schema, blockedOk), true);
  const completedWithBlockers = {
    ...validDirectImplementationPayload(),
    blockingIssues: ["still blocked"],
  };
  const blockedEmpty = { ...validDirectImplementationPayload(), outcome: "blocked" };
  const emptySummary = { ...validDirectImplementationPayload(), summary: "" };
  const emptyResidual = { ...validDirectImplementationPayload(), residualRisks: [""] };
  const emptyBlocker = {
    ...validDirectImplementationPayload(),
    outcome: "blocked",
    blockingIssues: [""],
  };
  assert.equal(Check(schema, completedWithBlockers), false);
  assert.equal(Check(schema, blockedEmpty), false);
  assert.equal(Check(schema, emptySummary), false);
  assert.equal(Check(schema, emptyResidual), false);
  assert.equal(Check(schema, emptyBlocker), false);
});

test("compileBrief interpolates job fields and does not invent workflow decisions", () => {
  const plan = compileBrief(sampleJob("plan"));
  assert.equal(plan.split("\n", 1)[0], "/skill:write-plan ");
  assert.match(plan, /submit_plan/);
  assert.match(plan, /job_1/);
  assert.match(plan, /\/abs\/requirement\.md/);
  assert.match(plan, /read-only/);
  assert.match(plan, /This run mounts Skills \(read the SKILL\.md at each path/);
  assert.match(plan, /- write-plan: .*agent_skills\/skills\/write-plan\/SKILL\.md/);
  assert.match(plan, /- delegate-work: .*agent_skills\/skills\/delegate-work\/SKILL\.md/);
  assert.doesNotMatch(plan, /kanban|ready\/running|Workflow Manifest/i);
  const review = compileBrief(sampleJob("execute_review"), {
    workspaceEvidencePath: "/out/derived/workspace-evidence.json",
    candidatePatchPath: "/out/derived/candidate.patch",
  });
  assert.equal(review.split("\n", 1)[0], "/skill:review-execute-candidate ");
  assert.match(review, /submit_execute_review/);
  assert.match(review, /workspace-evidence\.json/);
  assert.match(review, /candidate\.patch/);
  assert.match(review, /every delegated child must remain read-only/);
  const direct = compileBrief(sampleJob("direct_implement"));
  assert.ok(!direct.startsWith("/skill:"));
  assert.match(direct, /submit_direct_implementation/);
  assert.match(direct, /Implement the Requirement directly/);
  assert.match(direct, /- delegate-work: .*agent_skills\/skills\/delegate-work\/SKILL\.md/);
  assert.doesNotMatch(direct, /accepted plan/);
  assert.doesNotMatch(direct, /kanban|ready\/running|Workflow Manifest/i);
});
