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

function firstToolCallEntry(toolCall) {
  if (!toolCall || typeof toolCall !== "object" || Array.isArray(toolCall)) return null;
  const keys = Object.keys(toolCall);
  if (!keys.length) return null;
  const toolName = keys[0];
  return { toolName, entry: toolCall[toolName] };
}

function toolCallIdOf(event, entry) {
  if (typeof event.call_id === "string") return event.call_id;
  if (typeof event.toolCallId === "string") return event.toolCallId;
  if (typeof event.tool_call_id === "string") return event.tool_call_id;
  if (typeof event.id === "string") return event.id;
  if (entry && typeof entry === "object") {
    if (typeof entry.call_id === "string") return entry.call_id;
    if (typeof entry.id === "string") return entry.id;
    if (entry.args && typeof entry.args.toolCallId === "string") return entry.args.toolCallId;
  }
  return null;
}

function inferToolIsError(event, entry) {
  if (event && (event.is_error === true || event.isError === true)) return true;
  if (entry && typeof entry === "object") {
    if (entry.is_error === true || entry.isError === true) return true;
    const result = entry.result;
    if (result && typeof result === "object" && !Array.isArray(result)) {
      if (result.error != null || result.failure != null) return true;
    }
  }
  return false;
}

function isToolResultEvent(event) {
  // Tolerate the documented Cursor CLI shape (type "tool_call" + subtype
  // "completed" / nested .result) and a flat or nested type "tool_result".
  if (event.type === "tool_result") return true;
  if (event.tool_result && typeof event.tool_result === "object" && !Array.isArray(event.tool_result)) {
    return true;
  }
  if (!event.tool_call || typeof event.tool_call !== "object" || Array.isArray(event.tool_call)) {
    return false;
  }
  if (event.subtype === "completed") return true;
  const found = firstToolCallEntry(event.tool_call);
  return Boolean(found && found.entry && typeof found.entry === "object" && found.entry.result != null);
}

function isToolCallStartEvent(event) {
  // Relay scanner fact: event.tool_call.<name> (e.g. createPlanToolCall.args.plan).
  // A start is a tool_call object with a call key that is not a completion.
  if (isToolResultEvent(event)) return false;
  return Boolean(firstToolCallEntry(event.tool_call));
}

function projectToolFinished(event) {
  const nested = event.tool_result && typeof event.tool_result === "object" && !Array.isArray(event.tool_result)
    ? event.tool_result
    : null;
  const src = nested ?? event;
  const found = firstToolCallEntry(src.tool_call) ?? firstToolCallEntry(event.tool_call);
  const entry = found?.entry;
  const toolName = typeof src.toolName === "string"
    ? src.toolName
    : typeof src.tool_name === "string"
      ? src.tool_name
      : found?.toolName ?? null;
  return {
    type: "agent_tool_finished",
    data: {
      toolName,
      toolCallId: toolCallIdOf(src, entry) ?? toolCallIdOf(event, entry),
      isError: inferToolIsError(src, entry) || inferToolIsError(event, entry),
    },
  };
}

function projectToolStarted(event) {
  const found = firstToolCallEntry(event.tool_call);
  return {
    type: "agent_tool_started",
    data: {
      toolName: found?.toolName ?? null,
      toolCallId: toolCallIdOf(event, found?.entry),
    },
  };
}

function projectAssistant(event) {
  const message = event.message;
  if (!message || !Array.isArray(message.content)) return null;
  const texts = message.content
    .filter((part) => part && part.type === "text" && typeof part.text === "string")
    .map((part) => part.text);
  if (!texts.length) return null;
  return { type: "stage_message", data: { text: texts.join("\n\n") } };
}

// Cursor stream-json → coding-agent.event.v1. Session start is orthogonal (the
// first string session_id on any event) and is not in this table. Tool
// start/finish is classified by the heuristics above, not by type alone:
// type==="tool_call" with a completion marker projects through tool_result.
export const CURSOR_PROJECTION = Object.freeze({
  assistant: projectAssistant,
  tool_call: projectToolStarted,
  tool_result: projectToolFinished,
  result: () => ({ type: "agent_settled", data: {} }),
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

export function createCursorEventNormalizer(writer) {
  let buf = "";
  let sessionStarted = false;
  let settled = false;
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
    if (!event || typeof event !== "object" || Array.isArray(event)) {
      diagnostics.ignored += 1;
      return;
    }
    let emitted = false;
    if (!sessionStarted && typeof event.session_id === "string") {
      sessionStarted = true;
      writer.append("agent_session_started", { sessionId: event.session_id });
      emitted = true;
    }
    if (event.type === "result") {
      if (!settled) {
        settled = true;
        const projected = CURSOR_PROJECTION.result(event);
        writer.append(projected.type, projected.data);
      }
      return;
    }
    let projected = null;
    if (event.type === "assistant") projected = CURSOR_PROJECTION.assistant(event);
    else if (isToolResultEvent(event)) projected = CURSOR_PROJECTION.tool_result(event);
    else if (isToolCallStartEvent(event)) projected = CURSOR_PROJECTION.tool_call(event);
    if (projected) {
      writer.append(projected.type, projected.data);
      return;
    }
    if (!emitted) diagnostics.ignored += 1;
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
