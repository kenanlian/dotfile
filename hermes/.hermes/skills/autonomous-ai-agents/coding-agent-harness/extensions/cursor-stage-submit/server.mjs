#!/usr/bin/env node
/**
 * Run-scoped Cursor Stage Submit Bridge — zero-dependency stdio MCP server.
 *
 * Loaded via Cursor `--plugin-dir` (Agent Plugin layout: plugin.json + mcp.json).
 * Registers exactly one submit tool from the generated config and writes
 * O_EXCL attempt receipts. Structural checks only; host validatePayload is
 * authoritative.
 */

import {
  closeSync,
  constants as fsConstants,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  CONTRACT_FIELD_KEYS,
  DEVIATION_FIELD_KEYS,
  DIRECT_IMPLEMENTATION_FIELD_KEYS,
  DIRECT_IMPLEMENTATION_SCHEMA_ID,
  EXECUTE_REVIEW_FIELD_KEYS,
  EXECUTE_REVIEW_FINDING_FIELD_KEYS,
  EXECUTE_REVIEW_SCHEMA_ID,
  FILE_CHANGE_FIELD_KEYS,
  IMPLEMENTATION_FIELD_KEYS,
  IMPLEMENTATION_SCHEMA_ID,
  PLAN_FIELD_KEYS,
  PLAN_REVIEW_FIELD_KEYS,
  PLAN_REVIEW_FINDING_FIELD_KEYS,
  PLAN_REVIEW_SCHEMA_ID,
  PLAN_SCHEMA_ID,
  PLAN_VERIFICATION_FIELD_KEYS,
  REQUIREMENT_FIELD_KEYS,
  RISK_FIELD_KEYS,
  SUBMIT_DIRECT_IMPLEMENTATION,
  SUBMIT_EXECUTE_REVIEW,
  SUBMIT_IMPLEMENTATION,
  SUBMIT_PLAN,
  SUBMIT_PLAN_REVIEW,
  WORK_PACKAGE_FIELD_KEYS,
} from "../stage-submit/keys.mjs";

export const ATTEMPT_SCHEMA = "coding-agent.submit-attempt.v1";
export const CONFIG_SCHEMA = "coding-agent.submit-bridge.v1";
export const SEQ_PAD = 6;
export const BINDING_KEYS = Object.freeze([
  "jobId", "jobSha256", "stage", "expectedTool", "runNonce",
]);

export const SUBMIT_TOOLS = Object.freeze({
  plan: SUBMIT_PLAN,
  plan_review: SUBMIT_PLAN_REVIEW,
  implement: SUBMIT_IMPLEMENTATION,
  execute_review: SUBMIT_EXECUTE_REVIEW,
  direct_implement: SUBMIT_DIRECT_IMPLEMENTATION,
});

export const SUBMIT_TOOL_NAMES = Object.freeze(Object.values(SUBMIT_TOOLS));

const OUTCOMES = Object.freeze(["completed", "blocked"]);
const VERDICTS = Object.freeze(["approved", "request_changes", "blocked"]);

export const TOOL_FIELD_KEYS = Object.freeze({
  [SUBMIT_PLAN]: PLAN_FIELD_KEYS,
  [SUBMIT_PLAN_REVIEW]: PLAN_REVIEW_FIELD_KEYS,
  [SUBMIT_IMPLEMENTATION]: IMPLEMENTATION_FIELD_KEYS,
  [SUBMIT_EXECUTE_REVIEW]: EXECUTE_REVIEW_FIELD_KEYS,
  [SUBMIT_DIRECT_IMPLEMENTATION]: DIRECT_IMPLEMENTATION_FIELD_KEYS,
});

export const TOOL_SCHEMA_IDS = Object.freeze({
  [SUBMIT_PLAN]: PLAN_SCHEMA_ID,
  [SUBMIT_PLAN_REVIEW]: PLAN_REVIEW_SCHEMA_ID,
  [SUBMIT_IMPLEMENTATION]: IMPLEMENTATION_SCHEMA_ID,
  [SUBMIT_EXECUTE_REVIEW]: EXECUTE_REVIEW_SCHEMA_ID,
  [SUBMIT_DIRECT_IMPLEMENTATION]: DIRECT_IMPLEMENTATION_SCHEMA_ID,
});

