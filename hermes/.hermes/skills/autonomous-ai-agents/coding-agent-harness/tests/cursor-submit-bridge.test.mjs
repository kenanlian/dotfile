import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  CONTRACT_FIELD_KEYS,
  DEVIATION_FIELD_KEYS,
  DIRECT_IMPLEMENTATION_FIELD_KEYS,
  EXECUTE_REVIEW_FIELD_KEYS,
  EXECUTE_REVIEW_FINDING_FIELD_KEYS,
  FILE_CHANGE_FIELD_KEYS,
  IMPLEMENTATION_FIELD_KEYS,
  PLAN_FIELD_KEYS,
  PLAN_REVIEW_FIELD_KEYS,
  PLAN_REVIEW_FINDING_FIELD_KEYS,
  PLAN_VERIFICATION_FIELD_KEYS,
  REQUIREMENT_FIELD_KEYS,
  RISK_FIELD_KEYS,
  SUBMIT_DIRECT_IMPLEMENTATION,
  SUBMIT_EXECUTE_REVIEW,
  SUBMIT_IMPLEMENTATION,
  SUBMIT_PLAN,
  SUBMIT_PLAN_REVIEW,
  WORK_PACKAGE_FIELD_KEYS,
} from "../extensions/stage-submit/keys.mjs";
import {
  ATTEMPT_SCHEMA,
  BINDING_KEYS,
  TOOL_ENUM_FIELDS,
  TOOL_FIELD_KEYS,
  TOOL_SCHEMA_IDS,
  checkBinding,
  checkPayloadShape,
  handleJsonRpc,
  handleSubmitCall,
  isSmokeSuppressTool,
  listAttempts,
  loadConfig,
  writeAttempt,
} from "../extensions/cursor-stage-submit/server.mjs";
import {
  PLUGIN_LAYOUT,
  SERVER_PATH,
  classifySubmissions,
  generateSubmitBridge,
} from "../src/cursor-submit-bridge.mjs";

const SERVER_FILE = fileURLToPath(new URL("../extensions/cursor-stage-submit/server.mjs", import.meta.url));

function tempDir() {
  return mkdtempSync(join(tmpdir(), "cursor-submit-bridge-"));
}

function sampleJob(stage, jobId = `job_${stage}`) {
  return { jobId, stage };
}

function bindingFor(config, extra = {}) {
  const claimed = {};
  for (const key of BINDING_KEYS) claimed[key] = config[key];
  return { ...claimed, ...extra };
}

function validPlanPayload() {
  return {
    schema: "plan.v1",
    outcome: "completed",
    title: "Greet",
    goal: "Add greet",
    architecture: "Single module",
    techStack: ["Node.js"],
    requirements: [{ id: "R1", text: "greet returns a greeting" }],
    contracts: [{ id: "C1", requirementIds: ["R1"], text: "greet(name) returns Hello, name" }],
    workPackages: [{
      id: "WP-01",
      title: "Implement greet",
      objective: "Add greet and a test",
      dependsOn: [],
      contractIds: ["C1"],
      fileChanges: [{ action: "modify", path: "src/greet.mjs" }],
      steps: ["Write greet"],
      verificationIds: ["V1"],
    }],
    verification: [{
      id: "V1",
      kind: "focused",
      cwd: ".",
      argv: ["node", "--test"],
      expected: "tests pass",
      contractIds: ["C1"],
    }],
    risks: [{ risk: "none", mitigation: "keep tiny" }],
    blockingIssues: [],
  };
}

