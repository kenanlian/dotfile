import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { STAGE_CONTRACTS, typedError } from "./contracts.mjs";
import { classifySubmissions, generateSubmitBridge } from "./cursor-submit-bridge.mjs";
import { createCursorEventNormalizer } from "./events.mjs";
import { compileCursorRecoveryBrief } from "./prompts.mjs";
import { canonicalJson, sha256Text } from "./util.mjs";

const HARNESS_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const DEFAULT_CURSOR_RELAY_PATH = join(HARNESS_ROOT, "..", "cursor-delegate", "scripts", "relay.mjs");

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

function timeoutFlag(timeoutSeconds) {
  if (timeoutSeconds === null || timeoutSeconds === undefined) return [];
  return ["--timeout", `${timeoutSeconds}s`];
}

function emptyAdapterFailure(error, expectedSession = null) {
  return {
    status: error.kind === "adapter_unavailable" ? "unavailable"
      : error.kind === "timed_out" ? "timed_out"
        : error.kind === "aborted" ? "aborted"
          : "failed",
    sessionId: expectedSession,
    structuredOutput: null,
    structuredOutputError: null,
    usage: {},
    resolvedModel: null,
    adapterRuns: [],
    recovered: false,
    error,
    relay: null,
    raw: { primary: null },
  };
}

function resumeSessionId(job, recovery) {
  if (recovery) return job._recoverySessionId || job.agent.sessionId;
  return job.agent.sessionId;
}

export function tryBuildCursorRelayArgs({
  briefPath,
  repoRoot,
  adapterOutDir,
  job,
  phase,
  pluginDir,
  recovery = false,
  env = process.env,
}) {
  void phase;
  void env;
  const contract = STAGE_CONTRACTS[job.stage];
  if (!contract) {
    return { ok: false, error: typedError("invalid_job", "/stage", `unknown stage ${job.stage}`) };
  }
  const args = [
    "--brief", briefPath,
    "--cd", repoRoot,
    "--out-dir", adapterOutDir,
    job.permissions.mode === "write" && !recovery ? "--force" : "--read-only",
    "--model", job.agent.model,
  ];
  const sessionId = resumeSessionId(job, recovery);
  if (sessionId) args.push("--session", sessionId);
  args.push("--plugin-dir", pluginDir);
  args.push(...timeoutFlag(job.limits?.timeoutSeconds ?? null));
  return { ok: true, args };
}

function writeSpawnRecord(adapterOutDir, { job, pluginDir, expectedTool, runNonce, relay }) {
  const spawnInfo = relay?.spawn && typeof relay.spawn === "object" ? relay.spawn : { argv: null, envKeys: [] };
  writeFileSync(join(adapterOutDir, "spawn-record.json"), canonicalJson({
    stage: job.stage,
    adapter: "cursor",
    pluginDir,
    expectedTool,
    runNonce,
    argv: Array.isArray(spawnInfo.argv) ? spawnInfo.argv : null,
    envKeys: Array.isArray(spawnInfo.envKeys) ? spawnInfo.envKeys : [],
  }));
}

function classifyTransportError(relay, expectedSession) {
  if (!relay) {
    return typedError("adapter_failed", "/adapter", "relay produced no result.json");
  }
  if (expectedSession) {
    if (relay.status === "completed" && !relay.sessionId) {
      return typedError(
        "session_mismatch",
        "/agent/sessionId",
        `completed resume missing session ${expectedSession}`,
      );
    }
    if (relay.sessionId && relay.sessionId !== expectedSession) {
      return typedError("session_mismatch", "/agent/sessionId", `session ${relay.sessionId} did not match ${expectedSession}`);
    }
  }
  if (relay.status === "unavailable") {
    return typedError("adapter_unavailable", "/adapter", relay.error || "cursor unavailable");
  }
  if (relay.status === "timeout") {
    return typedError("timed_out", "/adapter", relay.error || "relay timed out");
  }
  if (relay.status === "aborted") {
    return typedError("aborted", "/adapter", relay.error || "relay aborted");
  }
  if (relay.status !== "completed") {
    return typedError("adapter_failed", "/adapter", relay.error || `relay status ${relay.status}`);
  }
  return null;
}

