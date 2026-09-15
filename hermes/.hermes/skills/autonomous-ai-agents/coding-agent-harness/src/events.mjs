import { appendFileSync, writeFileSync } from "node:fs";
import { EVENT_SCHEMA_ID } from "./contracts.mjs";
import { canonicalJson } from "./util.mjs";

export const EVENT_TYPES = Object.freeze([
  "run_started",
  "agent_session_started",
  "heartbeat",
  "stage_message",
  "agent_tool_started",
  "agent_tool_finished",
  "artifact_written",
  "check_started",
  "check_finished",
  "agent_settled",
  "run_finished",
]);

const EVENT_TYPE_SET = new Set(EVENT_TYPES);

const PI_PROJECTION = Object.freeze({
  session: (event) => ({ type: "agent_session_started", data: { sessionId: event.id ?? null } }),
  tool_execution_start: (event) => ({
    type: "agent_tool_started",
    data: { toolName: event.toolName ?? null, toolCallId: event.toolCallId ?? null },
  }),
  tool_execution_end: (event) => ({
    type: "agent_tool_finished",
    data: {
      toolName: event.toolName ?? null,
      toolCallId: event.toolCallId ?? null,
      isError: Boolean(event.isError),
    },
  }),
  agent_settled: () => ({ type: "agent_settled", data: {} }),
  message_end: (event) => {
    const message = event.message;
    if (!message || message.role !== "assistant" || !Array.isArray(message.content)) return null;
    const texts = message.content
      .filter((part) => part && part.type === "text" && typeof part.text === "string")
      .map((part) => part.text);
    if (!texts.length) return null;
    return { type: "stage_message", data: { text: texts.join("\n\n") } };
  },
});

export function createEventWriter({
  path,
  jobId,
  stage,
  now = () => new Date().toISOString(),
  heartbeatMs = 30_000,
  setIntervalFn = setInterval,
  clearIntervalFn = clearInterval,
} = {}) {
  let seq = 0;
  let heartbeatTimer = null;
  writeFileSync(path, "");

  function append(type, data = {}) {
    if (!EVENT_TYPE_SET.has(type)) {
      throw new Error(`unknown event type ${type}`);
    }
    seq += 1;
    const event = {
      schema: EVENT_SCHEMA_ID,
      seq,
      timestamp: now(),
      jobId,
      stage,
      type,
      data,
    };
    appendFileSync(path, `${JSON.stringify(event)}\n`);
    return event;
  }

  return {
    get seq() { return seq; },
    path,
    append,
    startHeartbeat() {
      if (heartbeatTimer) return;
      heartbeatTimer = setIntervalFn(() => {
        append("heartbeat", {});
      }, heartbeatMs);
    },
    stopHeartbeat() {
      if (!heartbeatTimer) return;
      clearIntervalFn(heartbeatTimer);
      heartbeatTimer = null;
    },
  };
}

export function createPiEventNormalizer(writer) {
  let buf = "";
  const diagnostics = { ignored: 0 };
  function consumeLine(line) {
    if (!line) return;
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      diagnostics.ignored += 1;
      return;
    }
    if (!event || typeof event !== "object" || typeof event.type !== "string") {
      diagnostics.ignored += 1;
      return;
    }
    const project = PI_PROJECTION[event.type];
    if (!project) {
      diagnostics.ignored += 1;
      return;
    }
    const projected = project(event);
    if (!projected) {
      diagnostics.ignored += 1;
      return;
    }
    writer.append(projected.type, projected.data);
  }
  return {
    diagnostics,
    push(chunk) {
      buf += chunk;
      let index;
      while ((index = buf.indexOf("\n")) !== -1) {
        const line = buf.slice(0, index).trim();
        buf = buf.slice(index + 1);
        consumeLine(line);
      }
    },
    flush() {
      const line = buf.trim();
      buf = "";
      consumeLine(line);
    },
  };
}

export { canonicalJson };
