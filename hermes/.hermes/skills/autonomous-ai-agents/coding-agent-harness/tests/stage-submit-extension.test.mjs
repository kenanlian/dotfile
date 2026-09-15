import { test } from "node:test";
import assert from "node:assert/strict";
import { realpathSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  EXECUTE_REVIEW_FIELD_KEYS as CONTRACT_EXECUTE_REVIEW_KEYS,
  IMPLEMENTATION_FIELD_KEYS as CONTRACT_IMPLEMENTATION_KEYS,
  PLAN_FIELD_KEYS as CONTRACT_PLAN_KEYS,
  PLAN_REVIEW_FIELD_KEYS as CONTRACT_PLAN_REVIEW_KEYS,
  STAGE_CONTRACTS,
  SUBMIT_TOOLS,
} from "../src/contracts.mjs";
import { compileBrief } from "../src/prompts.mjs";
import {
  EXECUTE_REVIEW_FIELD_KEYS,
  IMPLEMENTATION_FIELD_KEYS,
  PLAN_FIELD_KEYS,
  PLAN_REVIEW_FIELD_KEYS,
  SUBMIT_EXECUTE_REVIEW,
  SUBMIT_IMPLEMENTATION,
  SUBMIT_PLAN,
  SUBMIT_PLAN_REVIEW,
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

test("stage-submit extension loads four terminating tools", async () => {
  const loaded = await loadStageSubmit();
  assert.deepEqual(loaded.errors, []);
  assert.equal(loaded.extensions.length, 1);
  const tools = loaded.extensions[0].tools;
  for (const name of [SUBMIT_PLAN, SUBMIT_PLAN_REVIEW, SUBMIT_IMPLEMENTATION, SUBMIT_EXECUTE_REVIEW]) {
    assert.ok(tools.has(name), name);
    const tool = tools.get(name);
    assert.equal(tool.definition.parameters.additionalProperties, false);
  }
});

test("keys match contracts and JSON schema property order", () => {
  assert.deepEqual([...PLAN_FIELD_KEYS], [...CONTRACT_PLAN_KEYS]);
  assert.deepEqual([...PLAN_REVIEW_FIELD_KEYS], [...CONTRACT_PLAN_REVIEW_KEYS]);
  assert.deepEqual([...IMPLEMENTATION_FIELD_KEYS], [...CONTRACT_IMPLEMENTATION_KEYS]);
  assert.deepEqual([...EXECUTE_REVIEW_FIELD_KEYS], [...CONTRACT_EXECUTE_REVIEW_KEYS]);
  assert.equal(SUBMIT_PLAN, SUBMIT_TOOLS.plan);
  assert.equal(SUBMIT_PLAN_REVIEW, SUBMIT_TOOLS.plan_review);
  assert.equal(SUBMIT_IMPLEMENTATION, SUBMIT_TOOLS.implement);
  assert.equal(SUBMIT_EXECUTE_REVIEW, SUBMIT_TOOLS.execute_review);
  const planSchema = JSON.parse(readFileSync(join(SCHEMA_DIR, "plan.v1.schema.json"), "utf8"));
  assert.deepEqual(Object.keys(planSchema.properties), [...PLAN_FIELD_KEYS]);
});

test("valid payloads terminate and round-trip details, including unicode", async () => {
  const loaded = await loadStageSubmit();
  const tools = loaded.extensions[0].tools;
  const cases = [
    [SUBMIT_PLAN, validPlanPayload(), PLAN_FIELD_KEYS],
    [SUBMIT_PLAN_REVIEW, validPlanReviewPayload(), PLAN_REVIEW_FIELD_KEYS],
    [SUBMIT_IMPLEMENTATION, validImplementationPayload(), IMPLEMENTATION_FIELD_KEYS],
    [SUBMIT_EXECUTE_REVIEW, validExecuteReviewPayload(), EXECUTE_REVIEW_FIELD_KEYS],
  ];
  for (const [name, payload, keys] of cases) {
    const tool = tools.get(name);
    assert.deepEqual(Object.keys(tool.definition.parameters.properties), [...keys]);
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

test("compileBrief interpolates job fields and does not invent workflow decisions", () => {
  const plan = compileBrief(sampleJob("plan"));
  assert.match(plan, /submit_plan/);
  assert.match(plan, /job_1/);
  assert.match(plan, /\/abs\/requirement\.md/);
  assert.match(plan, /read-only/);
  assert.doesNotMatch(plan, /kanban|ready\/running|Workflow Manifest/i);
  const review = compileBrief(sampleJob("execute_review"), {
    workspaceEvidencePath: "/out/derived/workspace-evidence.json",
    candidatePatchPath: "/out/derived/candidate.patch",
  });
  assert.match(review, /submit_execute_review/);
  assert.match(review, /workspace-evidence\.json/);
  assert.match(review, /candidate\.patch/);
  assert.match(review, /every delegated child must remain read-only/);
});