function protocolErrorFor(classification, expectedTool) {
  if (!classification || classification.kind === "ok") return null;
  if (classification.kind === "missing") {
    return typedError("structured_output_missing", "/structuredOutput", `${expectedTool} was not called`);
  }
  if (classification.kind === "duplicate") {
    const acceptedCount = classification.attempts.filter((item) => item.outcome === "accepted").length;
    return typedError("structured_output_duplicate", "/structuredOutput", `${expectedTool} succeeded ${acceptedCount} times`);
  }
  return typedError("structured_output_invalid", "/structuredOutput", `${expectedTool} submission was invalid`);
}

export let activeCursorChild = null;

function registerActiveChild(child) {
  activeCursorChild = child;
  import("./active-adapter-child.mjs").then((m) => m.setActiveAdapterChild(child)).catch(() => {
    /* WP-07 not landed; local hook only */
  });
}

function spawnRelay({ relayPath, args, cwd, env, stdoutPath, stderrPath }) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [relayPath, ...args], {
      cwd,
      env,
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
    });
    registerActiveChild(child);
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
      registerActiveChild(null);
      reject(err);
    });
    child.on("close", (code, signal) => {
      registerActiveChild(null);
      resolve({
        child,
        exitCode: code,
        signal,
        stdout: Buffer.concat(stdoutChunks).toString("utf8"),
        stderr: Buffer.concat(stderrChunks).toString("utf8"),
      });
    });
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

function phasePaths(phase, adapterOutDir) {
  return {
    phase,
    result: join(adapterOutDir, "result.json"),
    events: join(adapterOutDir, "events.jsonl"),
    stderr: join(adapterOutDir, "stderr.txt"),
    final: join(adapterOutDir, "final.txt"),
  };
}

async function runOneRelay({
  phase,
  job,
  briefText,
  adapterOutDir,
  relayPath,
  env,
  events,
  recovery,
  jobSha256,
}) {
  mkdirSync(adapterOutDir, { recursive: true });
  const paths = phasePaths(phase, adapterOutDir);
  const contract = STAGE_CONTRACTS[job.stage];
  if (!contract) {
    return {
      phase,
      relay: null,
      spawned: null,
      assembleError: typedError("invalid_job", "/stage", `unknown stage ${job.stage}`),
      paths,
      diagnostics: { ignored: 0 },
      classification: { kind: "missing", accepted: null, attempts: [] },
      bridge: null,
    };
  }

  const bridge = generateSubmitBridge({
    adapterDir: adapterOutDir,
    job,
    jobSha256,
    expectedTool: contract.submitTool,
    phase,
  });
  const resolvedBrief = typeof briefText === "function" ? briefText(bridge) : briefText;
  const briefPath = join(adapterOutDir, "brief.txt");
  writeFileSync(briefPath, resolvedBrief);
  const harnessStdout = join(adapterOutDir, "harness-stdout.log");
  const harnessStderr = join(adapterOutDir, "harness-stderr.log");
  writeFileSync(harnessStdout, "");
  writeFileSync(harnessStderr, "");
  const built = tryBuildCursorRelayArgs({
    briefPath,
    repoRoot: job.workspace.repoRoot,
    adapterOutDir,
    job,
    phase,
    pluginDir: bridge.pluginDir,
    recovery,
    env,
  });
  if (!built.ok) {
    return {
      phase,
      relay: null,
      spawned: null,
      assembleError: built.error,
      paths,
      diagnostics: { ignored: 0 },
      classification: classifySubmissions(bridge.submitDir),
      bridge,
    };
  }

  const normalizer = createCursorEventNormalizer(events);
  const offsetRef = { value: 0 };
  const eventsPath = paths.events;
  const poll = setInterval(() => tailEventsFile(eventsPath, normalizer, offsetRef), 20);
  let spawned = null;
  try {
    spawned = await spawnRelay({
      relayPath,
      args: built.args,
      cwd: job.workspace.repoRoot,
      env,
      stdoutPath: harnessStdout,
      stderrPath: harnessStderr,
    });
  } catch {
    spawned = null;
  } finally {
    clearInterval(poll);
    tailEventsFile(eventsPath, normalizer, offsetRef);
    normalizer.flush();
  }

  const relay = readJsonIfExists(paths.result);
  writeSpawnRecord(adapterOutDir, {
    job,
    pluginDir: bridge.pluginDir,
    expectedTool: contract.submitTool,
    runNonce: bridge.config.runNonce,
    relay,
  });
  return {
    phase,
    relay,
    spawned,
    paths,
    diagnostics: normalizer.diagnostics,
    classification: classifySubmissions(bridge.submitDir),
    bridge,
  };
}

