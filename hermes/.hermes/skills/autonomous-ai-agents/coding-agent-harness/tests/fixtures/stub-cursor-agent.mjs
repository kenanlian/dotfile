#!/usr/bin/env node
/**
 * Fake Cursor `agent` binary for harness integration tests.
 *
 * Driven through the real cursor-delegate relay via CURSOR_AGENT_BIN.
 * Locates the run-scoped submit-bridge config from `--plugin-dir` and
 * records receipts through the real server.mjs helpers.
 */
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import {
  handleSubmitCall,
  loadConfig,
} from "../../extensions/cursor-stage-submit/server.mjs";

const DEFAULT_SESSION = "cursor-stub-session-1";
const DEFAULT_MODEL = "Claude Opus 5 1M Thinking";
const DEFAULT_USAGE = Object.freeze({ inputTokens: 12, outputTokens: 34 });

const PAYLOADS = Object.freeze({
  submit_plan: Object.freeze({
    schema: "plan.v1",
    outcome: "completed",
    title: "Greet helper",
    goal: "Add a greet function",
    architecture: "Single module plus unit test",
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
      steps: ["Write greet", "Write test"],
      verificationIds: ["V1"],
    }],
    verification: [{
      id: "V1",
      kind: "focused",
      cwd: ".",
      argv: ["node", "--test", "test/greet.test.mjs"],
      expected: "tests pass",
      contractIds: ["C1"],
    }],
    risks: [{ risk: "none material", mitigation: "keep scope tiny" }],
    blockingIssues: [],
  }),
  submit_plan_review: Object.freeze({
    schema: "plan-review.v1",
    verdict: "approved",
    summary: "ok",
    findings: [],
  }),
  submit_implementation: Object.freeze({
    schema: "implementation.v1",
    outcome: "completed",
    summary: "done",
    completedWorkPackages: ["WP-01"],
    deviations: [],
    residualRisks: [],
    blockingIssues: [],
  }),
  submit_execute_review: Object.freeze({
    schema: "execute-review.v1",
    verdict: "approved",
    summary: "ok",
    findings: [],
    acceptanceCoverage: ["C1: greet test"],
  }),
  submit_direct_implementation: Object.freeze({
    schema: "direct-implementation.v1",
    outcome: "completed",
    summary: "done",
    residualRisks: [],
    blockingIssues: [],
  }),
});

function flagValue(argv, flag) {
  const index = argv.indexOf(flag);
  if (index === -1 || index + 1 >= argv.length) return null;
  const value = argv[index + 1];
  if (typeof value !== "string" || value.startsWith("--")) return null;
  return value;
}

function pluginDirFromArgv(argv) {
  return flagValue(argv, "--plugin-dir");
}

function configPathForPluginDir(pluginDir) {
  const direct = join(pluginDir, "config.json");
  if (existsSync(direct)) return direct;
  return join(pluginDir, "..", "submit-bridge", "config.json");
}

