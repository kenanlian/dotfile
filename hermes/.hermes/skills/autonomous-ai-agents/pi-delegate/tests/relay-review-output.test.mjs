import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const RELAY = join(TEST_DIR, "..", "scripts", "relay.mjs");
const STUB = join(TEST_DIR, "fixtures", "stub-pi.mjs");
const REVIEW_SUBMIT_ROOT = join(TEST_DIR, "..", "extensions", "review-submit");

const PLAN_PAYLOAD = {
  schema: "development-plan-review.v1",
  board: "dotfile",
  card_id: "t_example",
  feature_id: "f_example",
  review_run_id: 1,
  round: 1,
  plan: { path: "/tmp/plan.md", sha256: "a".repeat(64) },
  verdict: "pass",
  summary: "ok",
  required_revisions: [],
};

function dashEPaths(argv) {
  const paths = [];
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "-e") paths.push(argv[i + 1]);
  }
  return paths;
}

function toolsArg(argv) {
  const index = argv.indexOf("--tools");
  return index >= 0 ? argv[index + 1] : null;
}

function makeFakeRoots(tmp) {
  const roots = join(tmp, "roots");
  const delegateRoot = join(roots, "delegate-agent");
  mkdirSync(delegateRoot, { recursive: true });
  writeFileSync(join(delegateRoot, "index.ts"), "export {};\n");
  return { delegateRoot };
}

function hermeticEnv(overrides = {}) {
  const env = { ...process.env, ...overrides };
  for (const key of Object.keys(env)) {
    if (key.startsWith("PI_AUTO_HANDOFF_")) delete env[key];
  }
  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined) delete env[key];
    else env[key] = value;
  }
  return env;
}