export const TOOL_ENUM_FIELDS = Object.freeze({
  [SUBMIT_PLAN]: Object.freeze({ outcome: OUTCOMES }),
  [SUBMIT_PLAN_REVIEW]: Object.freeze({ verdict: VERDICTS }),
  [SUBMIT_IMPLEMENTATION]: Object.freeze({ outcome: OUTCOMES }),
  [SUBMIT_EXECUTE_REVIEW]: Object.freeze({ verdict: VERDICTS }),
  [SUBMIT_DIRECT_IMPLEMENTATION]: Object.freeze({ outcome: OUTCOMES }),
});

const NESTED_OBJECT_KEYS = Object.freeze({
  [SUBMIT_PLAN]: Object.freeze([
    Object.freeze({ field: "requirements", keys: REQUIREMENT_FIELD_KEYS }),
    Object.freeze({ field: "contracts", keys: CONTRACT_FIELD_KEYS }),
    Object.freeze({ field: "workPackages", keys: WORK_PACKAGE_FIELD_KEYS, nested: Object.freeze([
      Object.freeze({ field: "fileChanges", keys: FILE_CHANGE_FIELD_KEYS }),
    ]) }),
    Object.freeze({ field: "verification", keys: PLAN_VERIFICATION_FIELD_KEYS }),
    Object.freeze({ field: "risks", keys: RISK_FIELD_KEYS }),
  ]),
  [SUBMIT_PLAN_REVIEW]: Object.freeze([
    Object.freeze({ field: "findings", keys: PLAN_REVIEW_FINDING_FIELD_KEYS }),
  ]),
  [SUBMIT_IMPLEMENTATION]: Object.freeze([
    Object.freeze({ field: "deviations", keys: DEVIATION_FIELD_KEYS }),
  ]),
  [SUBMIT_EXECUTE_REVIEW]: Object.freeze([
    Object.freeze({ field: "findings", keys: EXECUTE_REVIEW_FINDING_FIELD_KEYS }),
  ]),
  [SUBMIT_DIRECT_IMPLEMENTATION]: Object.freeze([]),
});

export const TOOL_TEXT = Object.freeze({
  [SUBMIT_PLAN]: Object.freeze({
    description: "Submit the completed plan payload and end the planner run. Call this once as the final action. contracts and workPackages are object arrays, not id strings.",
    shapeHint: "plan.v1 fields: schema, outcome, title, goal, architecture, techStack[], requirements[{id,text}], contracts[{id,requirementIds,text}], workPackages[{id,title,objective,dependsOn,contractIds,fileChanges[{action,path}],steps,verificationIds}], verification[{id,kind,cwd,argv,expected,contractIds}], risks[{risk,mitigation}], blockingIssues[].",
  }),
  [SUBMIT_PLAN_REVIEW]: Object.freeze({
    description: "Submit the completed plan-review payload and end the reviewer run. Call this once as the final action. findings are objects, not strings.",
    shapeHint: "plan-review.v1 fields: schema, verdict, summary, findings[{severity,location,problem,requiredChange}].",
  }),
  [SUBMIT_IMPLEMENTATION]: Object.freeze({
    description: "Submit the completed implementation payload and end the implementer run. Call this once as the final action.",
    shapeHint: "implementation.v1 fields: schema, outcome, summary, completedWorkPackages[], deviations[{workPackageId,summary}], residualRisks[], blockingIssues[].",
  }),
  [SUBMIT_EXECUTE_REVIEW]: Object.freeze({
    description: "Submit the completed execute-review payload and end the reviewer run. Call this once as the final action. findings are objects, not strings.",
    shapeHint: "execute-review.v1 fields: schema, verdict, summary, findings[{severity,file,line,problem,requiredChange}], acceptanceCoverage[].",
  }),
  [SUBMIT_DIRECT_IMPLEMENTATION]: Object.freeze({
    description: "Submit the completed direct-implementation payload and end the implementer run. Call this once as the final action.",
    shapeHint: "direct-implementation.v1 fields: schema, outcome, summary, residualRisks[], blockingIssues[].",
  }),
});

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function padSeq(seq) {
  return String(seq).padStart(SEQ_PAD, "0");
}

