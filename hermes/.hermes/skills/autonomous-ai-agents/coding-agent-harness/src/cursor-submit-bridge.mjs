/**
 * Per-run Cursor Stage Submit Bridge generator and receipt reconciliation.
 *
 * Confirmed `--plugin-dir` layout (live probe, Cursor CLI 2026.09.15-d2fe57e):
 * Agent Plugin at the plugin root:
 *   plugin.json  — Agent Plugins manifest ($schema + name)
 *   mcp.json     — mcpServers.<id> {type:"stdio", command, args}
 * MCP stdio handshake observed: initialize + tools/list against the configured command.
 */

import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  ATTEMPT_SCHEMA,
  CONFIG_SCHEMA,
  SUBMIT_TOOL_NAMES,
  SUBMIT_TOOLS,
  listAttempts,
} from "../extensions/cursor-stage-submit/server.mjs";

const SERVER_PATH = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "extensions",
  "cursor-stage-submit",
  "server.mjs",
);

export const PLUGIN_LAYOUT = Object.freeze({
  format: "agent-plugin",
  manifestFile: "plugin.json",
  mcpFile: "mcp.json",
  evidence: "Cursor CLI 2026.09.15-d2fe57e --plugin-dir loaded plugin.json + mcp.json; echo MCP received initialize and tools/list",
});

function assertKnownTool(expectedTool) {
  if (!SUBMIT_TOOL_NAMES.includes(expectedTool)) {
    throw new Error(`unknown submit tool: ${expectedTool}`);
  }
}

function canonicalJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

export function generateSubmitBridge({ adapterDir, job, jobSha256, expectedTool, phase }) {
  assertKnownTool(expectedTool);
  if (!job || typeof job.jobId !== "string" || job.jobId.length === 0) {
    throw new Error("job.jobId is required");
  }
  if (typeof jobSha256 !== "string" || jobSha256.length === 0) {
    throw new Error("jobSha256 is required");
  }
  if (typeof phase !== "string" || phase.length === 0) {
    throw new Error("phase is required");
  }
  if (typeof job.stage !== "string" || job.stage.length === 0) {
    throw new Error("job.stage is required");
  }
  const stage = job.stage;
  if (SUBMIT_TOOLS[stage] && SUBMIT_TOOLS[stage] !== expectedTool) {
    throw new Error(`expectedTool ${expectedTool} does not match stage ${stage}`);
  }

  const pluginDir = resolve(adapterDir, "submit-bridge");
  const submitDir = resolve(adapterDir, "submit");
  mkdirSync(pluginDir, { recursive: true });
  mkdirSync(submitDir, { recursive: true });

  const configPath = join(pluginDir, "config.json");
  const config = {
    schema: CONFIG_SCHEMA,
    jobId: job.jobId,
    jobSha256,
    stage,
    expectedTool,
    runNonce: randomUUID(),
    phase,
    submitDir,
  };
  writeFileSync(configPath, canonicalJson(config));

  const pluginManifest = {
    $schema: "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
    name: "cursor-stage-submit",
    version: "1.0.0",
    description: "Run-scoped Stage Submit Bridge for coding-agent-harness",
  };
  writeFileSync(join(pluginDir, PLUGIN_LAYOUT.manifestFile), canonicalJson(pluginManifest));

  const mcp = {
    mcpServers: {
      "cursor-stage-submit": {
        type: "stdio",
        command: process.execPath,
        args: [SERVER_PATH, "--config", configPath],
      },
    },
  };
  writeFileSync(join(pluginDir, PLUGIN_LAYOUT.mcpFile), canonicalJson(mcp));

  return { pluginDir, config, submitDir, configPath, serverPath: SERVER_PATH };
}

export function classifySubmissions(submitDir) {
  const listed = listAttempts(submitDir);
  const attempts = listed.map((item) => item.record);
  const accepted = attempts.filter((item) => item.outcome === "accepted");
  const rejected = attempts.filter((item) => item.outcome === "rejected");

  if (accepted.length >= 2) {
    return { kind: "duplicate", accepted: null, attempts };
  }
  if (rejected.length > 0) {
    return { kind: "invalid", accepted: null, attempts };
  }
  if (accepted.length === 1 && rejected.length === 0) {
    return { kind: "ok", accepted: accepted[0], attempts };
  }
  return { kind: "missing", accepted: null, attempts };
}

export { ATTEMPT_SCHEMA, CONFIG_SCHEMA, SUBMIT_TOOL_NAMES, SUBMIT_TOOLS, SERVER_PATH };