function runRelay(args, env) {
  return spawnSync(process.execPath, [RELAY, ...args], {
    env,
    encoding: "utf8",
    timeout: 30_000,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function setupRun(extra = {}) {
  const tmp = mkdtempSync(join(tmpdir(), "relay-review-output-"));
  const workDir = join(tmp, "work");
  const outDir = join(tmp, "out");
  const dumpPath = join(tmp, "stub-dump.json");
  mkdirSync(workDir, { recursive: true });
  mkdirSync(outDir, { recursive: true });
  const { delegateRoot } = makeFakeRoots(tmp);
  const briefPath = join(tmp, "brief.txt");
  writeFileSync(briefPath, "review the plan\n");
  const env = hermeticEnv({
    PI_BIN: STUB,
    PI_DELEGATE_AGENT_ROOT: delegateRoot,
    PI_REVIEW_SUBMIT_ROOT: REVIEW_SUBMIT_ROOT,
    PI_STUB_DUMP: dumpPath,
    ...extra.env,
  });
  const args = [
    "--brief", briefPath,
    "--cd", workDir,
    "--out-dir", outDir,
    ...(extra.args || []),
  ];
  return {
    tmp, workDir, outDir, dumpPath, briefPath, delegateRoot, env, args,
    cleanup() { rmSync(tmp, { recursive: true, force: true }); },
  };
}

function readResult(outDir) {
  return JSON.parse(readFileSync(join(outDir, "result.json"), "utf8"));
}

function readDump(dumpPath) {
  return JSON.parse(readFileSync(dumpPath, "utf8"));
}

function toolEnd(tool, payload, { isError = false } = {}) {
  return {
    type: "tool_execution_end",
    toolCallId: "call-1",
    toolName: tool,
    result: {
      content: [{ type: "text", text: `Submitted ${tool}` }],
      details: payload,
    },
    isError,
  };
}

test("absent --review-output leaves structuredOutput null and read-only tools unchanged", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay(ctx.args, ctx.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.schema, "delegate-relay.result.v1");
    assert.equal(result.status, "completed");
    assert.equal(result.structuredOutput, null);
    assert.equal(result.structuredOutputError, null);
    const dump = readDump(ctx.dumpPath);
    assert.ok(dump.argv.includes("--no-extensions"));
    assert.deepEqual(dashEPaths(dump.argv), [ctx.delegateRoot]);
    assert.equal(toolsArg(dump.argv), "read,grep,find,ls,delegate_agent");
  } finally {
    ctx.cleanup();
  }
});

test("write-mode relays reject --review-output", () => {
  const ctx = setupRun({ args: ["--write", "--review-output", "plan"] });
  try {
    const spawned = runRelay(ctx.args, ctx.env);
    assert.equal(spawned.status, 2, spawned.stderr);
    assert.match(spawned.stderr, /--review-output is not valid with --write/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);
  } finally {
    ctx.cleanup();
  }
});

test("exactly one successful expected-tool result is captured into structuredOutput", () => {
  const ctx = setupRun({
    args: ["--review-output", "plan"],
    env: {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan_review", PLAN_PAYLOAD)]),
    },
  });
  try {
    const spawned = runRelay(ctx.args, ctx.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.status, "completed");
    assert.deepEqual(result.structuredOutput, {
      tool: "submit_plan_review",
      payload: PLAN_PAYLOAD,
    });
    assert.equal(result.structuredOutputError, null);
    assert.equal(result.finalMessage, "stub final");
    const dump = readDump(ctx.dumpPath);
    assert.ok(dump.argv.includes("--no-extensions"));
    assert.deepEqual(dashEPaths(dump.argv), [ctx.delegateRoot, REVIEW_SUBMIT_ROOT]);
    assert.equal(
      toolsArg(dump.argv),
      "read,grep,find,ls,delegate_agent,submit_plan_review",
    );
  } finally {
    ctx.cleanup();
  }
});

test("missing expected-tool result yields null plus diagnostic", () => {
  const ctx = setupRun({ args: ["--review-output", "execute"] });
  try {
    const spawned = runRelay(ctx.args, ctx.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.structuredOutput, null);
    assert.match(result.structuredOutputError, /submit_execute_review was not called/);
    const dump = readDump(ctx.dumpPath);
    assert.equal(
      toolsArg(dump.argv),
      "read,grep,find,ls,delegate_agent,submit_execute_review",
    );
  } finally {
    ctx.cleanup();
  }
});

test("duplicate successful expected-tool results yield null plus diagnostic", () => {
  const first = toolEnd("submit_plan_review", PLAN_PAYLOAD);
  const second = {
    ...toolEnd("submit_plan_review", { ...PLAN_PAYLOAD, summary: "second" }),
    toolCallId: "call-2",
  };
  const ctx = setupRun({
    args: ["--review-output", "plan"],
    env: { PI_STUB_EVENTS: JSON.stringify([first, second]) },
  });
  try {
    const spawned = runRelay(ctx.args, ctx.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.structuredOutput, null);
    assert.match(result.structuredOutputError, /succeeded 2 times/);
  } finally {
    ctx.cleanup();
  }
});

test("error result from the expected tool yields null plus diagnostic", () => {
  const ctx = setupRun({
    args: ["--review-output", "plan"],
    env: {
      PI_STUB_EVENTS: JSON.stringify([
        toolEnd("submit_plan_review", PLAN_PAYLOAD, { isError: true }),
      ]),
    },
  });
  try {
    const spawned = runRelay(ctx.args, ctx.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.structuredOutput, null);
    assert.match(result.structuredOutputError, /returned an error result/);
  } finally {
    ctx.cleanup();
  }
});

test("recovery allowlist contains only the stage submit tool and requires --session", () => {
  const ctx = setupRun({
    args: [
      "--review-output", "plan",
      "--review-output-recovery",
      "--session", "stub-sess-1",
    ],
    env: {
      PI_STUB_SESSION: "stub-sess-1",
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan_review", PLAN_PAYLOAD)]),
    },
  });
  try {
    const spawned = runRelay(ctx.args, ctx.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const dump = readDump(ctx.dumpPath);
    assert.equal(toolsArg(dump.argv), "submit_plan_review");
    const promptIndex = dump.argv.indexOf("--append-system-prompt");
    assert.ok(promptIndex >= 0);
    assert.match(dump.argv[promptIndex + 1], /Output-only recovery turn/);
    assert.match(dump.argv[promptIndex + 1], /submit_plan_review/);
    assert.equal(dump.argv[dump.argv.indexOf("--session") + 1], "stub-sess-1");
    const result = readResult(ctx.outDir);
    assert.equal(result.resumed, true);
    assert.equal(result.structuredOutput.tool, "submit_plan_review");
  } finally {
    ctx.cleanup();
  }
});

test("--review-output-recovery without --session is a usage error", () => {
  const ctx = setupRun({ args: ["--review-output", "plan", "--review-output-recovery"] });
  try {
    const spawned = runRelay(ctx.args, ctx.env);
    assert.equal(spawned.status, 2, spawned.stderr);
    assert.match(spawned.stderr, /--review-output-recovery requires --session/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);
  } finally {
    ctx.cleanup();
  }
});