function emit(event) {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

function dumpRecord(record) {
  const dumpPath = process.env.CURSOR_STUB_DUMP;
  if (!dumpPath) return;
  mkdirSync(dirname(dumpPath), { recursive: true });
  let existing = [];
  if (existsSync(dumpPath)) {
    try {
      const parsed = JSON.parse(readFileSync(dumpPath, "utf8"));
      existing = Array.isArray(parsed) ? parsed : [parsed];
    } catch {
      existing = [];
    }
  }
  existing.push(record);
  writeFileSync(dumpPath, `${JSON.stringify(existing, null, 2)}\n`);
}

function sleepMs(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return;
  const ia = new Int32Array(new SharedArrayBuffer(4));
  Atomics.wait(ia, 0, 0, ms);
}

async function drainStdin() {
  if (!process.stdin.readable) return;
  for await (const _chunk of process.stdin) {
    void _chunk;
  }
}

function defaultPayload(expectedTool) {
  const payload = PAYLOADS[expectedTool];
  if (!payload) return { schema: "unknown.v1" };
  return JSON.parse(JSON.stringify(payload));
}

function claimedBinding(config, { badBinding }) {
  return {
    jobId: config.jobId,
    jobSha256: config.jobSha256,
    stage: config.stage,
    expectedTool: config.expectedTool,
    runNonce: badBinding ? "cursor-stub-wrong-nonce" : config.runNonce,
  };
}

function submitPayload(config, { badPayload }) {
  if (process.env.CURSOR_STUB_PAYLOAD) {
    return JSON.parse(process.env.CURSOR_STUB_PAYLOAD);
  }
  if (badPayload) return { schema: "nope" };
  return defaultPayload(config.expectedTool);
}

function shouldSuppressSubmit(argv) {
  if (process.env.CURSOR_STUB_SUPPRESS_SUBMIT === "1") return true;
  const primaryOnly = process.env.CURSOR_STUB_SUPPRESS_SUBMIT_PRIMARY === "1";
  if (primaryOnly && !argv.includes("--resume")) return true;
  return false;
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("--version")) {
    process.stdout.write(`${process.env.CURSOR_STUB_VERSION || "2026.09.15-stub"}\n`);
    process.exit(0);
  }

  const pluginDir = pluginDirFromArgv(argv);
  dumpRecord({
    argv,
    cwd: process.cwd(),
    pluginDir,
    resume: flagValue(argv, "--resume"),
  });

  await drainStdin();

  if (process.env.CURSOR_STUB_SLEEP_MS) {
    sleepMs(Number(process.env.CURSOR_STUB_SLEEP_MS));
  }

  if (process.env.CURSOR_STUB_WRITE_RELPATH) {
    const target = join(process.cwd(), process.env.CURSOR_STUB_WRITE_RELPATH);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, process.env.CURSOR_STUB_WRITE_CONTENTS ?? "stub-write\n");
  }

  const resumeId = flagValue(argv, "--resume");
  let sessionId = process.env.CURSOR_STUB_SESSION
    || resumeId
    || DEFAULT_SESSION;
  if (process.env.CURSOR_STUB_NO_SESSION === "1") sessionId = null;
  if (process.env.CURSOR_STUB_SESSION_MISMATCH) {
    sessionId = process.env.CURSOR_STUB_SESSION_MISMATCH;
  }

  const model = process.env.CURSOR_STUB_RESOLVED_MODEL || DEFAULT_MODEL;
  const permissionMode = argv.includes("--force") ? "edit" : "plan";
  const usage = process.env.CURSOR_STUB_USAGE
    ? JSON.parse(process.env.CURSOR_STUB_USAGE)
    : { ...DEFAULT_USAGE };

  if (sessionId) {
    emit({
      type: "system",
      subtype: "init",
      session_id: sessionId,
      model,
      permissionMode,
    });
  } else {
    emit({
      type: "system",
      subtype: "init",
      model,
      permissionMode,
    });
  }

  emit({
    type: "assistant",
    ...(sessionId ? { session_id: sessionId } : {}),
    message: {
      role: "assistant",
      content: [{ type: "text", text: process.env.CURSOR_STUB_ASSISTANT || "stub cursor run" }],
    },
  });

  let submitted = false;
  if (pluginDir && !shouldSuppressSubmit(argv)) {
    const configPath = configPathForPluginDir(pluginDir);
    const config = loadConfig(configPath);
    const badBinding = process.env.CURSOR_STUB_BAD_BINDING === "1";
    const badPayload = process.env.CURSOR_STUB_BAD_PAYLOAD === "1";
    const claimed = claimedBinding(config, { badBinding });
    const payload = submitPayload(config, { badPayload });
    const args = { ...claimed, payload };
    const echo = process.env.CURSOR_STUB_ECHO_TOOL !== "0";
    if (echo) {
      emit({
        type: "tool_call",
        ...(sessionId ? { session_id: sessionId } : {}),
        tool_call: {
          [config.expectedTool]: {
            id: "call-submit-1",
            args,
          },
        },
      });
    }
    handleSubmitCall(config, args, config.expectedTool);
    submitted = true;
    if (process.env.CURSOR_STUB_DOUBLE_SUBMIT === "1") {
      handleSubmitCall(config, args, config.expectedTool);
    }
    if (echo) {
      emit({
        type: "tool_call",
        subtype: "completed",
        ...(sessionId ? { session_id: sessionId } : {}),
        tool_call: {
          [config.expectedTool]: {
            id: "call-submit-1",
            args,
            result: { success: {} },
          },
        },
      });
    }
  }

  emit({
    type: "result",
    ...(sessionId ? { session_id: sessionId } : {}),
    result: submitted ? "submitted" : "done without submit",
    is_error: false,
    usage,
  });

  if (process.env.CURSOR_STUB_EXIT) {
    process.exit(Number(process.env.CURSOR_STUB_EXIT));
  }
  process.exit(0);
}

void main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exit(1);
});