function validPlanReviewPayload() {
  return {
    schema: "plan-review.v1",
    verdict: "approved",
    summary: "Looks good",
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

function validDirectImplementationPayload() {
  return {
    schema: "direct-implementation.v1",
    outcome: "completed",
    summary: "Implemented the requirement.",
    residualRisks: [],
    blockingIssues: [],
  };
}

const PAYLOADS = {
  [SUBMIT_PLAN]: validPlanPayload,
  [SUBMIT_PLAN_REVIEW]: validPlanReviewPayload,
  [SUBMIT_IMPLEMENTATION]: validImplementationPayload,
  [SUBMIT_EXECUTE_REVIEW]: validExecuteReviewPayload,
  [SUBMIT_DIRECT_IMPLEMENTATION]: validDirectImplementationPayload,
};

const STAGE_TOOLS = Object.freeze([
  ["plan", SUBMIT_PLAN],
  ["plan_review", SUBMIT_PLAN_REVIEW],
  ["implement", SUBMIT_IMPLEMENTATION],
  ["execute_review", SUBMIT_EXECUTE_REVIEW],
  ["direct_implement", SUBMIT_DIRECT_IMPLEMENTATION],
]);

function acceptedAttempt(seq, payload = { ok: true }) {
  return {
    seq,
    receivedAt: "2026-09-18T00:00:00.000Z",
    tool: SUBMIT_PLAN,
    binding: { jobId: "job", jobSha256: "a".repeat(64), stage: "plan", expectedTool: SUBMIT_PLAN, runNonce: "n" },
    bindingMatches: true,
    payload,
    outcome: "accepted",
  };
}

function rejectedAttempt(seq, reason = "binding mismatch: jobId") {
  return {
    ...acceptedAttempt(seq),
    outcome: "rejected",
    bindingMatches: false,
    reason,
  };
}

test("classification: 0 attempts → missing", () => {
  const tmp = tempDir();
  try {
    const result = classifySubmissions(join(tmp, "submit"));
    assert.equal(result.kind, "missing");
    assert.equal(result.accepted, null);
    assert.deepEqual(result.attempts, []);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("classification: 1 accepted → ok", () => {
  const tmp = tempDir();
  try {
    const submitDir = join(tmp, "submit");
    writeAttempt(submitDir, acceptedAttempt(1));
    const result = classifySubmissions(submitDir);
    assert.equal(result.kind, "ok");
    assert.equal(result.accepted.outcome, "accepted");
    assert.equal(result.attempts.length, 1);
    assert.equal(result.accepted.seq, "000001");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("classification: 2 accepted → duplicate", () => {
  const tmp = tempDir();
  try {
    const submitDir = join(tmp, "submit");
    writeAttempt(submitDir, acceptedAttempt(1));
    writeAttempt(submitDir, acceptedAttempt(2));
    const result = classifySubmissions(submitDir);
    assert.equal(result.kind, "duplicate");
    assert.equal(result.accepted, null);
    assert.equal(result.attempts.length, 2);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("classification: rejected-only → invalid", () => {
  const tmp = tempDir();
  try {
    const submitDir = join(tmp, "submit");
    writeAttempt(submitDir, rejectedAttempt(1));
    const result = classifySubmissions(submitDir);
    assert.equal(result.kind, "invalid");
    assert.equal(result.accepted, null);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("classification: rejected + accepted → invalid", () => {
  const tmp = tempDir();
  try {
    const submitDir = join(tmp, "submit");
    writeAttempt(submitDir, rejectedAttempt(1));
    writeAttempt(submitDir, acceptedAttempt(2));
    const result = classifySubmissions(submitDir);
    assert.equal(result.kind, "invalid");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("classification: duplicate beats invalid", () => {
  const tmp = tempDir();
  try {
    const submitDir = join(tmp, "submit");
    writeAttempt(submitDir, rejectedAttempt(1));
    writeAttempt(submitDir, acceptedAttempt(2));
    writeAttempt(submitDir, acceptedAttempt(3));
    const result = classifySubmissions(submitDir);
    assert.equal(result.kind, "duplicate");
    assert.equal(result.attempts.length, 3);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("O_EXCL prevents overwrite of the same seq", () => {
  const tmp = tempDir();
  try {
    const submitDir = join(tmp, "submit");
    writeAttempt(submitDir, acceptedAttempt(1));
    assert.throws(() => writeAttempt(submitDir, acceptedAttempt(1)), { code: "EEXIST" });
    assert.equal(listAttempts(submitDir).length, 1);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("binding mismatch is recorded rejected", () => {
  const tmp = tempDir();
  try {
    const generated = generateSubmitBridge({
      adapterDir: tmp,
      job: sampleJob("plan"),
      jobSha256: "b".repeat(64),
      expectedTool: SUBMIT_PLAN,
      phase: "primary",
    });
    const claimed = bindingFor(generated.config, { runNonce: "wrong-nonce" });
    const result = handleSubmitCall(generated.config, { ...claimed, payload: validPlanPayload() }, SUBMIT_PLAN);
    assert.equal(result.ok, false);
    assert.match(result.reason, /binding mismatch/);
    const listed = listAttempts(generated.submitDir);
    assert.equal(listed.length, 1);
    assert.equal(listed[0].record.outcome, "rejected");
    assert.equal(listed[0].record.bindingMatches, false);
    assert.equal(listed[0].record.schema, ATTEMPT_SCHEMA);
    assert.equal(classifySubmissions(generated.submitDir).kind, "invalid");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("payload-shape failure is recorded rejected", () => {
  const tmp = tempDir();
  try {
    const generated = generateSubmitBridge({
      adapterDir: tmp,
      job: sampleJob("plan"),
      jobSha256: "b".repeat(64),
      expectedTool: SUBMIT_PLAN,
      phase: "primary",
    });
    const claimed = bindingFor(generated.config);
    const bad = validPlanPayload();
    delete bad.title;
    const result = handleSubmitCall(generated.config, { ...claimed, payload: bad }, SUBMIT_PLAN);
    assert.equal(result.ok, false);
    assert.match(result.reason, /payload shape/);
    const listed = listAttempts(generated.submitDir);
    assert.equal(listed.length, 1);
    assert.equal(listed[0].record.outcome, "rejected");
    assert.equal(listed[0].record.bindingMatches, true);
    assert.equal(classifySubmissions(generated.submitDir).kind, "invalid");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("generated config binds exactly the expected tool per stage for all five SUBMIT_TOOLS", () => {
  const tmp = tempDir();
  try {
    for (const [stage, tool] of STAGE_TOOLS) {
      const adapterDir = join(tmp, stage);
      const generated = generateSubmitBridge({
        adapterDir,
        job: sampleJob(stage),
        jobSha256: "c".repeat(64),
        expectedTool: tool,
        phase: "primary",
      });
      assert.equal(generated.config.expectedTool, tool);
      assert.equal(generated.config.stage, stage);
      assert.equal(generated.config.jobId, `job_${stage}`);
      assert.equal(typeof generated.config.runNonce, "string");
      assert.match(generated.config.runNonce, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
      assert.equal(generated.config.phase, "primary");
      assert.equal(generated.config.submitDir, generated.submitDir);
      assert.equal(generated.config.schema, "coding-agent.submit-bridge.v1");

      const onDisk = loadConfig(join(generated.pluginDir, "config.json"));
      assert.equal(onDisk.expectedTool, tool);

      const plugin = JSON.parse(readFileSync(join(generated.pluginDir, PLUGIN_LAYOUT.manifestFile), "utf8"));
      assert.equal(plugin.$schema, "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json");
      assert.equal(plugin.name, "cursor-stage-submit");

      const mcp = JSON.parse(readFileSync(join(generated.pluginDir, PLUGIN_LAYOUT.mcpFile), "utf8"));
      const server = mcp.mcpServers["cursor-stage-submit"];
      assert.equal(server.type, "stdio");
      assert.equal(server.command, process.execPath);
      assert.deepEqual(server.args, [SERVER_PATH, "--config", join(generated.pluginDir, "config.json")]);
      assert.equal(PLUGIN_LAYOUT.format, "agent-plugin");
      assert.equal(PLUGIN_LAYOUT.manifestFile, "plugin.json");
      assert.equal(PLUGIN_LAYOUT.mcpFile, "mcp.json");

      const accepted = handleSubmitCall(
        generated.config,
        { ...bindingFor(generated.config), payload: PAYLOADS[tool]() },
        tool,
      );
      assert.equal(accepted.ok, true, accepted.reason);
      assert.equal(classifySubmissions(generated.submitDir).kind, "ok");
    }
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("generate rejects unknown tool names", () => {
  const tmp = tempDir();
  try {
    assert.throws(
      () => generateSubmitBridge({
        adapterDir: tmp,
        job: sampleJob("plan"),
        jobSha256: "d".repeat(64),
        expectedTool: "submit_unknown",
        phase: "primary",
      }),
      /unknown submit tool/,
    );
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("key-set parity with keys.mjs constants plus schema/outcome/verdict enums", () => {
  assert.deepEqual(TOOL_FIELD_KEYS[SUBMIT_PLAN], PLAN_FIELD_KEYS);
  assert.deepEqual(TOOL_FIELD_KEYS[SUBMIT_PLAN_REVIEW], PLAN_REVIEW_FIELD_KEYS);
  assert.deepEqual(TOOL_FIELD_KEYS[SUBMIT_IMPLEMENTATION], IMPLEMENTATION_FIELD_KEYS);
  assert.deepEqual(TOOL_FIELD_KEYS[SUBMIT_EXECUTE_REVIEW], EXECUTE_REVIEW_FIELD_KEYS);
  assert.deepEqual(TOOL_FIELD_KEYS[SUBMIT_DIRECT_IMPLEMENTATION], DIRECT_IMPLEMENTATION_FIELD_KEYS);

  assert.equal(TOOL_SCHEMA_IDS[SUBMIT_PLAN], "plan.v1");
  assert.equal(TOOL_SCHEMA_IDS[SUBMIT_PLAN_REVIEW], "plan-review.v1");
  assert.equal(TOOL_SCHEMA_IDS[SUBMIT_IMPLEMENTATION], "implementation.v1");
  assert.equal(TOOL_SCHEMA_IDS[SUBMIT_EXECUTE_REVIEW], "execute-review.v1");
  assert.equal(TOOL_SCHEMA_IDS[SUBMIT_DIRECT_IMPLEMENTATION], "direct-implementation.v1");

  assert.deepEqual(TOOL_ENUM_FIELDS[SUBMIT_PLAN].outcome, ["completed", "blocked"]);
  assert.deepEqual(TOOL_ENUM_FIELDS[SUBMIT_IMPLEMENTATION].outcome, ["completed", "blocked"]);
  assert.deepEqual(TOOL_ENUM_FIELDS[SUBMIT_DIRECT_IMPLEMENTATION].outcome, ["completed", "blocked"]);
  assert.deepEqual(TOOL_ENUM_FIELDS[SUBMIT_PLAN_REVIEW].verdict, ["approved", "request_changes", "blocked"]);
  assert.deepEqual(TOOL_ENUM_FIELDS[SUBMIT_EXECUTE_REVIEW].verdict, ["approved", "request_changes", "blocked"]);

  assert.deepEqual(REQUIREMENT_FIELD_KEYS, ["id", "text"]);
  assert.deepEqual(CONTRACT_FIELD_KEYS, ["id", "requirementIds", "text"]);
  assert.deepEqual(WORK_PACKAGE_FIELD_KEYS, [
    "id", "title", "objective", "dependsOn", "contractIds", "fileChanges", "steps", "verificationIds",
  ]);
  assert.deepEqual(FILE_CHANGE_FIELD_KEYS, ["action", "path"]);
  assert.deepEqual(PLAN_VERIFICATION_FIELD_KEYS, ["id", "kind", "cwd", "argv", "expected", "contractIds"]);
  assert.deepEqual(RISK_FIELD_KEYS, ["risk", "mitigation"]);
  assert.deepEqual(PLAN_REVIEW_FINDING_FIELD_KEYS, ["severity", "location", "problem", "requiredChange"]);
  assert.deepEqual(DEVIATION_FIELD_KEYS, ["workPackageId", "summary"]);
  assert.deepEqual(EXECUTE_REVIEW_FINDING_FIELD_KEYS, ["severity", "file", "line", "problem", "requiredChange"]);

  assert.equal(checkPayloadShape(SUBMIT_PLAN, validPlanPayload()).ok, true);
  assert.equal(checkPayloadShape(SUBMIT_PLAN, { ...validPlanPayload(), outcome: "nope" }).ok, false);
  assert.equal(checkPayloadShape(SUBMIT_PLAN_REVIEW, { ...validPlanReviewPayload(), verdict: "ship_it" }).ok, false);
  assert.equal(checkBinding({ jobId: "a", jobSha256: "b", stage: "plan", expectedTool: SUBMIT_PLAN, runNonce: "n" }, {
    jobId: "a", jobSha256: "b", stage: "plan", expectedTool: SUBMIT_PLAN, runNonce: "n",
  }).ok, true);
});

test("MCP JSON-RPC initialize / tools-list / tools-call writes an accepted receipt", async () => {
  const tmp = tempDir();
  try {
    const generated = generateSubmitBridge({
      adapterDir: tmp,
      job: sampleJob("plan"),
      jobSha256: "e".repeat(64),
      expectedTool: SUBMIT_PLAN,
      phase: "primary",
    });
    const init = handleJsonRpc(generated.config, {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "test", version: "0" } },
    });
    assert.equal(init.result.serverInfo.name, "cursor-stage-submit");
    const listed = handleJsonRpc(generated.config, { jsonrpc: "2.0", id: 2, method: "tools/list" });
    assert.equal(listed.result.tools.length, 1);
    assert.equal(listed.result.tools[0].name, SUBMIT_PLAN);

    const called = handleJsonRpc(generated.config, {
      jsonrpc: "2.0",
      id: 3,
      method: "tools/call",
      params: {
        name: SUBMIT_PLAN,
        arguments: { ...bindingFor(generated.config), payload: validPlanPayload() },
      },
    });
    assert.equal(called.result.isError, undefined);
    assert.match(called.result.content[0].text, /Submitted submit_plan/);
    assert.equal(classifySubmissions(generated.submitDir).kind, "ok");

    const mismatch = handleJsonRpc(generated.config, {
      jsonrpc: "2.0",
      id: 4,
      method: "tools/call",
      params: {
        name: SUBMIT_PLAN,
        arguments: { ...bindingFor(generated.config, { jobId: "nope" }), payload: validPlanPayload() },
      },
    });
    assert.equal(mismatch.result.isError, true);

    await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [SERVER_FILE, "--config", generated.configPath], {
        stdio: ["pipe", "pipe", "pipe"],
      });
      let out = "";
      let err = "";
      const finish = (fn) => {
        clearTimeout(timer);
        child.kill("SIGTERM");
        fn();
      };
      const timer = setTimeout(() => {
        finish(() => reject(new Error(`stdio server timed out: stdout=${out} stderr=${err}`)));
      }, 3000);
      child.stdout.setEncoding("utf8");
      child.stdout.on("data", (chunk) => {
        out += chunk;
        if (out.includes("submit_plan")) finish(() => resolve());
      });
      child.stderr.setEncoding("utf8");
      child.stderr.on("data", (chunk) => { err += chunk; });
      child.on("error", (error) => finish(() => reject(error)));
      child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2024-11-05" } })}\n`);
      child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })}\n`);
      child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" })}\n`);
    });
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("CURSOR_SMOKE_SUPPRESS_TOOL unset leaves classification unchanged; set records nothing", () => {
  const tmp = tempDir();
  try {
    const generated = generateSubmitBridge({
      adapterDir: tmp,
      job: sampleJob("plan"),
      jobSha256: "f".repeat(64),
      expectedTool: SUBMIT_PLAN,
      phase: "primary",
    });
    const call = {
      jsonrpc: "2.0",
      id: 10,
      method: "tools/call",
      params: {
        name: SUBMIT_PLAN,
        arguments: { ...bindingFor(generated.config), payload: validPlanPayload() },
      },
    };

    assert.equal(isSmokeSuppressTool({}), false);
    assert.equal(isSmokeSuppressTool({ CURSOR_SMOKE_SUPPRESS_TOOL: "1" }), true);

    const unsetEnv = { ...process.env };
    delete unsetEnv.CURSOR_SMOKE_SUPPRESS_TOOL;
    const unsetResult = handleJsonRpc(generated.config, call, unsetEnv);
    assert.equal(unsetResult.result.isError, undefined);
    assert.match(unsetResult.result.content[0].text, /Submitted submit_plan/);
    assert.equal(listAttempts(generated.submitDir).length, 1);
    assert.equal(classifySubmissions(generated.submitDir).kind, "ok");

    const setResult = handleJsonRpc(generated.config, { ...call, id: 11 }, {
      ...unsetEnv,
      CURSOR_SMOKE_SUPPRESS_TOOL: "1",
    });
    assert.equal(setResult.result.isError, true);
    assert.match(setResult.result.content[0].text, /CURSOR_SMOKE_SUPPRESS_TOOL/);
    assert.equal(listAttempts(generated.submitDir).length, 1);
    assert.equal(classifySubmissions(generated.submitDir).kind, "ok");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("SMOKE_SUPPRESS marker file suppresses recording and stays invisible to classification", () => {
  const tmp = tempDir();
  try {
    const generated = generateSubmitBridge({
      adapterDir: tmp,
      job: sampleJob("plan"),
      jobSha256: "f".repeat(64),
      expectedTool: SUBMIT_PLAN,
      phase: "primary",
    });
    writeFileSync(join(generated.submitDir, "SMOKE_SUPPRESS"), "");

    const call = {
      jsonrpc: "2.0",
      id: 20,
      method: "tools/call",
      params: {
        name: SUBMIT_PLAN,
        arguments: { ...bindingFor(generated.config), payload: validPlanPayload() },
      },
    };
    const unsetEnv = { ...process.env };
    delete unsetEnv.CURSOR_SMOKE_SUPPRESS_TOOL;

    // Marker present: error result, nothing recorded, classification missing.
    assert.equal(isSmokeSuppressTool(unsetEnv, generated.submitDir), true);
    const marked = handleJsonRpc(generated.config, call, unsetEnv);
    assert.equal(marked.result.isError, true);
    assert.match(marked.result.content[0].text, /CURSOR_SMOKE_SUPPRESS_TOOL/);
    assert.equal(listAttempts(generated.submitDir).length, 0);
    assert.equal(classifySubmissions(generated.submitDir).kind, "missing");

    // Marker removed: the same call records normally again.
    rmSync(join(generated.submitDir, "SMOKE_SUPPRESS"), { force: true });
    assert.equal(isSmokeSuppressTool(unsetEnv, generated.submitDir), false);
    const unmarked = handleJsonRpc(generated.config, { ...call, id: 21 }, unsetEnv);
    assert.equal(unmarked.result.isError, undefined);
    assert.equal(listAttempts(generated.submitDir).length, 1);
    assert.equal(classifySubmissions(generated.submitDir).kind, "ok");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});
