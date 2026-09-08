import { test } from "node:test";
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

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const RELAY = join(TEST_DIR, "..", "scripts", "relay.mjs");
const STUB = join(TEST_DIR, "fixtures", "stub-pi.mjs");
const RELAY_SOURCE = readFileSync(RELAY, "utf8");

function dashEPaths(argv) {
  const paths = [];
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "-e") paths.push(argv[i + 1]);
  }
  return paths;
}

function makeFakeRoots(root) {
  const delegateRoot = join(root, "delegate-agent");
  const autoHandoffRoot = join(root, "pi-auto-handoff");
  mkdirSync(delegateRoot, { recursive: true });
  writeFileSync(join(delegateRoot, "index.ts"), "export {};\n");
  mkdirSync(join(autoHandoffRoot, "src"), { recursive: true });
  writeFileSync(join(autoHandoffRoot, "package.json"), '{"name":"pi-auto-handoff"}\n');
  writeFileSync(join(autoHandoffRoot, "src", "index.ts"), "export {};\n");
  return { delegateRoot, autoHandoffRoot };
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
  const tmp = mkdtempSync(join(tmpdir(), "relay-auto-handoff-"));
  const workDir = join(tmp, "work");
  const outDir = join(tmp, "out");
  const dumpPath = join(tmp, "stub-dump.json");
  mkdirSync(workDir, { recursive: true });
  mkdirSync(outDir, { recursive: true });
  const { delegateRoot, autoHandoffRoot } = makeFakeRoots(rootDir(tmp));
  const planFile = join(tmp, "accepted-plan.md");
  writeFileSync(planFile, "# accepted plan\n");
  const briefPath = join(tmp, "brief.txt");
  writeFileSync(briefPath, "do the work\n");
  const env = hermeticEnv({
    PI_BIN: STUB,
    PI_DELEGATE_AGENT_ROOT: delegateRoot,
    PI_AUTO_HANDOFF_ROOT: autoHandoffRoot,
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
    tmp, workDir, outDir, dumpPath, planFile, briefPath,
    delegateRoot, autoHandoffRoot, env, args,
    cleanup() { rmSync(tmp, { recursive: true, force: true }); },
  };
}

function rootDir(tmp) {
  return join(tmp, "roots");
}

function readResult(outDir) {
  return JSON.parse(readFileSync(join(outDir, "result.json"), "utf8"));
}

function readDump(dumpPath) {
  return JSON.parse(readFileSync(dumpPath, "utf8"));
}

test("V1 enabled argv/env/config derivation", () => {
  const ctx = setupRun({ args: ["--write"] });
  try {
    const spawned = runRelay(
      [...ctx.args, "--auto-handoff-plan", ctx.planFile],
      ctx.env,
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.status, "completed");
    assert.equal(result.schema, "delegate-relay.result.v1");
    assert.deepEqual(result.autoHandoff, {
      enabled: true,
      planFile: ctx.planFile,
      handoffDir: join(ctx.outDir, "auto-handoff"),
      extensionRoot: ctx.autoHandoffRoot,
    });
    const dump = readDump(ctx.dumpPath);
    assert.ok(dump.argv.includes("--no-extensions"));
    assert.deepEqual(dashEPaths(dump.argv), [ctx.delegateRoot, ctx.autoHandoffRoot]);
    assert.equal(dump.argv[dump.argv.indexOf("--tools") + 1], "read,grep,find,ls,bash,edit,write,delegate_agent");
    assert.equal(dump.argv[dump.argv.indexOf("--thinking") + 1], "high");
    assert.equal(dump.planEnv, ctx.planFile);
    assert.equal(dump.handoffEnv, join(ctx.outDir, "auto-handoff"));
    assert.match(spawned.stdout, /auto handoff: enabled/);
    assert.match(
      spawned.stdout,
      new RegExp(`auto handoff: enabled · plan ${ctx.planFile} · handoff ${join(ctx.outDir, "auto-handoff")}`.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    );
  } finally {
    ctx.cleanup();
  }
});

test("V2 disabled absence", () => {
  const ctx = setupRun({ args: ["--write"] });
  try {
    const spawned = runRelay(ctx.args, ctx.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.status, "completed");
    assert.deepEqual(result.autoHandoff, {
      enabled: false,
      planFile: null,
      handoffDir: null,
      extensionRoot: null,
    });
    const dump = readDump(ctx.dumpPath);
    assert.deepEqual(dashEPaths(dump.argv), [ctx.delegateRoot]);
    assert.equal(dump.planEnv, null);
    assert.equal(dump.handoffEnv, null);
    assert.doesNotMatch(spawned.stdout, /auto handoff:/);
  } finally {
    ctx.cleanup();
  }
});

test("V3 validation failures", () => {
  const cases = [
    { name: "relative path", plan: () => "relative/plan.md" },
    { name: "non-existent absolute path", plan: (tmp) => join(tmp, "missing-plan.md") },
    { name: "empty string", plan: () => "" },
    { name: "directory path", plan: (tmp) => tmp },
    {
      name: "zero-byte file",
      plan: (tmp) => {
        const emptyFile = join(tmp, "empty-plan.md");
        writeFileSync(emptyFile, "");
        return emptyFile;
      },
    },
  ];
  for (const item of cases) {
    const ctx = setupRun();
    try {
      const plan = item.plan(ctx.tmp);
      const spawned = runRelay(
        [...ctx.args, "--auto-handoff-plan", plan],
        ctx.env,
      );
      assert.equal(spawned.status, 2, `${item.name}: expected exit 2, got ${spawned.status}\n${spawned.stderr}`);
      assert.match(spawned.stderr, /--auto-handoff-plan/, item.name);
      assert.equal(existsSync(join(ctx.outDir, "result.json")), false, `${item.name}: result.json must not exist`);
    } finally {
      ctx.cleanup();
    }
  }
});

test("V4 resume/rework composition", () => {
  const ctx = setupRun({
    args: ["--session", "stub-sess-1", "--write"],
    env: { PI_STUB_SESSION: "stub-sess-1" },
  });
  try {
    const spawned = runRelay(
      [...ctx.args, "--auto-handoff-plan", ctx.planFile],
      ctx.env,
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.resumed, true);
    assert.equal(result.autoHandoff.enabled, true);
    const dump = readDump(ctx.dumpPath);
    const sessionIndex = dump.argv.indexOf("--session");
    assert.ok(sessionIndex >= 0);
    assert.equal(dump.argv[sessionIndex + 1], "stub-sess-1");
    assert.deepEqual(dashEPaths(dump.argv), [ctx.delegateRoot, ctx.autoHandoffRoot]);
    assert.equal(dump.planEnv, ctx.planFile);
    assert.equal(dump.handoffEnv, join(ctx.outDir, "auto-handoff"));
  } finally {
    ctx.cleanup();
  }
});

test("V5 child-extension isolation and no env mutation (source)", () => {
  const spawnCalls = [...RELAY_SOURCE.matchAll(/\bspawn\(/g)];
  assert.equal(spawnCalls.length, 1, "relay must spawn pi exactly once");
  const dispatchIndex = RELAY_SOURCE.indexOf("function dispatchToPi");
  assert.ok(dispatchIndex >= 0);
  assert.ok(
    RELAY_SOURCE.indexOf("spawn(") > dispatchIndex,
    "spawn( from node:child_process must be used only in dispatchToPi",
  );
  assert.doesNotMatch(RELAY_SOURCE, /process\.env\.PI_AUTO_HANDOFF_[A-Z0-9_]*\s*=/);
  assert.doesNotMatch(RELAY_SOURCE, /delete\s+process\.env\.PI_AUTO_HANDOFF_/);
  assert.match(RELAY_SOURCE, /argv\.push\("-e", extensionRoot\)/);
  assert.match(RELAY_SOURCE, /if \(autoHandoff\?\.enabled\) argv\.push\("-e", autoHandoff\.extensionRoot\)/);
});

test("V6 result evidence on failed path", () => {
  const ctx = setupRun({ args: ["--write"] });
  const failingStub = join(ctx.tmp, "failing-stub.mjs");
  writeFileSync(
    failingStub,
    `#!/usr/bin/env node
if (process.argv.includes("--version")) {
  process.stdout.write("0.85.1-stub\\n");
  process.exit(0);
}
process.exit(1);
`,
  );
  chmodSync(failingStub, 0o755);
  ctx.env.PI_BIN = failingStub;
  try {
    const spawned = runRelay(
      [...ctx.args, "--auto-handoff-plan", ctx.planFile],
      ctx.env,
    );
    assert.equal(spawned.status, 1, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.status, "failed");
    assert.equal(result.autoHandoff.enabled, true);
    assert.equal(result.autoHandoff.planFile, ctx.planFile);
    assert.equal(result.autoHandoff.handoffDir, join(ctx.outDir, "auto-handoff"));
    assert.equal(result.autoHandoff.extensionRoot, ctx.autoHandoffRoot);
  } finally {
    ctx.cleanup();
  }
});

test("V7 missing root fail-closed", () => {
  const ctx = setupRun({ args: ["--write"] });
  const emptyHome = join(ctx.tmp, "empty-home");
  mkdirSync(emptyHome, { recursive: true });
  const env = hermeticEnv({
    PI_BIN: STUB,
    PI_DELEGATE_AGENT_ROOT: ctx.delegateRoot,
    PI_STUB_DUMP: ctx.dumpPath,
    HOME: emptyHome,
    PI_AUTO_HANDOFF_ROOT: undefined,
  });
  try {
    const spawned = runRelay(
      [...ctx.args, "--auto-handoff-plan", ctx.planFile],
      env,
    );
    assert.equal(spawned.status, 1, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.status, "failed");
    assert.match(result.error, /auto-handoff extension root/);
    assert.equal(existsSync(ctx.dumpPath), false, "pi must not be dispatched beyond the version probe");
  } finally {
    ctx.cleanup();
  }
});
