import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
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
import test from "node:test";

import {
  buildArgv,
  consultedEnvKeys,
  cursorAgentBin,
  parseArgs,
  parseDuration,
} from "../relay.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const RELAY = join(here, "..", "relay.mjs");

const STUB_SOURCE = `#!/usr/bin/env node
import { writeFileSync } from "node:fs";

if (process.argv.includes("--version")) {
  process.stdout.write("2026.07.23-stub\\n");
  process.exit(0);
}

const dumpPath = process.env.CURSOR_STUB_DUMP;
if (dumpPath) {
  writeFileSync(dumpPath, \`\${JSON.stringify({ argv: process.argv.slice(2) })}\\n\`, "utf8");
}

const sleepMs = Number(process.env.CURSOR_STUB_SLEEP_MS || 0);
if (sleepMs > 0) {
  const ia = new Int32Array(new SharedArrayBuffer(4));
  Atomics.wait(ia, 0, 0, sleepMs);
}

const sessionId = process.env.CURSOR_STUB_SESSION || "stub-session-1";
const model = process.env.CURSOR_STUB_MODEL || "stub-model";
const isError = process.env.CURSOR_STUB_IS_ERROR === "1";
const exitCode = Number(process.env.CURSOR_STUB_EXIT || 0);

process.stdout.write(\`\${JSON.stringify({
  type: "system",
  subtype: "init",
  session_id: sessionId,
  model,
  permissionMode: "plan",
})}\\n\`);
process.stdout.write(\`\${JSON.stringify({
  type: "assistant",
  message: { content: [{ type: "text", text: "stub assistant" }] },
})}\\n\`);
process.stdout.write(\`\${JSON.stringify({
  type: "result",
  session_id: sessionId,
  result: "stub final",
  is_error: isError,
  usage: { input_tokens: 1, output_tokens: 1 },
})}\\n\`);
process.exit(exitCode);
`;

function tempDir(prefix = "cursor-relay-") {
  return mkdtempSync(join(tmpdir(), prefix));
}

function rmDir(dir) {
  rmSync(dir, { recursive: true, force: true });
}

function installStub(dir) {
  const stubJs = join(dir, "stub-agent.mjs");
  const stubBin = join(dir, "stub-agent");
  writeFileSync(stubJs, STUB_SOURCE, "utf8");
  writeFileSync(
    stubBin,
    `#!/bin/sh\nexec ${JSON.stringify(process.execPath)} ${JSON.stringify(stubJs)} "$@"\n`,
    "utf8",
  );
  chmodSync(stubBin, 0o755);
  return stubBin;
}

function hermeticEnv(overrides = {}) {
  const env = { ...process.env, ...overrides };
  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined) delete env[key];
    else env[key] = value;
  }
  return env;
}

