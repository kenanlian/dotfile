import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { STAGE_CONTRACTS } from "../src/contracts.mjs";
import { tryBuildCursorRelayArgs, runCursorAdapter } from "../src/cursor-adapter.mjs";
import { createEventWriter } from "../src/events.mjs";
import { compileCursorRecoveryBrief } from "../src/prompts.mjs";

const HARNESS_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SERVER_PATH = join(HARNESS_ROOT, "extensions", "cursor-stage-submit", "server.mjs");
const SERVER_HREF = pathToFileURL(SERVER_PATH).href;

const STUB_SOURCE = `#!/usr/bin/env node
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { writeAttempt, checkBinding } from ${JSON.stringify(SERVER_HREF)};

function parse(argv) {
  const out = {
    brief: null,
    cd: null,
    outDir: null,
    readOnly: false,
    force: false,
    model: null,
    session: null,
    pluginDirs: [],
    timeout: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => argv[++i];
    if (arg === "--brief") out.brief = next();
    else if (arg === "--cd") out.cd = next();
    else if (arg === "--out-dir") out.outDir = next();
    else if (arg === "--read-only") out.readOnly = true;
    else if (arg === "--force") out.force = true;
    else if (arg === "--model") out.model = next();
    else if (arg === "--session") out.session = next();
    else if (arg === "--plugin-dir") out.pluginDirs.push(next());
    else if (arg === "--timeout") out.timeout = next();
  }
  return out;
}

function isRecovery(outDir) {
  return /(?:^|[\\\\/])output-recovery$/.test(outDir || "");
}

const opts = parse(process.argv.slice(2));
mkdirSync(opts.outDir, { recursive: true });
writeFileSync(join(opts.outDir, "relay-argv.json"), JSON.stringify(process.argv.slice(2), null, 2));

const status = process.env.CURSOR_STUB_STATUS || "completed";
const submitKey = isRecovery(opts.outDir) ? "CURSOR_STUB_SUBMIT_RECOVERY" : "CURSOR_STUB_SUBMIT";
const submit = process.env[submitKey] || process.env.CURSOR_STUB_SUBMIT || "ok";
const sessionMode = process.env.CURSOR_STUB_SESSION_MODE || "present";
let sessionId = process.env.CURSOR_STUB_SESSION || "sess-cursor-1";
if (sessionMode === "missing") sessionId = null;
if (sessionMode === "mismatch") sessionId = "sess-other";
const resolvedModel = process.env.CURSOR_STUB_RESOLVED_MODEL || "Claude Opus 5 1M Thinking";
const usage = process.env.CURSOR_STUB_USAGE
  ? JSON.parse(process.env.CURSOR_STUB_USAGE)
  : { inputTokens: 11, outputTokens: 22 };

const pluginDir = opts.pluginDirs[0];
let config = null;
if (pluginDir) {
  config = JSON.parse(readFileSync(join(pluginDir, "config.json"), "utf8"));
}

if (status === "completed" && submit !== "missing" && config) {
  const claimed = {
    jobId: config.jobId,
    jobSha256: config.jobSha256,
    stage: config.stage,
    expectedTool: config.expectedTool,
    runNonce: submit === "invalid" ? "wrong-nonce" : config.runNonce,
  };
  const binding = checkBinding(config, claimed);
  const payload = { schema: "plan.v1", stub: true, tool: config.expectedTool };
  if (submit === "ok" || submit === "duplicate") {
    writeAttempt(config.submitDir, {
      receivedAt: new Date().toISOString(),
      tool: config.expectedTool,
      binding: claimed,
      bindingMatches: binding.ok,
      payload,
      outcome: "accepted",
    });
  }
  if (submit === "duplicate") {
    writeAttempt(config.submitDir, {
      receivedAt: new Date().toISOString(),
      tool: config.expectedTool,
      binding: claimed,
      bindingMatches: binding.ok,
      payload,
      outcome: "accepted",
    });
  }
  if (submit === "invalid") {
    writeAttempt(config.submitDir, {
      receivedAt: new Date().toISOString(),
      tool: config.expectedTool,
      binding: claimed,
      bindingMatches: binding.ok,
      payload,
      outcome: "rejected",
      reason: binding.reason || "invalid",
    });
  }
}

const events = [];
if (sessionId) {
  events.push({
    type: "system",
    subtype: "init",
    session_id: sessionId,
    model: resolvedModel,
    permissionMode: opts.force ? "edit" : "plan",
  });
}
events.push({
  type: "assistant",
  session_id: sessionId,
  message: { role: "assistant", content: [{ type: "text", text: "stub run" }] },
});
events.push({
  type: "result",
  session_id: sessionId,
  result: "done",
  is_error: false,
  usage,
});
writeFileSync(join(opts.outDir, "events.jsonl"), events.map((item) => JSON.stringify(item)).join("\\n") + "\\n");
writeFileSync(join(opts.outDir, "stderr.txt"), "");
writeFileSync(join(opts.outDir, "final.txt"), "stub\\n");

if (process.env.CURSOR_STUB_NO_RESULT === "1") {
  process.exit(0);
}

const result = {
  schema: "delegate-relay.result.v1",
  status,
  sessionId,
  resolvedModel,
  usage,
  pluginDirs: opts.pluginDirs,
  spawn: {
    argv: [
      "--print",
      "--output-format", "stream-json",
      "--trust",
      opts.force ? "--force" : "--mode",
      ...(opts.force ? [] : ["plan"]),
      "--model", opts.model,
      ...(opts.session ? ["--resume", opts.session] : []),
      ...(pluginDir ? ["--plugin-dir", pluginDir] : []),
    ],
    envKeys: ["CURSOR_AGENT_BIN"],
  },
};
writeFileSync(join(opts.outDir, "result.json"), JSON.stringify(result, null, 2) + "\\n");
process.exit(0);
`;

