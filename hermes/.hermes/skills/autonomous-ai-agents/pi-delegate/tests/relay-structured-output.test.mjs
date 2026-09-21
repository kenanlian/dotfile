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
  schema: "plan.v1",
  outcome: "completed",
  title: "ok",
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
  const genericRoot = join(roots, "stage-submit");
  mkdirSync(genericRoot, { recursive: true });
  writeFileSync(join(genericRoot, "index.ts"), "export {};\n");
  return { delegateRoot, genericRoot };
}

function hermeticEnv(overrides = {}) {
  const env = { ...process.env, ...overrides };
  for (const key of Object.keys(env)) {
    if (key.startsWith("PI_AUTO_HANDOFF_") || (key.startsWith("PI_STUB_") && !(key in overrides))) {
      delete env[key];
    }
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
  const tmp = mkdtempSync(join(tmpdir(), "relay-structured-output-"));
  const workDir = join(tmp, "work");
  const outDir = join(tmp, "out");
  const dumpPath = join(tmp, "stub-dump.json");
  mkdirSync(workDir, { recursive: true });
  mkdirSync(outDir, { recursive: true });
  const { delegateRoot, genericRoot } = makeFakeRoots(tmp);
  const briefPath = join(tmp, "brief.txt");
  writeFileSync(briefPath, "submit the plan\n");
  const env = hermeticEnv({
    PI_BIN: STUB,
    PI_DELEGATE_AGENT_ROOT: delegateRoot,
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
    tmp, workDir, outDir, dumpPath, briefPath, delegateRoot, genericRoot, env, args,
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

function genericFlags(extensionRoot, tool = "submit_plan") {
  return ["--structured-output-tool", tool, "--structured-output-extension", extensionRoot];
}

test("generic read-only run loads extension and captures one successful tool", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay(
      [...ctx.args, ...genericFlags(ctx.genericRoot), "--read-only"],
      {
        ...ctx.env,
        PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", PLAN_PAYLOAD)]),
      },
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(ctx.outDir);
    assert.equal(result.schema, "delegate-relay.result.v1");
    assert.equal(result.status, "completed");
    assert.deepEqual(result.structuredOutput, { tool: "submit_plan", payload: PLAN_PAYLOAD });
    assert.equal(result.structuredOutputError, null);
    const dump = readDump(ctx.dumpPath);
    assert.deepEqual(dashEPaths(dump.argv), [ctx.delegateRoot, ctx.genericRoot]);
    assert.equal(toolsArg(dump.argv), "read,grep,find,ls,delegate_agent,submit_plan");
  } finally {
    ctx.cleanup();
  }
});

test("generic write run allowlist includes write tools plus the submit tool", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay(
      [...ctx.args, ...genericFlags(ctx.genericRoot, "submit_implementation"), "--write"],
      {
        ...ctx.env,
        PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_implementation", { schema: "implementation.v1" })]),
      },
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const dump = readDump(ctx.dumpPath);
    assert.equal(
      toolsArg(dump.argv),
      "read,grep,find,ls,bash,edit,write,delegate_agent,submit_implementation",
    );
    const result = readResult(ctx.outDir);
    assert.equal(result.mode, "write");
    assert.equal(result.structuredOutput.tool, "submit_implementation");
  } finally {
    ctx.cleanup();
  }
});

test("generic recovery allowlist is only the submit tool and requires --session", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay(
      [
        ...ctx.args,
        ...genericFlags(ctx.genericRoot),
        "--structured-output-recovery",
        "--session", "stub-sess-1",
      ],
      {
        ...ctx.env,
        PI_STUB_SESSION: "stub-sess-1",
        PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", PLAN_PAYLOAD)]),
      },
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const dump = readDump(ctx.dumpPath);
    assert.equal(toolsArg(dump.argv), "submit_plan");
    const promptIndex = dump.argv.indexOf("--append-system-prompt");
    assert.ok(promptIndex >= 0);
    assert.match(dump.argv[promptIndex + 1], /Output-only recovery turn/);
    assert.match(dump.argv[promptIndex + 1], /submit_plan/);
    assert.equal(readResult(ctx.outDir).resumed, true);
  } finally {
    ctx.cleanup();
  }
});

test("recovery allowlist ignores --extra-tools", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay(
      [
        ...ctx.args,
        ...genericFlags(ctx.genericRoot),
        "--extra-tools", "todo",
        "--structured-output-recovery",
        "--session", "stub-sess-1",
      ],
      {
        ...ctx.env,
        PI_STUB_SESSION: "stub-sess-1",
        PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", PLAN_PAYLOAD)]),
      },
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const dump = readDump(ctx.dumpPath);
    assert.equal(toolsArg(dump.argv), "submit_plan");
    assert.ok(!toolsArg(dump.argv).split(",").includes("todo"));
  } finally {
    ctx.cleanup();
  }
});