export async function runCursorAdapter(context) {
  const {
    job,
    brief,
    outDir,
    events,
    relayPath = process.env.CODING_AGENT_CURSOR_RELAY_PATH || DEFAULT_CURSOR_RELAY_PATH,
    env = process.env,
    jobSha256 = sha256Text(canonicalJson(job)),
  } = context;
  const contract = STAGE_CONTRACTS[job.stage];
  const expectedSession = job.agent.sessionId;
  if (!contract) {
    return emptyAdapterFailure(
      typedError("invalid_job", "/stage", `unknown stage ${job.stage}`),
      expectedSession,
    );
  }

  const adapterRoot = join(outDir, "adapter");
  const primaryDir = join(adapterRoot, "primary");
  const primary = await runOneRelay({
    phase: "primary",
    job,
    briefText: brief,
    adapterOutDir: primaryDir,
    relayPath,
    env,
    events,
    recovery: false,
    jobSha256,
  });
  if (primary.assembleError) {
    return {
      ...emptyAdapterFailure(primary.assembleError, expectedSession),
      adapterRuns: [primary.paths],
      raw: { primary: primary.paths },
    };
  }

  const adapterRuns = [primary.paths];
  let relay = primary.relay;
  let classification = primary.classification;
  let recovered = false;

  const missing = relay
    && relay.status === "completed"
    && classification?.kind === "missing"
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
      briefText: (bridge) => compileCursorRecoveryBrief(recoveryJob, {
        submitBinding: bridge.config,
        submitConfigPath: bridge.configPath,
      }),
      adapterOutDir: join(adapterRoot, "output-recovery"),
      relayPath,
      env,
      events,
      recovery: true,
      jobSha256,
    });
    adapterRuns.push(recovery.paths);
    relay = recovery.relay;
    classification = recovery.classification;
    recovered = true;
    if (recovery.assembleError) {
      return {
        status: "failed",
        sessionId: expectedSession,
        structuredOutput: null,
        structuredOutputError: null,
        usage: {},
        resolvedModel: null,
        adapterRuns,
        recovered,
        error: recovery.assembleError,
        relay,
        raw: { primary: primary.paths },
      };
    }
  }

  const status = mapRelayStatus(relay);
  const transportError = classifyTransportError(relay, expectedSession);
  const protocolError = !transportError && relay?.status === "completed"
    ? protocolErrorFor(classification, contract.submitTool)
    : null;
  const error = transportError || protocolError;
  const terminalStatus = error
    ? (error.kind === "timed_out" ? "timed_out"
      : error.kind === "aborted" ? "aborted"
        : error.kind === "adapter_unavailable" ? "unavailable"
          : "failed")
    : status;

  const structuredOutput = !error && classification?.kind === "ok"
    ? { tool: contract.submitTool, payload: classification.accepted?.payload ?? null }
    : null;

  return {
    status: terminalStatus,
    sessionId: relay?.sessionId ?? expectedSession,
    structuredOutput,
    structuredOutputError: error && error.path === "/structuredOutput" ? error.message : null,
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