const READ_ONLY_STAGES = ["plan", "plan_review", "execute_review"];
const WRITE_STAGES = ["implement", "direct_implement"];

function tempWorld() {
  const root = mkdtempSync(join(tmpdir(), "cursor-adapter-"));
  const repoRoot = join(root, "repo");
  const outDir = join(root, "out");
  mkdirSync(repoRoot);
  mkdirSync(outDir);
  const relayPath = join(root, "stub-cursor-relay.mjs");
  writeFileSync(relayPath, STUB_SOURCE);
  return { root, repoRoot, outDir, relayPath };
}

function fakeJob(stage = "plan", extra = {}) {
  const write = WRITE_STAGES.includes(stage);
  const contract = STAGE_CONTRACTS[stage];
  return {
    jobId: `job_${stage}`,
    idempotencyKey: `task:${stage}:1`,
    taskId: "task",
    stage,
    attempt: 1,
    workspace: {
      repoRoot: extra.repoRoot || "/tmp",
      branch: "main",
      expectedHead: "a".repeat(40),
      requireCleanAtStart: true,
    },
    agent: {
      adapter: "cursor",
      profile: contract.profile,
      model: "claude-opus-5-thinking-high",
      thinking: "high",
      sessionId: extra.sessionId === undefined ? null : extra.sessionId,
    },
    permissions: { mode: write ? "write" : "read-only" },
    inputs: [],
    expectedOutput: { kind: contract.outputKind, schema: contract.outputSchema },
    verification: [],
    limits: { timeoutSeconds: extra.timeoutSeconds === undefined ? null : extra.timeoutSeconds },
  };
}

function buildArgs(job, extra = {}) {
  const built = tryBuildCursorRelayArgs({
    briefPath: extra.briefPath || "/tmp/brief.txt",
    repoRoot: extra.repoRoot || job.workspace.repoRoot,
    adapterOutDir: extra.adapterOutDir || "/tmp/adapter/primary",
    job,
    phase: extra.phase || "primary",
    pluginDir: extra.pluginDir || "/tmp/plugin",
    recovery: extra.recovery || false,
    env: extra.env || process.env,
  });
  assert.equal(built.ok, true, built.error && built.error.message);
  return built.args;
}

