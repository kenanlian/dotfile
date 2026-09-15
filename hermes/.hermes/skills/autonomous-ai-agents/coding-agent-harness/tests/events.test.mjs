import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createEventWriter, createPiEventNormalizer } from "../src/events.mjs";
import { buildRelayArgs, runPiAdapter } from "../src/pi-adapter.mjs";

const RELAY = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "pi-delegate", "scripts", "relay.mjs");
const STUB = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "pi-delegate", "tests", "fixtures", "stub-pi.mjs");
const EXT = join(dirname(fileURLToPath(import.meta.url)), "..", "extensions", "stage-submit");

function readEvents(path) {
  return readFileSync(path, "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

function fakeJob() {
  return {
    jobId: "job_1",
    stage: "plan",
    attempt: 1,
    workspace: { repoRoot: "/tmp" },
    agent: {
      adapter: "pi",
      profile: "planner",
      model: "zai-coding-cn/glm-5.3",
      thinking: "high",
      sessionId: null,
    },
    permissions: { mode: "read-only" },
    limits: { timeoutSeconds: null },
  };
}

test("event writer assigns monotonic seq and rejects unknown types", () => {
  const tmp = mkdtempSync(join(tmpdir(), "events-"));
  const path = join(tmp, "events.jsonl");
  try {
    let now = Date.parse("2026-09-14T00:00:00.000Z");
    const writer = createEventWriter({
      path,
      jobId: "job_1",
      stage: "plan",
      now: () => new Date(now).toISOString(),
    });
    writer.append("run_started", { x: 1 });
    writer.append("run_finished", { status: "completed" });
    const events = readEvents(path);
    assert.equal(events[0].seq, 1);
    assert.equal(events[1].seq, 2);
    assert.equal(events[0].schema, "coding-agent.event.v1");
    assert.throws(() => writer.append("not_a_type", {}));
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("normalizer projects allowed Pi events and ignores malformed or unknown lines", () => {
  const tmp = mkdtempSync(join(tmpdir(), "events-"));
  const path = join(tmp, "events.jsonl");
  try {
    const writer = createEventWriter({ path, jobId: "job_1", stage: "plan" });
    const normalizer = createPiEventNormalizer(writer);
    writer.append("run_started", {});
    normalizer.push('{"type":"session","id":"sess-1"}\n');
    normalizer.push('{"type":"tool_execution_start","toolName":"read","toolCallId":"c1"}\n');
    normalizer.push('{"type":"tool_execution_end","toolName":"submit_plan","toolCallId":"c2","isError":false}\n');
    normalizer.push("not-json\n");
    normalizer.push('{"type":"unknown_event"}\n');
    normalizer.push('{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"diag"}]}}\n');
    normalizer.push('{"type":"agent_settled"}\n');
    writer.append("run_finished", { status: "completed" });
    const events = readEvents(path);
    assert.deepEqual(events.map((item) => item.type), [
      "run_started",
      "agent_session_started",
      "agent_tool_started",
      "agent_tool_finished",
      "stage_message",
      "agent_settled",
      "run_finished",
    ]);
    assert.equal(events[0].seq, 1);
    assert.equal(events.at(-1).seq, 7);
    assert.equal(normalizer.diagnostics.ignored, 2);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("normalizer accepts partial NDJSON chunks", () => {
  const tmp = mkdtempSync(join(tmpdir(), "events-"));
  const path = join(tmp, "events.jsonl");
  try {
    const writer = createEventWriter({ path, jobId: "job_1", stage: "plan" });
    const normalizer = createPiEventNormalizer(writer);
    normalizer.push('{"type":"ses');
    normalizer.push('sion","id":"sess-chunk"}\n{"type":"agent_settled"}');
    normalizer.flush();
    const events = readEvents(path);
    assert.deepEqual(events.map((item) => item.type), ["agent_session_started", "agent_settled"]);
    assert.equal(events[0].data.sessionId, "sess-chunk");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("heartbeat uses injectable timer and does not depend on wall clock", () => {
  const tmp = mkdtempSync(join(tmpdir(), "events-"));
  const path = join(tmp, "events.jsonl");
  try {
    const timers = [];
    const writer = createEventWriter({
      path,
      jobId: "job_1",
      stage: "plan",
      heartbeatMs: 30_000,
      setIntervalFn: (fn, ms) => {
        const handle = { fn, ms };
        timers.push(handle);
        return handle;
      },
      clearIntervalFn: (handle) => {
        const index = timers.indexOf(handle);
        if (index >= 0) timers.splice(index, 1);
      },
    });
    writer.append("run_started", {});
    writer.startHeartbeat();
    assert.equal(timers.length, 1);
    assert.equal(timers[0].ms, 30_000);
    timers[0].fn();
    timers[0].fn();
    writer.stopHeartbeat();
    assert.equal(timers.length, 0);
    const types = readEvents(path).map((item) => item.type);
    assert.deepEqual(types, ["run_started", "heartbeat", "heartbeat"]);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("adapter argv uses generic structured-output flags and exact session", () => {
  const job = fakeJob();
  job.agent.sessionId = "sess-exact";
  const args = buildRelayArgs({
    briefPath: "/tmp/brief.txt",
    repoRoot: "/tmp/repo",
    outDir: "/tmp/adapter",
    job,
    extensionRoot: EXT,
  });
  assert.equal(args[args.indexOf("--session") + 1], "sess-exact");
  assert.equal(args[args.indexOf("--structured-output-tool") + 1], "submit_plan");
  assert.equal(args[args.indexOf("--structured-output-extension") + 1], EXT);
  assert.ok(args.includes("--read-only"));
});

test("runPiAdapter maps timeout/failed/unavailable and records adapter paths", async () => {
  const tmp = mkdtempSync(join(tmpdir(), "adapter-"));
  const workDir = join(tmp, "work");
  const outDir = join(tmp, "out");
  const dumpPath = join(tmp, "dump.json");
  mkdirSync(workDir);
  mkdirSync(outDir);
  const eventsPath = join(outDir, "events.jsonl");
  const writer = createEventWriter({ path: eventsPath, jobId: "job_1", stage: "plan" });
  const job = fakeJob();
  job.workspace.repoRoot = workDir;
  const env = {
    ...process.env,
    PI_BIN: STUB,
    PI_DELEGATE_AGENT_ROOT: join(tmp, "delegate"),
    PI_STUB_DUMP: dumpPath,
  };
  mkdirSync(join(tmp, "delegate"));
  writeFileSync(join(tmp, "delegate", "index.ts"), "export {};\n");
  try {
    writer.append("run_started", {});
    const missingDelegateHome = { ...env, PI_DELEGATE_AGENT_ROOT: join(tmp, "missing-delegate"), HOME: join(tmp, "empty-home") };
    mkdirSync(join(tmp, "empty-home"));
    const failed = await runPiAdapter({
      job,
      brief: "plan it",
      outDir,
      events: writer,
      relayPath: RELAY,
      extensionRoot: EXT,
      env: missingDelegateHome,
    });
    writer.append("run_finished", { status: failed.status, errorKind: failed.error?.kind });
    assert.equal(failed.status, "failed");
    assert.equal(failed.error.kind, "adapter_failed");
    assert.ok(failed.adapterRuns[0].result.endsWith("result.json"));
    const types = readEvents(eventsPath).map((item) => item.type);
    assert.equal(types[0], "run_started");
    assert.equal(types.at(-1), "run_finished");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("missing submit tool triggers exactly one recovery run", async () => {
  const tmp = mkdtempSync(join(tmpdir(), "adapter-"));
  const workDir = join(tmp, "work");
  const outDir = join(tmp, "out");
  mkdirSync(workDir);
  mkdirSync(outDir);
  mkdirSync(join(tmp, "delegate"));
  writeFileSync(join(tmp, "delegate", "index.ts"), "export {};\n");
  const eventsPath = join(outDir, "events.jsonl");
  const writer = createEventWriter({ path: eventsPath, jobId: "job_1", stage: "plan" });
  const job = fakeJob();
  job.workspace.repoRoot = workDir;
  const payload = {
    schema: "plan.v1",
    outcome: "blocked",
    title: "t",
    goal: "g",
    architecture: "a",
    techStack: [],
    requirements: [],
    contracts: [],
    workPackages: [],
    verification: [],
    risks: [],
    blockingIssues: ["x"],
  };
  const env = {
    ...process.env,
    PI_BIN: STUB,
    PI_DELEGATE_AGENT_ROOT: join(tmp, "delegate"),
    PI_STUB_SESSION: "sess-primary",
  };
  for (const key of Object.keys(env)) {
    if (key.startsWith("PI_STUB_") && key !== "PI_STUB_SESSION") delete env[key];
  }
  try {
    const result = await runPiAdapter({
      job,
      brief: "plan it",
      outDir,
      events: writer,
      relayPath: RELAY,
      extensionRoot: EXT,
      env: {
        ...env,
        PI_STUB_EVENTS: JSON.stringify([
          {
            type: "tool_execution_end",
            toolCallId: "call-1",
            toolName: "submit_plan",
            result: { details: payload },
            isError: false,
          },
        ]),
      },
    });
    assert.equal(result.recovered, false);
    assert.equal(result.structuredOutput.tool, "submit_plan");
    assert.equal(result.adapterRuns.length, 1);

    const recovered = await runPiAdapter({
      job,
      brief: "plan it",
      outDir: join(tmp, "out2"),
      events: writer,
      relayPath: RELAY,
      extensionRoot: EXT,
      env,
    });
    mkdirSync(join(tmp, "out2"), { recursive: true });
    assert.equal(recovered.recovered, true);
    assert.equal(recovered.adapterRuns.length, 2);
    assert.equal(recovered.adapterRuns[1].phase, "output-recovery");
    assert.equal(recovered.error.kind, "structured_output_missing");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});
