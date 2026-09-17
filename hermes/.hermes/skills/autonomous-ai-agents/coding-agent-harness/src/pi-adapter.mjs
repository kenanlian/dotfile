import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { STAGE_CONTRACTS, typedError } from "./contracts.mjs";
import { createPiEventNormalizer } from "./events.mjs";
import {
  EXPECT_EXTENSIONS_ENV,
  assertProfileResourcesExist,
  expectedExtensionsEnvValue,
  resolveStageProfile,
  verifyArgvConsistency,
  verifyHarnessAttestation,
} from "./stage-profiles.mjs";
import { canonicalJson, sha256Text } from "./util.mjs";

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

export function tryBuildRelayArgs({
  briefPath,
  repoRoot,
  outDir,
  job,
  recovery = false,
  extensionRoot = DEFAULT_STAGE_SUBMIT_ROOT,
  profile,
  env = process.env,
}) {
  let resolved = profile;
  if (!resolved) {
    const loaded = resolveStageProfile(job.stage, { env });
    if (!loaded.ok) return loaded;
    const roots = assertProfileResourcesExist(loaded.value);
    if (!roots.ok) return roots;
    resolved = roots.value;
  }
  const contract = STAGE_CONTRACTS[job.stage];
  if (!contract) {
    return { ok: false, error: typedError("invalid_job", "/stage", `unknown stage ${job.stage}`) };
  }
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
  for (const ext of resolved.extensionRoots) {
    if (ext.channel === "auto-handoff-plan") {
      const plan = (job.inputs || []).find((item) => item.kind === "plan");
      if (!plan?.path) {
        return {
          ok: false,
          error: typedError(
            "invalid_job",
            "/inputs",
            `stage ${job.stage} profile ${resolved.profileId} requires a plan input for auto-handoff`,
          ),
        };
      }
      args.push("--auto-handoff-plan", plan.path);
    } else {
      args.push("--extension", ext.root);
    }
  }
  for (const [key, value] of Object.entries(resolved.env)) {
    args.push("--env", `${key}=${value}`);
  }
  if (resolved.toolsExtra.length > 0) args.push("--extra-tools", resolved.toolsExtra.join(","));
  const skills = resolved.skills || { mode: "auto", paths: [] };
  if (skills.mode === "explicit") {
    args.push("--no-skills");
    for (const skillPath of skills.paths) args.push("--skill", skillPath);
  }
  args.push("--env", `${EXPECT_EXTENSIONS_ENV}=${expectedExtensionsEnvValue(resolved)}`);
  args.push(...timeoutFlag(job.limits?.timeoutSeconds ?? null));
  return { ok: true, args, profile: resolved };
}

export function buildRelayArgs(options) {
  const built = tryBuildRelayArgs(options);
  if (!built.ok) {
    const error = new Error(built.error.message);
    error.typedError = built.error;
    throw error;
  }
  return built.args;
}

function writeSpawnRecord(adapterOutDir, job, profile, relay) {
  const spawn = relay?.spawn && typeof relay.spawn === "object" ? relay.spawn : { argv: null, envKeys: [] };
  writeFileSync(join(adapterOutDir, "spawn-record.json"), canonicalJson({
    stage: job.stage,
    profileId: profile.profileId,
    expectedExtensionIds: profile.expectedExtensionIds,
    disabledEntries: profile.disabledEntries,
    argv: Array.isArray(spawn.argv) ? spawn.argv : null,
    envKeys: Array.isArray(spawn.envKeys) ? spawn.envKeys : [],
  }));
}

function verifyCompletedAssembly(relay, eventsPath, profile) {
  // Fail-closed after agent_settled: stage-submit must have written the
  // attestation line, and pi argv must match the resolved profile.
  // Pi 0.85.1 print/json empirically exits 1 on a bad `-e` (does not
  // warn-and-continue); attestation still proves this factory ran.
  // Skill mounting is not part of attestation — argv golden tests cover
  // `-ns` plus the exact `--skill` set. `toolsExtra` (e.g. `todo`) is
  // the `-t` allowlist hook, not a load proof: Pi silently ignores
  // unknown `-t` names.
  if (!existsSync(eventsPath)) {
    return typedError("extension_manifest_mismatch", "/adapter", "adapter events.jsonl is missing");
  }
  const eventsText = readFileSync(eventsPath, "utf8");
  const attestation = verifyHarnessAttestation(eventsText, profile.expectedExtensionIds);
  if (!attestation.ok) return attestation.error;
  const argv = relay?.spawn?.argv;
  const argvCheck = verifyArgvConsistency(argv, profile);
  if (!argvCheck.ok) return argvCheck.error;
  return null;
}