function flagValue(args, flag) {
  const index = args.indexOf(flag);
  return index === -1 ? undefined : args[index + 1];
}

async function runAdapter({ world, job, brief = "do the work", env = {}, eventsPath }) {
  const path = eventsPath || join(world.outDir, "events.jsonl");
  const writer = createEventWriter({ path, jobId: job.jobId, stage: job.stage });
  const result = await runCursorAdapter({
    job,
    brief,
    outDir: world.outDir,
    events: writer,
    relayPath: world.relayPath,
    env: { ...process.env, ...env },
  });
  return { result, writer, eventsPath: path };
}

test("golden argv: read-only stages emit --read-only and write stages emit --force", () => {
  for (const stage of READ_ONLY_STAGES) {
    const args = buildArgs(fakeJob(stage));
    assert.ok(args.includes("--read-only"), stage);
    assert.ok(!args.includes("--force"), stage);
  }
  for (const stage of WRITE_STAGES) {
    const args = buildArgs(fakeJob(stage));
    assert.ok(args.includes("--force"), stage);
    assert.ok(!args.includes("--read-only"), stage);
  }
});

test("golden argv: --model slug, --plugin-dir present, --timeout omitted when null", () => {
  const pluginDir = "/tmp/plugin-dir";
  const args = buildArgs(fakeJob("plan"), { pluginDir });
  assert.equal(flagValue(args, "--model"), "claude-opus-5-thinking-high");
  assert.equal(flagValue(args, "--plugin-dir"), pluginDir);
  assert.ok(args.includes("--brief"));
  assert.ok(args.includes("--cd"));
  assert.ok(args.includes("--out-dir"));
  assert.equal(args.includes("--timeout"), false);
  assert.equal(args.includes("--session"), false);
});

test("golden argv: --timeout is emitted only when set, resume uses --session", () => {
  const job = fakeJob("implement", { timeoutSeconds: 90, sessionId: "sess-resume" });
  const args = buildArgs(job);
  assert.equal(flagValue(args, "--timeout"), "90s");
  assert.equal(flagValue(args, "--session"), "sess-resume");
  assert.ok(args.includes("--force"));
});

test("golden argv: recovery is --read-only even for implement and resumes the observed session", () => {
  const job = fakeJob("implement", { sessionId: "sess-observed" });
  job._recoverySessionId = "sess-observed";
  const args = buildArgs(job, { recovery: true, pluginDir: "/tmp/recovery-plugin" });
  assert.ok(args.includes("--read-only"));
  assert.ok(!args.includes("--force"));
  assert.equal(flagValue(args, "--session"), "sess-observed");
  assert.equal(flagValue(args, "--plugin-dir"), "/tmp/recovery-plugin");
});

test("unknown stage is typed invalid_job", () => {
  const job = fakeJob("plan");
  job.stage = "not_a_stage";
  const built = tryBuildCursorRelayArgs({
    briefPath: "/tmp/brief.txt",
    repoRoot: "/tmp/repo",
    adapterOutDir: "/tmp/out",
    job,
    phase: "primary",
    pluginDir: "/tmp/plugin",
    recovery: false,
  });
  assert.equal(built.ok, false);
  assert.equal(built.error.kind, "invalid_job");
  assert.equal(built.error.path, "/stage");
});