function parseSeqFromName(name) {
  const match = /^attempt-(\d+)\.json$/.exec(name);
  if (!match) return null;
  return Number(match[1]);
}

function exclusiveWriteFile(path, contents) {
  mkdirSync(dirname(path), { recursive: true });
  const fd = openSync(path, fsConstants.O_CREAT | fsConstants.O_EXCL | fsConstants.O_WRONLY, 0o644);
  try {
    writeFileSync(fd, contents);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}

export function listAttempts(submitDir) {
  if (!existsSync(submitDir)) return [];
  const names = readdirSync(submitDir);
  const attempts = [];
  for (const name of names) {
    const seq = parseSeqFromName(name);
    if (seq === null) continue;
    const path = join(submitDir, name);
    let record;
    try {
      record = JSON.parse(readFileSync(path, "utf8"));
    } catch {
      continue;
    }
    attempts.push({ path, seq, record });
  }
  attempts.sort((a, b) => a.seq - b.seq);
  return attempts;
}

function nextSeq(submitDir) {
  const existing = listAttempts(submitDir);
  if (existing.length === 0) return 1;
  return existing[existing.length - 1].seq + 1;
}

export function writeAttempt(submitDir, attempt) {
  mkdirSync(submitDir, { recursive: true });
  const seqNumber = attempt.seq == null ? nextSeq(submitDir) : Number(attempt.seq);
  if (!Number.isInteger(seqNumber) || seqNumber < 1) {
    const error = new Error(`invalid seq: ${attempt.seq}`);
    error.code = "EINVAL";
    throw error;
  }
  const seq = padSeq(seqNumber);
  const record = {
    schema: ATTEMPT_SCHEMA,
    ...attempt,
    schema: ATTEMPT_SCHEMA,
    seq,
  };
  const path = join(submitDir, `attempt-${seq}.json`);
  exclusiveWriteFile(path, `${JSON.stringify(record, null, 2)}\n`);
  return { path, seq: seqNumber, record };
}

export function checkBinding(config, claimed) {
  if (!isPlainObject(config)) {
    return { ok: false, reason: "binding mismatch: config is not an object" };
  }
  if (!isPlainObject(claimed)) {
    return { ok: false, reason: "binding mismatch: claimed binding is not an object" };
  }
  for (const key of BINDING_KEYS) {
    if (claimed[key] !== config[key]) {
      return { ok: false, reason: `binding mismatch: ${key}` };
    }
  }
  return { ok: true };
}

function exactKeys(value, keys, path) {
  if (!isPlainObject(value)) return `payload shape: ${path || "/"} expected object`;
  const actual = Object.keys(value);
  for (const key of actual) {
    if (!keys.includes(key)) {
      return `payload shape: unknown field ${path}/${key}`;
    }
  }
  if (actual.length !== keys.length) {
    return `payload shape: ${path || "/"} expected exact keys [${keys.join(", ")}]`;
  }
  return null;
}

function checkNestedObjects(items, keys, path, nested) {
  if (!Array.isArray(items)) return `payload shape: ${path} expected array`;
  for (let i = 0; i < items.length; i += 1) {
    const itemPath = `${path}/${i}`;
    const err = exactKeys(items[i], keys, itemPath);
    if (err) return err;
    if (nested) {
      for (const child of nested) {
        const nestedErr = checkNestedObjects(items[i][child.field], child.keys, `${itemPath}/${child.field}`, child.nested);
        if (nestedErr) return nestedErr;
      }
    }
  }
  return null;
}

export function checkPayloadShape(expectedTool, payload) {
  const fieldKeys = TOOL_FIELD_KEYS[expectedTool];
  if (!fieldKeys) {
    return { ok: false, reason: `payload shape: unknown tool ${expectedTool}` };
  }
  const top = exactKeys(payload, fieldKeys, "");
  if (top) return { ok: false, reason: top };

  const schemaId = TOOL_SCHEMA_IDS[expectedTool];
  if (payload.schema !== schemaId) {
    return { ok: false, reason: `payload shape: schema must be ${schemaId}` };
  }

  const enums = TOOL_ENUM_FIELDS[expectedTool] || {};
  for (const [field, allowed] of Object.entries(enums)) {
    if (!allowed.includes(payload[field])) {
      return { ok: false, reason: `payload shape: ${field} must be ${allowed.join("|")}` };
    }
  }

  const nested = NESTED_OBJECT_KEYS[expectedTool] || [];
  for (const spec of nested) {
    const err = checkNestedObjects(payload[spec.field], spec.keys, `/${spec.field}`, spec.nested);
    if (err) return { ok: false, reason: err };
  }

  return { ok: true };
}

function claimedBinding(args) {
  const claimed = {};
  for (const key of BINDING_KEYS) claimed[key] = args?.[key];
  return claimed;
}

export function handleSubmitCall(config, args, toolName) {
  const claimed = claimedBinding(args);
  const tool = toolName || args?.expectedTool || config.expectedTool;
  const payload = args?.payload;
  const receivedAt = new Date().toISOString();

  function record(outcome, reason, bindingMatches) {
    return writeAttempt(config.submitDir, {
      receivedAt,
      tool,
      binding: claimed,
      bindingMatches,
      payload: payload === undefined ? null : payload,
      outcome,
      ...(reason ? { reason } : {}),
    });
  }

  if (tool !== config.expectedTool) {
    const written = record("rejected", `binding mismatch: tool ${tool}`, false);
    return { ok: false, attempt: written, reason: written.record.reason };
  }

  const binding = checkBinding(config, claimed);
  if (!binding.ok) {
    const written = record("rejected", binding.reason, false);
    return { ok: false, attempt: written, reason: binding.reason };
  }

  const shape = checkPayloadShape(config.expectedTool, payload);
  if (!shape.ok) {
    const written = record("rejected", shape.reason, true);
    return { ok: false, attempt: written, reason: shape.reason };
  }

  const written = record("accepted", undefined, true);
  return { ok: true, attempt: written };
}

export function loadConfig(configPath) {
  const resolved = resolve(configPath);
  const config = JSON.parse(readFileSync(resolved, "utf8"));
  if (!isPlainObject(config)) throw new Error(`invalid config: ${resolved}`);
  if (!SUBMIT_TOOL_NAMES.includes(config.expectedTool)) {
    throw new Error(`unknown submit tool: ${config.expectedTool}`);
  }
  for (const key of [...BINDING_KEYS, "phase", "submitDir"]) {
    if (typeof config[key] !== "string" || config[key].length === 0) {
      throw new Error(`config missing ${key}`);
    }
  }
  return config;
}

function parseConfigPath(argv, env = process.env) {
  const index = argv.indexOf("--config");
  if (index >= 0) {
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error("missing --config path");
    return value;
  }
  if (typeof env.CURSOR_SUBMIT_CONFIG === "string" && env.CURSOR_SUBMIT_CONFIG.length > 0) {
    return env.CURSOR_SUBMIT_CONFIG;
  }
  throw new Error("missing --config or CURSOR_SUBMIT_CONFIG");
}

function toolDefinition(config) {
  const text = TOOL_TEXT[config.expectedTool];
  return {
    name: config.expectedTool,
    description: `${text.description} ${text.shapeHint}`,
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        jobId: { type: "string", description: "Harness job id" },
        jobSha256: { type: "string", description: "Harness job SHA-256" },
        stage: { type: "string", description: "Harness stage" },
        expectedTool: { type: "string", description: "Expected submit tool name" },
        runNonce: { type: "string", description: "Per-phase run nonce" },
        payload: { type: "object", description: "Stage payload object" },
      },
      required: ["jobId", "jobSha256", "stage", "expectedTool", "runNonce", "payload"],
    },
  };
}

