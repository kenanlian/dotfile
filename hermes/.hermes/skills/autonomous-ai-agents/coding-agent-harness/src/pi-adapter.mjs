import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { STAGE_CONTRACTS, typedError } from "./contracts.mjs";
import { createPiEventNormalizer } from "./events.mjs";
import { sha256Text } from "./util.mjs";

const HARNESS_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const DEFAULT_RELAY_PATH = join(HARNESS_ROOT, "..", "pi-delegate", "scripts", "relay.mjs");
export const DEFAULT_STAGE_SUBMIT_ROOT = join(HARNESS_ROOT, "extensions", "stage-submit");

function readJsonIfExists(path) {
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8"));
}

function mapRelayStatus(relay) {
  if (!relay) return "failed";
  if (relay.status === "timeout") return "timed_out";
  if (relay.status === "completed" || relay.status === "failed" || relay.status === "aborted" || relay.status === "unavailable") {
    return relay.status;
  }
  return "failed";
}

function isMissingToolError(message, tool) {
  return typeof message === "string" && message.includes(`${tool} was not called`);
}

function timeoutFlag(timeoutSeconds) {
  if (timeoutSeconds === null || timeoutSeconds === undefined) return [];
  return ["--timeout", `${timeoutSeconds}s`];
}

export function buildRelayArgs({
  briefPath,
  repoRoot,
  outDir,
  job,
  recovery = false,
  extensionRoot = DEFAULT_STAGE_SUBMIT_ROOT,
}) {
  const contract = STAGE_CONTRACTS[job.stage];
  const args = [
    "--brief", briefPath,
    "--cd", repoRoot,
    "--out-dir", outDir,
    job.permissions.mode === "write" && !recovery ? "--write" : "--read-only",
    "--model", job.agent.model,
    "--thinking", job.agent.thinking,
    "--structured-output-tool", contract.submitTool,
    "--structured-output-extension", extensionRoot,
  ];
  const sessionId = recovery ? job._recoverySessionId || job.agent.sessionId : job.agent.sessionId;
  if (sessionId) args.push("--session", sessionId);
  if (recovery) args.push("--structured-output-recovery");
  args.push(...timeoutFlag(job.limits?.timeoutSeconds ?? null));
  return args;
}

function classifyAdapterError(relay, job, expectedSession) {
  if (!relay) {
    return typedError("adapter_failed", "/adapter", "relay produced no result.json");
  }
  if (relay.status === "unavailable") {
    return typedError("adapter_unavailable", "/adapter", relay.error || "pi unavailable");
  }
  if (relay.status === "timeout") {
    return typedError("timed_out", "/adapter", relay.error || "relay timed out");
  }
  if (relay.status === "aborted") {
    return typedError("aborted", "/adapter", relay.error || "relay aborted");
  }
  if (expectedSession && relay.sessionId && relay.sessionId !== expectedSession) {
    return typedError("session_mismatch", "/agent/sessionId", `session ${relay.sessionId} did not match ${expectedSession}`);
  }
  if (relay.status === "completed" && relay.error && /agent_settled was never observed/.test(relay.error)) {
    return typedError("agent_not_settled", "/adapter", relay.error);
  }
  if (relay.status !== "completed") {
    if (relay.error && /agent_settled was never observed/.test(relay.error)) {
      return typedError("agent_not_settled", "/adapter", relay.error);
    }
    return typedError("adapter_failed", "/adapter", relay.error || `relay status ${relay.status}`);
  }
  return null;
}

export let activeRelayChild = null;

function spawnRelay({ relayPath, args, cwd, env, stdoutPath, stderrPath, onEventsChunk }) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [relayPath, ...args], {
      cwd,
      env,
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
    });
    activeRelayChild = child;
    const stdoutChunks = [];
    const stderrChunks = [];
    child.stdout.on("data", (chunk) => {
      stdoutChunks.push(chunk);
      writeFileSync(stdoutPath, Buffer.concat(stdoutChunks));
    });
    child.stderr.on("data", (chunk) => {
      stderrChunks.push(chunk);
      writeFileSync(stderrPath, Buffer.concat(stderrChunks));
    });
    child.on("error", (err) => {
      activeRelayChild = null;
      reject(err);
    });
    child.on("close", (code, signal) => {
      activeRelayChild = null;
      resolve({
        child,
        exitCode: code,
        signal,
        stdout: Buffer.concat(stdoutChunks).toString("utf8"),
        stderr: Buffer.concat(stderrChunks).toString("utf8"),
      });
    });
    if (onEventsChunk) {
      /* events are tailed from the adapter out-dir, not relay stdout */
    }
  });
}

function tailEventsFile(eventsPath, normalizer, offsetRef) {
  if (!existsSync(eventsPath)) return;
  const content = readFileSync(eventsPath, "utf8");
  if (content.length <= offsetRef.value) return;
  const chunk = content.slice(offsetRef.value);
  offsetRef.value = content.length;
  normalizer.push(chunk);
}