test("status mapping table: timeout/failed/aborted/unavailable/missing result.json", async () => {
  const cases = [
    { status: "timeout", expectedStatus: "timed_out", expectedKind: "timed_out" },
    { status: "failed", expectedStatus: "failed", expectedKind: "adapter_failed" },
    { status: "aborted", expectedStatus: "aborted", expectedKind: "aborted" },
    { status: "unavailable", expectedStatus: "unavailable", expectedKind: "adapter_unavailable" },
  ];
  for (const item of cases) {
    const world = tempWorld();
    try {
      const job = fakeJob("plan", { repoRoot: world.repoRoot });
      const { result } = await runAdapter({
        world,
        job,
        env: { CURSOR_STUB_STATUS: item.status, CURSOR_STUB_SUBMIT: "missing" },
      });
      assert.equal(result.status, item.expectedStatus, item.status);
      assert.equal(result.error.kind, item.expectedKind, item.status);
      assert.equal(result.recovered, false, item.status);
    } finally {
      rmSync(world.root, { recursive: true, force: true });
    }
  }

  const world = tempWorld();
  try {
    const job = fakeJob("plan", { repoRoot: world.repoRoot });
    const { result } = await runAdapter({
      world,
      job,
      env: { CURSOR_STUB_NO_RESULT: "1", CURSOR_STUB_SUBMIT: "missing" },
    });
    assert.equal(result.status, "failed");
    assert.equal(result.error.kind, "adapter_failed");
    assert.match(result.error.message, /no result\.json/);
  } finally {
    rmSync(world.root, { recursive: true, force: true });
  }
});

test("session_mismatch both directions: completed without sessionId, and sessionId !== expected", async () => {
  const missingWorld = tempWorld();
  try {
    const job = fakeJob("plan", { repoRoot: missingWorld.repoRoot, sessionId: "sess-expected" });
    const { result } = await runAdapter({
      world: missingWorld,
      job,
      env: { CURSOR_STUB_SESSION_MODE: "missing", CURSOR_STUB_SUBMIT: "ok" },
    });
    assert.equal(result.error.kind, "session_mismatch");
    assert.equal(result.status, "failed");
    assert.equal(result.recovered, false);
  } finally {
    rmSync(missingWorld.root, { recursive: true, force: true });
  }

  const mismatchWorld = tempWorld();
  try {
    const job = fakeJob("plan", { repoRoot: mismatchWorld.repoRoot, sessionId: "sess-expected" });
    const { result } = await runAdapter({
      world: mismatchWorld,
      job,
      env: { CURSOR_STUB_SESSION_MODE: "mismatch", CURSOR_STUB_SUBMIT: "ok" },
    });
    assert.equal(result.error.kind, "session_mismatch");
    assert.match(result.error.message, /sess-other/);
    assert.equal(result.recovered, false);
  } finally {
    rmSync(mismatchWorld.root, { recursive: true, force: true });
  }
});

test("completed + missing triggers exactly one recovery; argv uses same session, --read-only, fresh plugin dir", async () => {
  const world = tempWorld();
  try {
    const job = fakeJob("implement", { repoRoot: world.repoRoot });
    const { result } = await runAdapter({
      world,
      job,
      env: {
        CURSOR_STUB_SUBMIT: "missing",
        CURSOR_STUB_SUBMIT_RECOVERY: "ok",
        CURSOR_STUB_SESSION: "sess-primary",
      },
    });
    assert.equal(result.recovered, true);
    assert.equal(result.adapterRuns.length, 2);
    assert.equal(result.adapterRuns[1].phase, "output-recovery");
    assert.equal(result.status, "completed");
    assert.equal(result.error, null);
    assert.equal(result.sessionId, "sess-primary");
    assert.equal(result.structuredOutput.tool, "submit_implementation");
    assert.equal(result.structuredOutput.payload.tool, "submit_implementation");

    const recoveryArgv = JSON.parse(readFileSync(join(world.outDir, "adapter", "output-recovery", "relay-argv.json"), "utf8"));
    assert.ok(recoveryArgv.includes("--read-only"));
    assert.ok(!recoveryArgv.includes("--force"));
    assert.equal(flagValue(recoveryArgv, "--session"), "sess-primary");

    const primaryRecord = JSON.parse(readFileSync(join(world.outDir, "adapter", "primary", "spawn-record.json"), "utf8"));
    const recoveryRecord = JSON.parse(readFileSync(join(world.outDir, "adapter", "output-recovery", "spawn-record.json"), "utf8"));
    assert.equal(primaryRecord.adapter, "cursor");
    assert.equal(recoveryRecord.adapter, "cursor");
    assert.notEqual(recoveryRecord.pluginDir, primaryRecord.pluginDir);
    assert.notEqual(recoveryRecord.runNonce, primaryRecord.runNonce);
    assert.equal(flagValue(recoveryArgv, "--plugin-dir"), recoveryRecord.pluginDir);

    const recoveryBrief = readFileSync(join(world.outDir, "adapter", "output-recovery", "brief.txt"), "utf8");
    const recoveryConfigPath = join(recoveryRecord.pluginDir, "config.json");
    const recoveryConfig = JSON.parse(readFileSync(recoveryConfigPath, "utf8"));
    const recoveryJob = {
      ...job,
      agent: { ...job.agent, sessionId: "sess-primary" },
      _recoverySessionId: "sess-primary",
    };
    assert.equal(recoveryBrief, compileCursorRecoveryBrief(recoveryJob, {
      submitBinding: recoveryConfig,
      submitConfigPath: recoveryConfigPath,
    }));
  } finally {
    rmSync(world.root, { recursive: true, force: true });
  }
});