function jsonRpcResult(id, result) {
  return { jsonrpc: "2.0", id, result };
}

function jsonRpcError(id, code, message, data) {
  const error = { code, message };
  if (data !== undefined) error.data = data;
  return { jsonrpc: "2.0", id, error };
}

export function isSmokeSuppressTool(env = process.env, submitDir = null) {
  // Smoke-only suppression (WP-09 scenario C), fails closed: honored only when
  // the env knob is explicitly "1" or the run-scoped marker file exists inside
  // this bridge's submit dir. The Cursor CLI sanitizes the parent environment
  // of MCP server children (verified live 2026-09-18: CURSOR_* vars do not
  // propagate), so the marker file is the transport the real-CLI smoke uses.
  if (env.CURSOR_SMOKE_SUPPRESS_TOOL === "1") return true;
  if (typeof submitDir === "string" && existsSync(join(submitDir, SMOKE_SUPPRESS_MARKER))) return true;
  return false;
}

export const SMOKE_SUPPRESS_MARKER = "SMOKE_SUPPRESS";

export function handleJsonRpc(config, message, env = process.env) {
  if (!isPlainObject(message) || message.jsonrpc !== "2.0") {
    return jsonRpcError(message?.id ?? null, -32600, "Invalid Request");
  }
  const { id, method, params } = message;
  if (method === "notifications/initialized" || method === "notifications/cancelled") {
    return null;
  }
  if (method === "initialize") {
    const protocolVersion = params?.protocolVersion || "2024-11-05";
    return jsonRpcResult(id, {
      protocolVersion,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "cursor-stage-submit", version: "1.0.0" },
    });
  }
  if (method === "ping") {
    return jsonRpcResult(id, {});
  }
  if (method === "tools/list" || method === "tools-list") {
    return jsonRpcResult(id, { tools: [toolDefinition(config)] });
  }
  if (method === "tools/call" || method === "tools-call") {
    if (isSmokeSuppressTool(env, config.submitDir)) {
      return jsonRpcResult(id, {
        content: [{ type: "text", text: "CURSOR_SMOKE_SUPPRESS_TOOL: submit suppressed without recording" }],
        isError: true,
      });
    }
    const name = params?.name;
    const args = params?.arguments ?? {};
    try {
      const outcome = handleSubmitCall(config, args, name);
      if (!outcome.ok) {
        return jsonRpcResult(id, {
          content: [{ type: "text", text: outcome.reason }],
          isError: true,
        });
      }
      return jsonRpcResult(id, {
        content: [{ type: "text", text: `Submitted ${config.expectedTool} seq=${outcome.attempt.record.seq}` }],
      });
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      try {
        writeAttempt(config.submitDir, {
          receivedAt: new Date().toISOString(),
          tool: name || config.expectedTool,
          binding: claimedBinding(args),
          bindingMatches: false,
          payload: args?.payload ?? null,
          outcome: "rejected",
          reason: `write failure: ${reason}`,
        });
      } catch {
        // Surface the original write/tool error when a rejected receipt cannot be recorded.
      }
      return jsonRpcResult(id, {
        content: [{ type: "text", text: reason }],
        isError: true,
      });
    }
  }
  if (id === undefined) return null;
  return jsonRpcError(id, -32601, `Method not found: ${method}`);
}

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function runStdio(config) {
  let buffer = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    buffer += chunk;
    while (true) {
      if (buffer.startsWith("{") || buffer.startsWith("[")) {
        const newline = buffer.indexOf("\n");
        if (newline < 0) break;
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (!line) continue;
        let parsed;
        try {
          parsed = JSON.parse(line);
        } catch {
          send(jsonRpcError(null, -32700, "Parse error"));
          continue;
        }
        const reply = handleJsonRpc(config, parsed);
        if (reply) send(reply);
        continue;
      }
      const headerEnd = buffer.indexOf("\r\n\r\n");
      if (headerEnd < 0) break;
      const headers = buffer.slice(0, headerEnd);
      const match = headers.match(/Content-Length:\s*(\d+)/i);
      if (!match) {
        buffer = buffer.slice(headerEnd + 4);
        continue;
      }
      const length = Number(match[1]);
      const start = headerEnd + 4;
      if (buffer.length < start + length) break;
      const body = buffer.slice(start, start + length);
      buffer = buffer.slice(start + length);
      let parsed;
      try {
        parsed = JSON.parse(body);
      } catch {
        send(jsonRpcError(null, -32700, "Parse error"));
        continue;
      }
      const reply = handleJsonRpc(config, parsed);
      if (reply) send(reply);
    }
  });
}

function isMainModule() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    return resolve(entry) === fileURLToPath(import.meta.url);
  } catch {
    return false;
  }
}

if (isMainModule()) {
  try {
    const config = loadConfig(parseConfigPath(process.argv.slice(2)));
    runStdio(config);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exit(1);
  }
}