test("generic missing, duplicate, and tool-error captures stay null plus diagnostic", () => {
  const missing = setupRun();
  try {
    const spawned = runRelay([...missing.args, ...genericFlags(missing.genericRoot)], missing.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(missing.outDir);
    assert.equal(result.structuredOutput, null);
    assert.match(result.structuredOutputError, /submit_plan was not called/);
  } finally {
    missing.cleanup();
  }

  const duplicate = setupRun();
  try {
    const first = toolEnd("submit_plan", PLAN_PAYLOAD);
    const second = { ...toolEnd("submit_plan", { ...PLAN_PAYLOAD, title: "second" }), toolCallId: "call-2" };
    const spawned = runRelay(
      [...duplicate.args, ...genericFlags(duplicate.genericRoot)],
      { ...duplicate.env, PI_STUB_EVENTS: JSON.stringify([first, second]) },
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(duplicate.outDir);
    assert.equal(result.structuredOutput, null);
    assert.match(result.structuredOutputError, /succeeded 2 times/);
  } finally {
    duplicate.cleanup();
  }

  const errored = setupRun();
  try {
    const spawned = runRelay(
      [...errored.args, ...genericFlags(errored.genericRoot)],
      {
        ...errored.env,
        PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", PLAN_PAYLOAD, { isError: true })]),
      },
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(errored.outDir);
    assert.equal(result.structuredOutput, null);
    assert.match(result.structuredOutputError, /returned an error result/);
  } finally {
    errored.cleanup();
  }

  const recovered = setupRun();
  try {
    const failed = toolEnd("submit_plan", PLAN_PAYLOAD, { isError: true });
    const ok = { ...toolEnd("submit_plan", { ...PLAN_PAYLOAD, title: "retry-ok" }), toolCallId: "call-2" };
    const spawned = runRelay(
      [...recovered.args, ...genericFlags(recovered.genericRoot)],
      { ...recovered.env, PI_STUB_EVENTS: JSON.stringify([failed, ok]) },
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const result = readResult(recovered.outDir);
    // An errored attempt corrected by a later successful submission is a
    // success: the error result was the model's feedback loop.
    assert.equal(result.structuredOutputError, null);
    assert.equal(result.structuredOutput.tool, "submit_plan");
    assert.equal(result.structuredOutput.payload.title, "retry-ok");
  } finally {
    recovered.cleanup();
  }
});

test("missing extension index writes a failed relay result after run-dir exists", () => {
  const ctx = setupRun();
  const badRoot = join(ctx.tmp, "empty-ext");
  mkdirSync(badRoot, { recursive: true });
  try {
    const spawned = runRelay([...ctx.args, ...genericFlags(badRoot)], ctx.env);
    assert.equal(spawned.status, 1, spawned.stderr);
    assert.equal(existsSync(join(ctx.outDir, "brief.txt")), true);
    const result = readResult(ctx.outDir);
    assert.equal(result.status, "failed");
    assert.match(result.error, /structured-output extension/);
    assert.equal(existsSync(ctx.dumpPath), false);
  } finally {
    ctx.cleanup();
  }
});

test("relative --structured-output-extension is a usage error", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay(
      [...ctx.args, "--structured-output-tool", "submit_plan", "--structured-output-extension", "relative-ext"],
      ctx.env,
    );
    assert.equal(spawned.status, 2, spawned.stderr);
    assert.match(spawned.stderr, /absolute path/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);
  } finally {
    ctx.cleanup();
  }
});

test("legacy review flags and generic structured-output flags are mutually exclusive", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay(
      [...ctx.args, "--review-output", "plan", ...genericFlags(ctx.genericRoot)],
      ctx.env,
    );
    assert.equal(spawned.status, 2, spawned.stderr);
    assert.match(spawned.stderr, /mutually exclusive|cannot be combined|not valid with/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);
  } finally {
    ctx.cleanup();
  }
});

test("tool and extension flags must be paired; recovery requires both plus --session", () => {
  const unpairedTool = setupRun();
  try {
    const spawned = runRelay(
      [...unpairedTool.args, "--structured-output-tool", "submit_plan"],
      unpairedTool.env,
    );
    assert.equal(spawned.status, 2, spawned.stderr);
    assert.equal(existsSync(join(unpairedTool.outDir, "result.json")), false);
  } finally {
    unpairedTool.cleanup();
  }

  const unpairedExt = setupRun();
  try {
    const spawned = runRelay(
      [...unpairedExt.args, "--structured-output-extension", unpairedExt.genericRoot],
      unpairedExt.env,
    );
    assert.equal(spawned.status, 2, spawned.stderr);
  } finally {
    unpairedExt.cleanup();
  }

  const recoveryNoSession = setupRun();
  try {
    const spawned = runRelay(
      [...recoveryNoSession.args, ...genericFlags(recoveryNoSession.genericRoot), "--structured-output-recovery"],
      recoveryNoSession.env,
    );
    assert.equal(spawned.status, 2, spawned.stderr);
    assert.match(spawned.stderr, /--structured-output-recovery requires --session/);
  } finally {
    recoveryNoSession.cleanup();
  }
});

test("legacy --review-output + --write remains rejected while generic write is allowed", () => {
  const legacy = setupRun({ args: ["--write", "--review-output", "plan"] });
  try {
    const spawned = runRelay(legacy.args, {
      ...legacy.env,
      PI_REVIEW_SUBMIT_ROOT: REVIEW_SUBMIT_ROOT,
    });
    assert.equal(spawned.status, 2, spawned.stderr);
    assert.match(spawned.stderr, /--review-output is not valid with --write/);
  } finally {
    legacy.cleanup();
  }
});