test("duplicate/invalid/timeout/aborted are never recovered", async () => {
  const cases = [
    { env: { CURSOR_STUB_SUBMIT: "duplicate" }, kind: "structured_output_duplicate", recovered: false },
    { env: { CURSOR_STUB_SUBMIT: "invalid" }, kind: "structured_output_invalid", recovered: false },
    { env: { CURSOR_STUB_STATUS: "timeout", CURSOR_STUB_SUBMIT: "missing" }, kind: "timed_out", recovered: false },
    { env: { CURSOR_STUB_STATUS: "aborted", CURSOR_STUB_SUBMIT: "missing" }, kind: "aborted", recovered: false },
  ];
  for (const item of cases) {
    const world = tempWorld();
    try {
      const job = fakeJob("implement", { repoRoot: world.repoRoot });
      const { result } = await runAdapter({ world, job, env: item.env });
      assert.equal(result.recovered, false, item.kind);
      assert.equal(result.adapterRuns.length, 1, item.kind);
      assert.equal(result.error.kind, item.kind, item.kind);
    } finally {
      rmSync(world.root, { recursive: true, force: true });
    }
  }
});

test("resolvedModel and usage propagate from relay result.json", async () => {
  const world = tempWorld();
  try {
    const job = fakeJob("plan", { repoRoot: world.repoRoot });
    const usage = { inputTokens: 7, outputTokens: 13, cacheRead: 2 };
    const { result } = await runAdapter({
      world,
      job,
      env: {
        CURSOR_STUB_SUBMIT: "ok",
        CURSOR_STUB_RESOLVED_MODEL: "Claude Opus 5 1M Thinking",
        CURSOR_STUB_USAGE: JSON.stringify(usage),
      },
    });
    assert.equal(result.status, "completed");
    assert.equal(result.resolvedModel, "Claude Opus 5 1M Thinking");
    assert.deepEqual(result.usage, usage);
    assert.equal(result.recovered, false);
    assert.equal(result.structuredOutput.tool, "submit_plan");
    const spawnRecord = JSON.parse(readFileSync(join(world.outDir, "adapter", "primary", "spawn-record.json"), "utf8"));
    assert.equal(spawnRecord.stage, "plan");
    assert.equal(spawnRecord.adapter, "cursor");
    assert.equal(spawnRecord.expectedTool, "submit_plan");
    assert.ok(Array.isArray(spawnRecord.argv));
    assert.ok(spawnRecord.argv.includes("--plugin-dir"));
  } finally {
    rmSync(world.root, { recursive: true, force: true });
  }
});