function runRelay(args, env, options = {}) {
  return spawnSync(process.execPath, [RELAY, ...args], {
    env,
    encoding: "utf8",
    timeout: options.timeout ?? 30_000,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function setupRun(overrides = {}) {
  const tmp = tempDir();
  const workDir = join(tmp, "work");
  const outDir = join(tmp, "out");
  const pluginA = join(tmp, "plugin-a");
  const pluginB = join(tmp, "plugin-b");
  mkdirSync(workDir, { recursive: true });
  mkdirSync(outDir, { recursive: true });
  mkdirSync(pluginA, { recursive: true });
  mkdirSync(pluginB, { recursive: true });
  const briefPath = join(tmp, "brief.txt");
  writeFileSync(briefPath, "do the work\n");
  const dumpPath = join(tmp, "stub-dump.json");
  const stubBin = installStub(tmp);
  const env = hermeticEnv({
    CURSOR_AGENT_BIN: stubBin,
    CURSOR_STUB_DUMP: dumpPath,
    ...overrides.env,
  });
  const args = ["--brief", briefPath, "--cd", workDir, "--out-dir", outDir];
  return {
    tmp,
    workDir,
    outDir,
    pluginA,
    pluginB,
    briefPath,
    dumpPath,
    stubBin,
    env,
    args,
    cleanup() { rmDir(tmp); },
  };
}

function readResult(outDir) {
  return JSON.parse(readFileSync(join(outDir, "result.json"), "utf8"));
}

function readDump(dumpPath) {
  return JSON.parse(readFileSync(dumpPath, "utf8"));
}

test("buildArgv emits --plugin-dir after the base flags, in given order", () => {
  const argv = buildArgv({
    readOnly: true,
    force: false,
    sandbox: null,
    model: null,
    session: null,
    resumeLast: false,
    addDirs: [],
    pluginDirs: ["/abs/plugin-a", "/abs/plugin-b"],
  });
  assert.deepEqual(argv.slice(0, 4), ["--print", "--output-format", "stream-json", "--trust"]);
  const first = argv.indexOf("--plugin-dir");
  assert.ok(first >= 0);
  assert.equal(argv[first + 1], "/abs/plugin-a");
  assert.equal(argv[first + 2], "--plugin-dir");
  assert.equal(argv[first + 3], "/abs/plugin-b");
  assert.ok(first > argv.indexOf("--trust"));
});

test("parseArgs accepts repeatable absolute --plugin-dir and rejects missing or relative dirs", () => {
  const dir = tempDir("cursor-plugin-");
  const extra = join(dir, "extra");
  mkdirSync(extra);
  try {
    const opts = parseArgs(["--plugin-dir", dir, "--plugin-dir", extra]);
    assert.deepEqual(opts.pluginDirs, [dir, extra]);
  } finally {
    rmDir(dir);
  }

  const ctx = setupRun();
  try {
    const missing = runRelay(
      [...ctx.args, "--plugin-dir", join(ctx.tmp, "no-such-plugin")],
      ctx.env,
    );
    assert.equal(missing.status, 2, missing.stderr);
    assert.match(missing.stderr, /--plugin-dir not found/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);

    const relative = runRelay([...ctx.args, "--plugin-dir", "relative/plugin"], ctx.env);
    assert.equal(relative.status, 2, relative.stderr);
    assert.match(relative.stderr, /--plugin-dir must be an absolute path/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);
  } finally {
    ctx.cleanup();
  }
});

test("CURSOR_AGENT_BIN is honored and spawn.argv matches the stub dump", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay(
      [...ctx.args, "--plugin-dir", ctx.pluginA, "--plugin-dir", ctx.pluginB],
      ctx.env,
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const dump = readDump(ctx.dumpPath);
    const result = readResult(ctx.outDir);
    assert.deepEqual(result.spawn.argv, dump.argv);
    assert.deepEqual(result.pluginDirs, [ctx.pluginA, ctx.pluginB]);
    const pluginIdx = dump.argv.indexOf("--plugin-dir");
    assert.equal(dump.argv[pluginIdx + 1], ctx.pluginA);
    assert.equal(dump.argv[pluginIdx + 2], "--plugin-dir");
    assert.equal(dump.argv[pluginIdx + 3], ctx.pluginB);
    assert.ok(result.spawn.envKeys.includes("CURSOR_AGENT_BIN"));
    assert.equal(result.spawn.envKeys.includes(ctx.stubBin), false);
    assert.doesNotMatch(JSON.stringify(result.spawn), /CURSOR_AGENT_BIN=/);
  } finally {
    ctx.cleanup();
  }
});

test("result.json includes spawn and pluginDirs on completed and unavailable paths", () => {
  const ctx = setupRun();
  try {
    const ok = runRelay(ctx.args, ctx.env);
    assert.equal(ok.status, 0, ok.stderr);
    const completed = readResult(ctx.outDir);
    assert.equal(completed.status, "completed");
    assert.deepEqual(completed.pluginDirs, []);
    assert.ok(Array.isArray(completed.spawn.argv));
    assert.ok(Array.isArray(completed.spawn.envKeys));
    assert.ok(completed.spawn.envKeys.includes("CURSOR_AGENT_BIN"));
    assert.equal(completed.spawn.argv.includes("--plugin-dir"), false);

    const missingBin = join(ctx.tmp, "no-such-agent");
    const unavailable = runRelay(ctx.args, hermeticEnv({
      CURSOR_AGENT_BIN: missingBin,
      CURSOR_API_KEY: "super-secret-key",
    }));
    assert.equal(unavailable.status, 127, unavailable.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.status, "unavailable");
    assert.deepEqual(result.pluginDirs, []);
    assert.ok(Array.isArray(result.spawn.argv));
    assert.ok(result.spawn.envKeys.includes("CURSOR_AGENT_BIN"));
    assert.ok(result.spawn.envKeys.includes("CURSOR_API_KEY"));
    assert.doesNotMatch(JSON.stringify(result), /super-secret-key/);
  } finally {
    ctx.cleanup();
  }
});

test("explicit read-only and sandbox overrides remain available", () => {
  const ctx = setupRun();
  try {
    const readOnly = runRelay([...ctx.args, "--read-only", "--session", "sess-abc"], ctx.env);
    assert.equal(readOnly.status, 0, readOnly.stderr);
    const {argv} = readDump(ctx.dumpPath);
    assert.equal(argv[argv.indexOf("--mode") + 1], "plan");
    assert.equal(argv.includes("--force"), false);
    assert.equal(argv[argv.indexOf("--resume") + 1], "sess-abc");
    const sandbox = runRelay([...ctx.args, "--sandbox", "enabled"], ctx.env);
    assert.equal(sandbox.status, 0, sandbox.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.sandbox, "enabled");
    assert.equal(result.force, true);
  } finally { ctx.cleanup(); }
});

test("documentation and help contain no retired development workflow", () => {
  const skill = join(here, "..", "..");
  for (const file of ["SKILL.md", "references/dispatch-and-poll.md", "scripts/relay.mjs"]) {
    const content = readFileSync(join(skill, file), "utf8");
    assert.doesNotMatch(content, /Development-Orchestrator|Origin grounding|write-plan|execute-plan|Card contract|Dispatcher worker|delegate-setup|review-and-land|re-run the project gates yourself|committing is always the/i);
  }
  assert.equal(existsSync(join(skill, "scripts/review-relay.mjs")), false);
});

test("retired fleet lane option is rejected without loading another skill", () => {
  const child = runRelay(["--lane", "old-lane"], process.env);
  assert.equal(child.status, 2);
  assert.match(child.stderr, /unknown option: --lane/);
});

test("fresh and resumed runs default to full permissions", () => {
  const ctx = setupRun();
  try {
    for (const extra of [[], ["--session", "sess-abc"], ["--resume-last"]]) {
      const spawned = runRelay([...ctx.args, ...extra], ctx.env);
      assert.equal(spawned.status, 0, spawned.stderr);
      const { argv } = readDump(ctx.dumpPath);
      assert.equal(argv.includes("--force"), true);
      assert.equal(argv.includes("--mode"), false);
      assert.equal(argv[argv.indexOf("--sandbox") + 1], "disabled");
      const result = readResult(ctx.outDir);
      assert.equal(result.readOnly, false);
      assert.equal(result.force, true);
      assert.equal(result.sandbox, "disabled");
      if (extra[0] === "--session") {
        assert.equal(argv[argv.indexOf("--resume") + 1], "sess-abc");
      }
      if (extra[0] === "--resume-last") assert.equal(argv.includes("--continue"), true);
    }
  } finally {
    ctx.cleanup();
  }
});

test("--timeout parse rejects invalid durations and maps watchdog kills to timeout", () => {
  assert.equal(parseDuration("90s"), 90_000);
  assert.equal(parseDuration("1h"), 3_600_000);
  assert.equal(parseDuration("45m"), 2_700_000);
  assert.equal(parseDuration("abc"), null);
  assert.equal(parseDuration("0s"), null);

  const ctx = setupRun();
  try {
    const invalid = runRelay([...ctx.args, "--timeout", "abc"], ctx.env);
    assert.equal(invalid.status, 2, invalid.stderr);
    assert.match(invalid.stderr, /--timeout "abc" is invalid/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);

    const timed = runRelay(
      [...ctx.args, "--timeout", "1s"],
      hermeticEnv({
        CURSOR_AGENT_BIN: ctx.stubBin,
        CURSOR_STUB_DUMP: ctx.dumpPath,
        CURSOR_STUB_SLEEP_MS: "15000",
      }),
    );
    assert.notEqual(timed.status, 0, timed.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.status, "timeout");
    assert.ok(result.spawn);
    assert.ok(Array.isArray(result.spawn.argv));
    assert.ok(Array.isArray(result.spawn.envKeys));
  } finally {
    ctx.cleanup();
  }
});

test("status mapping: completed, failed (exit and is_error), timeout, unavailable", () => {
  const ctx = setupRun();
  try {
    const completed = runRelay(ctx.args, ctx.env);
    assert.equal(completed.status, 0, completed.stderr);
    assert.equal(readResult(ctx.outDir).status, "completed");

    const failedExit = runRelay(ctx.args, hermeticEnv({
      CURSOR_AGENT_BIN: ctx.stubBin,
      CURSOR_STUB_DUMP: ctx.dumpPath,
      CURSOR_STUB_EXIT: "1",
    }));
    assert.equal(failedExit.status, 1, failedExit.stderr);
    const failedExitResult = readResult(ctx.outDir);
    assert.equal(failedExitResult.status, "failed");
    assert.ok(failedExitResult.spawn);

    const failedError = runRelay(ctx.args, hermeticEnv({
      CURSOR_AGENT_BIN: ctx.stubBin,
      CURSOR_STUB_DUMP: ctx.dumpPath,
      CURSOR_STUB_IS_ERROR: "1",
    }));
    assert.equal(failedError.status, 1, failedError.stderr);
    const failedErrorResult = readResult(ctx.outDir);
    assert.equal(failedErrorResult.status, "failed");
    assert.ok(failedErrorResult.spawn);

    const unavailable = runRelay(ctx.args, hermeticEnv({
      CURSOR_AGENT_BIN: join(ctx.tmp, "missing-agent"),
    }));
    assert.equal(unavailable.status, 127);
    assert.equal(readResult(ctx.outDir).status, "unavailable");
  } finally {
    ctx.cleanup();
  }
});

test("cursorAgentBin defaults to agent; consultedEnvKeys records names only", () => {
  assert.equal(cursorAgentBin({}), "agent");
  assert.equal(cursorAgentBin({ CURSOR_AGENT_BIN: "/tmp/fake-agent" }), "/tmp/fake-agent");
  assert.deepEqual(consultedEnvKeys({}), []);
  assert.deepEqual(
    consultedEnvKeys({ CURSOR_AGENT_BIN: "/bin/x", CURSOR_API_KEY: "secret" }),
    ["CURSOR_AGENT_BIN", "CURSOR_API_KEY"],
  );
});
