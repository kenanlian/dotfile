import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createCursorEventNormalizer, createEventWriter } from "../src/events.mjs";

function readEvents(path) {
  return readFileSync(path, "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

const SYSTEM_INIT = {
  type: "system",
  subtype: "init",
  session_id: "sess-cursor-1",
  model: "Claude Opus 5 1M Thinking",
  permissionMode: "plan",
};

const ASSISTANT = {
  type: "assistant",
  session_id: "sess-cursor-1",
  message: {
    role: "assistant",
    content: [
      { type: "text", text: "I'll draft a plan." },
      { type: "text", text: "Next I'll call a tool." },
    ],
  },
};

const TOOL_STARTED = {
  type: "tool_call",
  subtype: "started",
  call_id: "call-plan-1",
  session_id: "sess-cursor-1",
  tool_call: {
    createPlanToolCall: {
      args: { plan: "# Plan\nDo the work." },
    },
  },
};

const TOOL_COMPLETED = {
  type: "tool_call",
  subtype: "completed",
  call_id: "call-plan-1",
  session_id: "sess-cursor-1",
  tool_call: {
    createPlanToolCall: {
      args: { plan: "# Plan\nDo the work." },
      result: { success: {} },
    },
  },
};

const TOOL_RESULT_FLAT = {
  type: "tool_result",
  toolName: "readToolCall",
  call_id: "call-read-1",
  is_error: true,
  session_id: "sess-cursor-1",
};

const TOOL_RESULT_NESTED = {
  type: "user",
  session_id: "sess-cursor-1",
  tool_result: {
    tool_name: "grepToolCall",
    id: "call-grep-1",
    isError: false,
  },
};

const RESULT = {
  type: "result",
  subtype: "success",
  is_error: false,
  result: "done",
  session_id: "sess-cursor-1",
  usage: { inputTokens: 10, outputTokens: 4 },
};

test("normalizer projects Cursor relay-scanner stream-json shapes", () => {
  const tmp = mkdtempSync(join(tmpdir(), "cursor-events-"));
  const path = join(tmp, "events.jsonl");
  try {
    const writer = createEventWriter({ path, jobId: "job_1", stage: "plan" });
    const normalizer = createCursorEventNormalizer(writer);
    writer.append("run_started", {});
    normalizer.push(`${JSON.stringify(SYSTEM_INIT)}\n`);
    normalizer.push(`${JSON.stringify(ASSISTANT)}\n`);
    normalizer.push(`${JSON.stringify(TOOL_STARTED)}\n`);
    normalizer.push(`${JSON.stringify(TOOL_COMPLETED)}\n`);
    normalizer.push(`${JSON.stringify(RESULT)}\n`);
    writer.append("run_finished", { status: "completed" });
    const events = readEvents(path);
    assert.deepEqual(events.map((item) => item.type), [
      "run_started",
      "agent_session_started",
      "stage_message",
      "agent_tool_started",
      "agent_tool_finished",
      "agent_settled",
      "run_finished",
    ]);
    assert.equal(events[1].data.sessionId, "sess-cursor-1");
    assert.equal(events[2].data.text, "I'll draft a plan.\n\nNext I'll call a tool.");
    assert.equal(events[3].data.toolName, "createPlanToolCall");
    assert.equal(events[3].data.toolCallId, "call-plan-1");
    assert.equal(events[4].data.toolName, "createPlanToolCall");
    assert.equal(events[4].data.toolCallId, "call-plan-1");
    assert.equal(events[4].data.isError, false);
    assert.deepEqual(events[5].data, {});
    assert.equal(normalizer.diagnostics.ignored, 0);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("normalizer accepts partial NDJSON chunks", () => {
  const tmp = mkdtempSync(join(tmpdir(), "cursor-events-"));
  const path = join(tmp, "events.jsonl");
  try {
    const writer = createEventWriter({ path, jobId: "job_1", stage: "plan" });
    const normalizer = createCursorEventNormalizer(writer);
    const first = JSON.stringify(SYSTEM_INIT);
    const second = JSON.stringify(RESULT);
    normalizer.push(first.slice(0, 18));
    normalizer.push(`${first.slice(18)}\n${second}`);
    normalizer.flush();
    const events = readEvents(path);
    assert.deepEqual(events.map((item) => item.type), ["agent_session_started", "agent_settled"]);
    assert.equal(events[0].data.sessionId, "sess-cursor-1");
    assert.equal(normalizer.diagnostics.ignored, 0);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("unknown and malformed lines increment diagnostics.ignored", () => {
  const tmp = mkdtempSync(join(tmpdir(), "cursor-events-"));
  const path = join(tmp, "events.jsonl");
  try {
    const writer = createEventWriter({ path, jobId: "job_1", stage: "plan" });
    const normalizer = createCursorEventNormalizer(writer);
    normalizer.push(`${JSON.stringify(SYSTEM_INIT)}\n`);
    normalizer.push("not-json\n");
    normalizer.push('{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hi"}]},"session_id":"sess-cursor-1"}\n');
    normalizer.push('{"type":"unknown_event"}\n');
    normalizer.push("[]\n");
    const events = readEvents(path);
    assert.deepEqual(events.map((item) => item.type), ["agent_session_started"]);
    assert.equal(normalizer.diagnostics.ignored, 4);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("session is emitted once even if session_id repeats", () => {
  const tmp = mkdtempSync(join(tmpdir(), "cursor-events-"));
  const path = join(tmp, "events.jsonl");
  try {
    const writer = createEventWriter({ path, jobId: "job_1", stage: "plan" });
    const normalizer = createCursorEventNormalizer(writer);
    normalizer.push(`${JSON.stringify(SYSTEM_INIT)}\n`);
    normalizer.push(`${JSON.stringify({ ...SYSTEM_INIT, model: "other" })}\n`);
    normalizer.push(`${JSON.stringify(ASSISTANT)}\n`);
    const events = readEvents(path);
    assert.deepEqual(events.map((item) => item.type), ["agent_session_started", "stage_message"]);
    assert.equal(events.filter((item) => item.type === "agent_session_started").length, 1);
    assert.equal(normalizer.diagnostics.ignored, 1);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("result projects agent_settled exactly once", () => {
  const tmp = mkdtempSync(join(tmpdir(), "cursor-events-"));
  const path = join(tmp, "events.jsonl");
  try {
    const writer = createEventWriter({ path, jobId: "job_1", stage: "plan" });
    const normalizer = createCursorEventNormalizer(writer);
    normalizer.push(`${JSON.stringify(RESULT)}\n`);
    normalizer.push(`${JSON.stringify({ ...RESULT, usage: { inputTokens: 99 } })}\n`);
    const events = readEvents(path);
    assert.deepEqual(events.map((item) => item.type), ["agent_session_started", "agent_settled"]);
    assert.equal(events.filter((item) => item.type === "agent_settled").length, 1);
    assert.equal(normalizer.diagnostics.ignored, 0);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("tool-result events tolerate type tool_result and nested shapes", () => {
  const tmp = mkdtempSync(join(tmpdir(), "cursor-events-"));
  const path = join(tmp, "events.jsonl");
  try {
    const writer = createEventWriter({ path, jobId: "job_1", stage: "plan" });
    const normalizer = createCursorEventNormalizer(writer);
    normalizer.push(`${JSON.stringify(TOOL_RESULT_FLAT)}\n`);
    normalizer.push(`${JSON.stringify(TOOL_RESULT_NESTED)}\n`);
    const events = readEvents(path);
    assert.equal(events[0].type, "agent_session_started");
    assert.equal(events[1].type, "agent_tool_finished");
    assert.equal(events[1].data.toolName, "readToolCall");
    assert.equal(events[1].data.toolCallId, "call-read-1");
    assert.equal(events[1].data.isError, true);
    assert.equal(events[2].type, "agent_tool_finished");
    assert.equal(events[2].data.toolName, "grepToolCall");
    assert.equal(events[2].data.toolCallId, "call-grep-1");
    assert.equal(events[2].data.isError, false);
    assert.equal(normalizer.diagnostics.ignored, 0);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});