function classifyAdapterError(relay, job, expectedSession) {
  if (!relay) {
    return typedError("adapter_failed", "/adapter", "relay produced no result.json");
  }
  if (expectedSession) {
    const observedMissing = typeof relay.error === "string" && /no valid session id was observed/.test(relay.error);
    if (observedMissing || (relay.status === "completed" && !relay.sessionId)) {
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
    return typedError("adapter_unavailable", "/adapter", relay.error || "pi unavailable");
  }
  if (relay.status === "timeout") {
    return typedError("timed_out", "/adapter", relay.error || "relay timed out");
  }
  if (relay.status === "aborted") {
    return typedError("aborted", "/adapter", relay.error || "relay aborted");
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
  profile,
}) {
  mkdirSync(adapterOutDir, { recursive: true });
  const harnessStdout = join(adapterOutDir, "harness-stdout.log");
  const harnessStderr = join(adapterOutDir, "harness-stderr.log");
  writeFileSync(harnessStdout, "");
  writeFileSync(harnessStderr, "");
  const built = tryBuildRelayArgs({
    briefPath,
    repoRoot: job.workspace.repoRoot,
    outDir: adapterOutDir,
    job,
    recovery,
    extensionRoot,
    profile,
    env,
  });
  if (!built.ok) {
    return {
      phase,
      relay: null,
      spawned: null,
      assembleError: built.error,
      paths: {
        phase,
        result: join(adapterOutDir, "result.json"),
        events: join(adapterOutDir, "events.jsonl"),
        stderr: join(adapterOutDir, "stderr.txt"),
        final: join(adapterOutDir, "final.txt"),
      },
      diagnostics: { ignored: 0 },
    };
  }
  const normalizer = createPiEventNormalizer(events);
  const offsetRef = { value: 0 };
  const eventsPath = join(adapterOutDir, "events.jsonl");
  const poll = setInterval(() => tailEventsFile(eventsPath, normalizer, offsetRef), 20);
  let spawned;
  try {
    spawned = await spawnRelay({
      relayPath,
      args: built.args,
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
  writeSpawnRecord(adapterOutDir, job, profile, relay);
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
  const loaded = resolveStageProfile(job.stage, { env });
  if (!loaded.ok) return emptyAdapterFailure(loaded.error, job.agent.sessionId);
  const rooted = assertProfileResourcesExist(loaded.value);
  if (!rooted.ok) return emptyAdapterFailure(rooted.error, job.agent.sessionId);
  const profile = rooted.value;
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
    profile,
  });
  if (primary.assembleError) {
    return {
      ...emptyAdapterFailure(primary.assembleError, expectedSession),
      adapterRuns: [primary.paths],
    };
  }
  const adapterRuns = [primary.paths];
  let relay = primary.relay;
  let recovered = false;

  if (relay?.status === "completed") {
    const assemblyError = verifyCompletedAssembly(relay, primary.paths.events, profile);
    if (assemblyError) {
      return {
        status: "failed",
        sessionId: relay.sessionId ?? expectedSession,
        structuredOutput: null,
        structuredOutputError: relay.structuredOutputError ?? null,
        usage: relay.usage ?? {},
        resolvedModel: relay.resolvedModel ?? null,
        adapterRuns,
        recovered: false,
        error: assemblyError,
        relay,
        raw: { primary: primary.paths },
      };
    }
  }

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
      profile,
    });
    adapterRuns.push(recovery.paths);
    relay = recovery.relay;
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
    if (relay?.status === "completed") {
      const assemblyError = verifyCompletedAssembly(relay, recovery.paths.events, profile);
      if (assemblyError) {
        return {
          status: "failed",
          sessionId: relay.sessionId ?? expectedSession,
          structuredOutput: null,
          structuredOutputError: relay.structuredOutputError ?? null,
          usage: relay.usage ?? {},
          resolvedModel: relay.resolvedModel ?? null,
          adapterRuns,
          recovered,
          error: assemblyError,
          relay,
          raw: { primary: primary.paths },
        };
      }
    }
  }

  const status = mapRelayStatus(relay);
  const sessionError = expectedSession && (
    (relay?.status === "completed" && !relay?.sessionId)
    || (typeof relay?.error === "string" && /no valid session id was observed/.test(relay.error))
    || (relay?.sessionId && relay.sessionId !== expectedSession)
  )
    ? typedError(
      "session_mismatch",
      "/agent/sessionId",
      relay?.sessionId && relay.sessionId !== expectedSession
        ? `session ${relay.sessionId} did not match ${expectedSession}`
        : `completed resume missing session ${expectedSession}`,
    )
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