async function runOneRelay({
  phase,
  job,
  briefPath,
  adapterOutDir,
  relayPath,
  extensionRoot,
  env,
  events,
  recovery,
}) {
  mkdirSync(adapterOutDir, { recursive: true });
  const harnessStdout = join(adapterOutDir, "harness-stdout.log");
  const harnessStderr = join(adapterOutDir, "harness-stderr.log");
  writeFileSync(harnessStdout, "");
  writeFileSync(harnessStderr, "");
  const args = buildRelayArgs({
    briefPath,
    repoRoot: job.workspace.repoRoot,
    outDir: adapterOutDir,
    job,
    recovery,
    extensionRoot,
  });
  const normalizer = createPiEventNormalizer(events);
  const offsetRef = { value: 0 };
  const eventsPath = join(adapterOutDir, "events.jsonl");
  const poll = setInterval(() => tailEventsFile(eventsPath, normalizer, offsetRef), 20);
  let spawned;
  try {
    spawned = await spawnRelay({
      relayPath,
      args,
      cwd: job.workspace.repoRoot,
      env,
      stdoutPath: harnessStdout,
      stderrPath: harnessStderr,
    });
  } finally {
    clearInterval(poll);
    tailEventsFile(eventsPath, normalizer, offsetRef);
    normalizer.flush();
  }
  const relay = readJsonIfExists(join(adapterOutDir, "result.json"));
  return {
    phase,
    relay,
    spawned,
    paths: {
      phase,
      result: join(adapterOutDir, "result.json"),
      events: eventsPath,
      stderr: join(adapterOutDir, "stderr.txt"),
      final: join(adapterOutDir, "final.txt"),
    },
    diagnostics: normalizer.diagnostics,
  };
}

export async function runPiAdapter(context) {
  const {
    job,
    brief,
    outDir,
    events,
    relayPath = process.env.CODING_AGENT_RELAY_PATH || DEFAULT_RELAY_PATH,
    extensionRoot = DEFAULT_STAGE_SUBMIT_ROOT,
    env = process.env,
  } = context;
  const contract = STAGE_CONTRACTS[job.stage];
  const adapterRoot = join(outDir, "adapter");
  const primaryDir = join(adapterRoot, "primary");
  mkdirSync(primaryDir, { recursive: true });
  const briefPath = join(primaryDir, "brief.txt");
  writeFileSync(briefPath, brief);
  sha256Text(brief);

  const expectedSession = job.agent.sessionId;
  const primary = await runOneRelay({
    phase: "primary",
    job,
    briefPath,
    adapterOutDir: primaryDir,
    relayPath,
    extensionRoot,
    env,
    events,
    recovery: false,
  });
  const adapterRuns = [primary.paths];
  let relay = primary.relay;
  let recovered = false;

  const missing = relay
    && relay.status === "completed"
    && relay.structuredOutput == null
    && isMissingToolError(relay.structuredOutputError, contract.submitTool)
    && relay.sessionId;

  if (missing) {
    const recoveryJob = {
      ...job,
      agent: { ...job.agent, sessionId: relay.sessionId },
      _recoverySessionId: relay.sessionId,
    };
    const recovery = await runOneRelay({
      phase: "output-recovery",
      job: recoveryJob,
      briefPath,
      adapterOutDir: join(adapterRoot, "output-recovery"),
      relayPath,
      extensionRoot,
      env,
      events,
      recovery: true,
    });
    adapterRuns.push(recovery.paths);
    relay = recovery.relay;
    recovered = true;
  }

  const status = mapRelayStatus(relay);
  const sessionError = expectedSession && relay?.sessionId && relay.sessionId !== expectedSession
    ? typedError("session_mismatch", "/agent/sessionId", `session ${relay.sessionId} did not match ${expectedSession}`)
    : null;
  const transportError = sessionError || classifyAdapterError(relay, job, expectedSession);
  let protocolError = null;
  if (!transportError && relay?.status === "completed") {
    if (relay.structuredOutputError && isMissingToolError(relay.structuredOutputError, contract.submitTool)) {
      protocolError = typedError("structured_output_missing", "/structuredOutput", relay.structuredOutputError);
    } else if (relay.structuredOutputError && /succeeded \d+ times/.test(relay.structuredOutputError)) {
      protocolError = typedError("structured_output_duplicate", "/structuredOutput", relay.structuredOutputError);
    } else if (relay.structuredOutputError) {
      protocolError = typedError("structured_output_invalid", "/structuredOutput", relay.structuredOutputError);
    } else if (!relay.structuredOutput) {
      protocolError = typedError("structured_output_missing", "/structuredOutput", "structured output was null");
    } else if (relay.structuredOutput.tool !== contract.submitTool) {
      protocolError = typedError("structured_output_invalid", "/structuredOutput", `expected tool ${contract.submitTool}`);
    }
  }

  const error = transportError || protocolError;
  const terminalStatus = error
    ? (error.kind === "timed_out" ? "timed_out"
      : error.kind === "aborted" ? "aborted"
        : error.kind === "adapter_unavailable" ? "unavailable"
          : "failed")
    : status;

  return {
    status: terminalStatus,
    sessionId: relay?.sessionId ?? expectedSession,
    structuredOutput: error ? null : relay?.structuredOutput ?? null,
    structuredOutputError: relay?.structuredOutputError ?? null,
    usage: relay?.usage ?? {},
    resolvedModel: relay?.resolvedModel ?? null,
    adapterRuns,
    recovered,
    error,
    relay,
    raw: {
      primary: primary.paths,
    },
  };
}
