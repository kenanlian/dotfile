#!/usr/bin/env node
/**
 * delegate-skills · pi-delegate · relay.mjs
 *
 * Dispatch a self-contained brief to the Pi coding agent CLI (`pi -p --mode json`),
 * capture the NDJSON event stream, and write a `delegate-relay.result.v1` result
 * the orchestrating agent can review. One command, then read one file.
 *
 * Verified against Pi 0.84.4 (macOS). Node built-ins only, no dependencies.
 *
 * Trust posture: relay.mjs makes no network calls, reads/writes no credentials,
 * sends no telemetry. It shells out only to `pi` and `git`. The `pi` process it
 * launches does authenticate — exactly as at the terminal. Read before running.
 *
 * Deterministic extension loading: the child runs with `--no-extensions` plus an
 * explicit `-e` pointing at the delegate-agent extension root, so `delegate_agent`
 * exists and nothing implicit loads. Global Skills discovery is NOT disabled:
 * Skills come from the single global root via the user's own Pi configuration;
 * the relay never copies or mirrors Skills.
 *
 * Read-only enforcement is the tool allowlist (`--tools read,grep,find,ls,delegate_agent`);
 * Pi has no permission wall. Write mode adds `bash,edit,write` to the allowlist.
 * Per the settled user decision, there is NO call_allowlist against a read-only
 * parent invoking a write child; this relay intentionally does not gate that.
 *
 * The brief rides a temp file consumed at Pi's final argv position (Pi takes the
 * prompt as a positional argument), so it is never visible in the host process
 * list. The temp file is removed after the Pi child exits.
 *
 * It deliberately does NOT commit, push, or perform any remote/release action.
 * Committing is always the orchestrator's job.
 *
 * Usage:
 *   node relay.mjs --brief <file> [options]
 *   cat brief.txt | node relay.mjs [options]
 *
 * Options:
 *   --brief <file>       Path to the brief. If omitted, read from stdin.
 *   --cd <dir>           Exact working root; child process cwd. Default: cwd.
 *   --read-only          Tool allowlist read,grep,find,ls,delegate_agent (default).
 *   --write              Tool allowlist read,grep,find,ls,bash,edit,write,delegate_agent.
 *   --model <id>         Explicit provider-prefixed model, e.g. zai-coding-cn/glm-5.3.
 *                        Optional :thinking suffix also accepted.
 *   --thinking <level>   off|minimal|low|medium|high|xhigh|max. Default: high.
 *   --session <id>       Resume one exact Pi session (--session-id, create-if-missing).
 *   --timeout <dur>      Optional relay-side watchdog (default: off; h/m/s strings).
 *   --out-dir <dir>      Where to write run artifacts (default: fresh temp dir).
 *   -h, --help           Show this help.
 *
 * Result: written to <out-dir>/result.json —
 *   schema delegate-relay.result.v1, tool "pi", status, exitCode, signal,
 *   piVersion, sessionId, cwd, mode, requestedModel, resolvedModel, thinking,
 *   resumed, startedAt, finishedAt, finalMessage, touchedFiles (git porcelain
 *   under --cd), usage, briefPath/finalPath/eventsPath/stderrPath, and
 *   error/stderrTail on failure.
 *
 * Completion requires: process exit + exit code 0 + Pi agent_settled observed
 * + a valid session id + atomically written result.json. On any failure the
 * artifacts and working tree are preserved (nothing is cleaned).
 *
 * Exit codes: pre-run usage error exits 2 and writes no result; a missing `pi`
 * binary exits 127 with status pi_unavailable; otherwise exit mirrors the
 * mapped terminal status (0 completed, non-zero otherwise).
 */

import { spawn, execFileSync, spawnSync } from "node:child_process";
import {
  mkdirSync, writeFileSync, renameSync, rmSync, readFileSync, existsSync,
  appendFileSync, mkdtempSync, unlinkSync,
} from "node:fs";
import { join, resolve, basename, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { constants, tmpdir } from "node:os";
import { StringDecoder } from "node:string_decoder";

const MAX_TIMER_MS = 2_147_483_647;
const VERSION_PROBE_TIMEOUT_MS = 10_000;
const SAFE_MODEL = /^[A-Za-z0-9][A-Za-z0-9._:@/-]*$/;
const SAFE_SESSION = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const THINKING_LEVELS = new Set(["off", "minimal", "low", "medium", "high", "xhigh", "max"]);
const READ_ONLY_TOOLS = ["read", "grep", "find", "ls", "delegate_agent"];
const WRITE_TOOLS = ["read", "grep", "find", "ls", "bash", "edit", "write", "delegate_agent"];

/** The delegate-agent extension root: `-e` takes a directory, not a module file. */
function delegateAgentRoot() {
  const self = dirname(fileURLToPath(import.meta.url));
  // Layout fallback order: neither repo is guaranteed present; probe both.
  const candidates = [
    join(self, "extensions", "delegate-agent"),
    process.env.PI_DELEGATE_AGENT_ROOT || "",
    join(process.env.HOME || "", ".pi", "agent", "extensions", "delegate-agent"),
    join(process.env.HOME || "", "Secret-Projects", "pi-delegate-agent"),
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (existsSync(join(candidate, "index.ts")) || existsSync(join(candidate, "index.js"))) {
      return candidate;
    }
  }
  return null;
}

function fail(message, code = 2) {
  process.stderr.write(`relay: ${message}\n`);
  process.exit(code);
}

function parseDuration(duration) {
  const match = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/.exec(duration);
  if (!match || (!match[1] && !match[2] && !match[3])) return null;
  const seconds =
    BigInt(match[1] || 0) * 3600n + BigInt(match[2] || 0) * 60n + BigInt(match[3] || 0);
  const milliseconds = seconds * 1000n;
  if (milliseconds <= 0n || milliseconds > BigInt(MAX_TIMER_MS)) return null;
  return Number(milliseconds);
}

function parseArgs(argv) {
  const opts = {
    brief: null,
    cd: process.cwd(),
    readOnly: true,
    write: false,
    model: null,
    thinking: "high",
    session: null,
    timeout: null,
    outDir: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (value === undefined) fail(`${arg} requires a value`);
      i += 1;
      return value;
    };
    switch (arg) {
      case "-h":
      case "--help":
        process.stdout.write(headerComment());
        process.exit(0);
        break;
      case "--brief": opts.brief = next(); break;
      case "--cd": opts.cd = resolve(next()); break;
      case "--read-only": opts.readOnly = true; opts.write = false; break;
      case "--write": opts.write = true; opts.readOnly = false; break;
      case "--model": opts.model = next(); break;
      case "--thinking": opts.thinking = next(); break;
      case "--session": opts.session = next(); break;
      case "--timeout": opts.timeout = next(); break;
      case "--out-dir": opts.outDir = resolve(next()); break;
      default:
        fail(`unknown option: ${arg}`);
    }
  }
  if (opts.model !== null && !SAFE_MODEL.test(opts.model)) {
    fail(`--model contains unsupported characters (allowed: letters, digits, . _ : @ / -)`);
  }
  if (opts.session !== null && !SAFE_SESSION.test(opts.session)) {
    fail(`--session contains unsupported characters (allowed: letters, digits, . _ -)`);
  }
  if (!THINKING_LEVELS.has(opts.thinking)) {
    fail(`--thinking "${opts.thinking}" is invalid; expected one of ${[...THINKING_LEVELS].join(", ")}`);
  }
  if (opts.timeout !== null && parseDuration(opts.timeout) === null) {
    fail(`--timeout "${opts.timeout}" is invalid; use a positive h/m/s duration no longer than about 24 days`);
  }
  return opts;
}

function headerComment() {
  const src = readFileSync(new URL(import.meta.url), "utf8");
  const match = src.match(/\/\*\*([\s\S]*?)\*\//);
  if (!match) return "relay.mjs — dispatch a brief to pi -p --mode json\n";
  return `${match[1].replace(/^\s*\* ?/gm, "").trim()}\n`;
}

function readBrief(opts) {
  if (opts.brief) {
    if (!existsSync(opts.brief)) fail(`brief file not found: ${opts.brief}`);
    return readFileSync(opts.brief, "utf8");
  }
  if (process.stdin.isTTY) {
    fail("no --brief given and stdin is a TTY; pass --brief <file> or pipe the brief on stdin");
  }
  let stdin = "";
  try {
    stdin = readFileSync(0, "utf8");
  } catch {
    stdin = "";
  }
  return stdin;
}

function piBinary() {
  const explicit = process.env.PI_BIN;
  if (explicit) return explicit;
  const home = process.env.HOME || "";
  const homeCandidate = join(home, ".local", "bin", "pi");
  if (existsSync(homeCandidate)) return homeCandidate;
  return "pi"; // PATH fallback
}

function piVersion(bin, timeoutMs) {
  try {
    const out = execFileSync(bin, ["--version"], {
      encoding: "utf8",
      timeout: Math.min(timeoutMs, VERSION_PROBE_TIMEOUT_MS),
      killSignal: "SIGKILL",
    }).trim();
    return { version: out || "unknown", error: null };
  } catch (error) {
    if (error?.code === "ENOENT") return { version: null, error: null };
    return { version: null, error };
  }
}

function gitTouchedFiles(cwd) {
  try {
    const output = execFileSync("git", ["status", "--porcelain"], {
      cwd,
      encoding: "utf8",
      timeout: 10_000,
      killSignal: "SIGKILL",
      stdio: ["ignore", "pipe", "ignore"],
      maxBuffer: 64 * 1024 * 1024,
    });
    return output.split("\n").map((line) => line.trimEnd()).filter(Boolean);
  } catch {
    return null;
  }
}

function timestamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function buildArgv(opts, extensionRoot, promptFile) {
  // Deterministic extension loading: -ne disables implicit discovery; the
  // explicit -e still loads under it. Skills discovery is left enabled.
  const argv = ["--mode", "json", "-p", "--no-extensions"];
  if (extensionRoot) argv.push("-e", extensionRoot);
  argv.push("--tools", (opts.write ? WRITE_TOOLS : READ_ONLY_TOOLS).join(","));
  if (opts.model) argv.push("--model", opts.model);
  argv.push("--thinking", opts.thinking);
  if (opts.session) {
    argv.push("--session-id", opts.session);
  } else {
    // Fresh logical session ids are the caller's choice; without one Pi mints
    // its own, which the relay reports from the session event.
  }
  argv.push("--", `@${promptFile}`);
  return argv;
}

function prepareRunDir(opts, brief) {
  const startedAt = new Date().toISOString();
  const outDir = opts.outDir
    || join(tmpdir(), "pi-relay", `${basename(opts.cd) || "repo"}-${timestamp()}`);
  mkdirSync(outDir, { recursive: true });
  const run = {
    startedAt,
    briefPath: join(outDir, "brief.txt"),
    finalPath: join(outDir, "final.txt"),
    eventsPath: join(outDir, "events.jsonl"),
    stderrPath: join(outDir, "stderr.txt"),
    resultPath: join(outDir, "result.json"),
  };
  rmSync(run.finalPath, { force: true });
  rmSync(run.resultPath, { force: true });
  writeFileSync(run.briefPath, brief, "utf8");
  writeFileSync(run.eventsPath, "", "utf8");
  writeFileSync(run.stderrPath, "", "utf8");
  return run;
}

function makeResultWriter(opts, version, run) {
  return (extra) => {
    const result = {
      schema: "delegate-relay.result.v1",
      tool: "pi",
      piVersion: version,
      cwd: opts.cd,
      mode: opts.write ? "write" : "read-only",
      requestedModel: opts.model,
      thinking: opts.thinking,
      resumed: Boolean(opts.session),
      startedAt: run.startedAt,
      finishedAt: new Date().toISOString(),
      briefPath: run.briefPath,
      finalPath: existsSync(run.finalPath) ? run.finalPath : null,
      eventsPath: run.eventsPath,
      stderrPath: run.stderrPath,
      ...extra,
    };
    const temporary = `${run.resultPath}.${process.pid}.tmp`;
    writeFileSync(temporary, `${JSON.stringify(result, null, 2)}\n`, "utf8");
    renameSync(temporary, run.resultPath); // atomic publish
    return result;
  };
}

/**
 * Incremental NDJSON scan of Pi's stdout stream. Tracks:
 *  - sessionId  (session.id, first occurrence)
 *  - resolvedModel (assistant message_end.message.provider/model)
 *  - finalText  (concatenated text parts of the LAST assistant message)
 *  - usage      (last assistant usage object)
 *  - settled    (agent_settled seen)
 *  - stopReason (last observed stopReason)
 */
function makePiEventScanner() {
  let buf = "";
  const state = {
    sessionId: null,
    sessionCwd: null,
    resolvedProvider: null,
    resolvedModel: null,
    finalText: null,
    usage: null,
    settled: false,
    stopReason: null,
    retryCount: 0,
  };
  const handle = (event) => {
    if (!event || typeof event !== "object") return;
    switch (event.type) {
      case "session":
        if (typeof event.id === "string" && !state.sessionId) state.sessionId = event.id;
        if (typeof event.cwd === "string" && !state.sessionCwd) state.sessionCwd = event.cwd;
        break;
      case "model_change":
        if (typeof event.provider === "string") state.resolvedProvider = event.provider;
        if (typeof event.modelId === "string") state.resolvedModel = event.modelId;
        break;
      case "message_end": {
        const message = event.message;
        if (message && typeof message === "object" && message.role === "assistant") {
          if (typeof message.provider === "string") state.resolvedProvider = message.provider;
          if (typeof message.model === "string") state.resolvedModel = message.model;
          if (message.usage && typeof message.usage === "object") state.usage = message.usage;
          if (typeof message.stopReason === "string") state.stopReason = message.stopReason;
          if (Array.isArray(message.content)) {
            const texts = [];
            for (const part of message.content) {
              if (part && typeof part === "object" && part.type === "text" && typeof part.text === "string") {
                texts.push(part.text);
              }
            }
            if (texts.length) state.finalText = texts.join("\n\n");
          }
        }
        break;
      }
      case "auto_retry_start":
        state.retryCount += 1;
        break;
      case "agent_settled":
        state.settled = true;
        break;
      default:
        break;
    }
  };
  return {
    state,
    push(chunk) {
      buf += chunk;
      let index;
      while ((index = buf.indexOf("\n")) !== -1) {
        const line = buf.slice(0, index).trim();
        buf = buf.slice(index + 1);
        if (!line) continue;
        try {
          handle(JSON.parse(line));
        } catch {
          /* skip malformed line */
        }
      }
    },
  };
}

function killChild(child, signal = "SIGTERM") {
  if (!child || !child.pid) return;
  try {
    process.kill(-child.pid, signal);
  } catch {
    try {
      child.kill(signal);
    } catch {
      /* the process group already exited */
    }
  }
}

function assembleFinalText(state) {
  return state.finalText && state.finalText.trim() ? state.finalText : "";
}

function printSummary(result, resultPath) {
  const lines = [];
  lines.push("");
  lines.push(`relay: ${result.status} (exit ${result.exitCode}${result.signal ? `, killed by ${result.signal}` : ""})  ·  pi ${result.piVersion ?? "?"}`);
  if (result.resumed) lines.push("mode: resumed an exact session");
  lines.push(`mode: ${result.mode} (tools ${result.mode === "write" ? "read,grep,find,ls,bash,edit,write,delegate_agent" : "read,grep,find,ls,delegate_agent"})`);
  if (result.resolvedModel) {
    lines.push(`model: ${result.resolvedModel}  ·  thinking: ${result.thinking}`);
  }
  if (result.sessionId) lines.push(`session id (resume with: --session ${result.sessionId}): ${result.sessionId}`);
  const touched = result.touchedFiles;
  if (touched === null) {
    lines.push("touched files: git unavailable — inspect the working tree directly");
  } else {
    lines.push(`touched files: ${touched.length}`);
    for (const file of touched.slice(0, 40)) lines.push(`  ${file}`);
    if (touched.length > 40) lines.push(`  ... and ${touched.length - 40} more`);
  }
  if (result.stderrTail && result.stderrTail.length) {
    lines.push("last stderr:");
    for (const line of result.stderrTail.slice(-8)) lines.push(`  ${line}`);
  }
  lines.push("");
  lines.push("--- pi final report ---");
  lines.push(result.finalMessage || "(no final message captured)");
  lines.push("--- end report ---");
  lines.push("");
  lines.push(`result: ${resultPath}`);
  lines.push("relay does not commit. Review the diff, re-run the project gates yourself, then commit from the orchestrator.");
  process.stdout.write(`${lines.join("\n")}\n`);
}

function dispatchToPi(opts, brief, run, writeResult, bin) {
  const extensionRoot = delegateAgentRoot();
  if (!extensionRoot) {
    const result = writeResult({
      status: "failed",
      exitCode: 1,
      signal: null,
      sessionId: opts.session,
      resolvedModel: null,
      finalMessage: "",
      touchedFiles: gitTouchedFiles(opts.cd),
      error: "delegate-agent extension root not found (expected ~/.pi/agent/extensions/delegate-agent or PI_DELEGATE_AGENT_ROOT)",
    });
    printSummary(result, run.resultPath);
    process.exit(1);
  }

  // The brief rides a temp file attached via Pi's `@file` message syntax
  // (`pi [options] [--] [@files...] [messages...]`): argv carries only the fixed
  // flags plus a temp path, never the brief text itself. The file outlives spawn
  // (Pi reads it during startup) and is removed once the child has exited.
  const promptFile = join(dirname(run.briefPath), "prompt-attachment.tmp");
  writeFileSync(promptFile, brief, { encoding: "utf8", mode: 0o600 });
  const argv = buildArgv(opts, extensionRoot, promptFile);
  const child = spawn(bin, argv, { cwd: opts.cd, stdio: ["ignore", "pipe", "pipe"], detached: true });
  const unlinkPrompt = () => { try { unlinkSync(promptFile); } catch { /* already gone */ } };
  child.once("close", unlinkPrompt);
  child.once("error", unlinkPrompt);

  const scanner = makePiEventScanner();
  const stderrTail = [];
  const stderrDecoder = new StringDecoder("utf8");
  const stdoutDecoder = new StringDecoder("utf8");

  child.stdout.on("data", (chunk) => {
    appendFileSync(run.eventsPath, chunk);
    scanner.push(stdoutDecoder.write(chunk));
  });

  child.stderr.on("data", (chunk) => {
    process.stderr.write(chunk);
    appendFileSync(run.stderrPath, chunk);
    for (const line of stderrDecoder.write(chunk).split("\n")) {
      if (line.trim()) stderrTail.push(line.trimEnd());
    }
    while (stderrTail.length > 20) stderrTail.shift();
  });

  const assembleFinal = () => {
    const message = assembleFinalText(scanner.state);
    if (message) writeFileSync(run.finalPath, message, "utf8");
    return message;
  };

  let settled = false;
  let watchdogFired = false;
  let watchdogTimer = null;
  let sigkillTimer = null;
  const timeoutMs = opts.timeout === null ? null : parseDuration(opts.timeout);
  if (timeoutMs !== null) {
    watchdogTimer = setTimeout(() => {
      watchdogFired = true;
      killChild(child);
      sigkillTimer = setTimeout(() => {
        if (!settled) killChild(child, "SIGKILL");
      }, 10_000);
    }, timeoutMs);
  }

  // The relay's own death must still produce a result: without this, a kill from
  // the orchestrator side leaves the pi child running with nothing recording why.
  for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) {
    process.on(sig, () => {
      if (settled) return;
      settled = true;
      clearTimeout(watchdogTimer);
      if (sigkillTimer) clearTimeout(sigkillTimer);
      const abortedFields = {
        status: "aborted",
        exitCode: 128 + (constants.signals[sig] || 15),
        signal: sig,
        sessionId: scanner.state.sessionId || opts.session,
        resolvedModel: scanner.state.resolvedModel,
        resolvedProvider: scanner.state.resolvedProvider,
        finalMessage: assembleFinal(),
        touchedFiles: gitTouchedFiles(opts.cd),
        stderrTail: stderrTail.slice(-20),
        error: `the relay was killed by ${sig}; pi was terminated with it — inspect the working tree before re-dispatching`,
      };
      const result = writeResult(abortedFields);
      printSummary(result, run.resultPath);
      killChild(child);
      setTimeout(() => {
        killChild(child, "SIGKILL");
        const late = gitTouchedFiles(opts.cd);
        writeResult({ ...abortedFields, touchedFiles: late });
        process.exit(result.exitCode);
      }, 2000);
    });
  }

  child.on("error", (err) => {
    if (settled) return;
    settled = true;
    clearTimeout(watchdogTimer);
    if (sigkillTimer) clearTimeout(sigkillTimer);
    const result = writeResult({
      status: "failed",
      exitCode: 1,
      signal: null,
      sessionId: scanner.state.sessionId || opts.session,
      resolvedModel: scanner.state.resolvedModel,
      resolvedProvider: scanner.state.resolvedProvider,
      finalMessage: assembleFinal(),
      touchedFiles: gitTouchedFiles(opts.cd),
      stderrTail: stderrTail.slice(-20),
      error: String(err && err.message ? err.message : err),
    });
    printSummary(result, run.resultPath);
    process.exit(1);
  });

  child.on("close", (code, signal) => {
    if (settled) return;
    settled = true;
    clearTimeout(watchdogTimer);
    if (sigkillTimer) clearTimeout(sigkillTimer);
    if (watchdogFired) killChild(child, "SIGKILL");

    const state = scanner.state;
    const sessionId = state.sessionId || opts.session;
    // Honest resolution: provider + modelId are separate stream fields; only
    // prefix when the resolved model id is not already provider-qualified.
    const resolvedModel = state.resolvedModel
      ? (state.resolvedProvider && !state.resolvedModel.includes("/")
        ? `${state.resolvedProvider}/${state.resolvedModel}`
        : state.resolvedModel)
      : null;
    const mapped = code ?? (constants.signals[signal] ? 128 + constants.signals[signal] : 1);
    // Completion requires process exit + exit 0 + agent_settled + valid session id.
    // A terminal stopReason of 'error' or 'aborted' (same contract as the
    // delegate-agent extension) fails the run even on a zero exit.
    const failedStop = state.stopReason === "error" || state.stopReason === "aborted";
    const succeeded =
      code === 0 && !watchdogFired && !failedStop && state.settled
      && typeof sessionId === "string" && sessionId.length > 0;
    let status;
    if (succeeded) status = "completed";
    else if (watchdogFired) status = "timeout";
    else status = "failed";
    let error = null;
    if (watchdogFired) {
      error = `pi did not finish within --timeout ${opts.timeout}; killed by the relay watchdog`;
    } else if (code !== 0) {
      error = `pi exited with code ${code}`;
    } else if (failedStop) {
      error = `pi reported stopReason "${state.stopReason}" on its final message`;
    } else if (!state.settled) {
      error = "pi exited 0 but agent_settled was never observed in the event stream";
    } else if (!sessionId) {
      error = "pi exited 0 and settled but no valid session id was observed";
    }
    const exitCode = succeeded ? 0 : mapped === 0 ? 1 : mapped;
    const result = writeResult({
      status,
      exitCode,
      signal: signal ?? null,
      sessionId,
      resolvedModel,
      resolvedProvider: state.resolvedProvider || null,
      finalMessage: assembleFinal(),
      touchedFiles: gitTouchedFiles(opts.cd),
      usage: state.usage,
      stopReason: state.stopReason || null,
      autoRetryCount: state.retryCount,
      ...(succeeded ? {} : { stderrTail: stderrTail.slice(-20) }),
      ...(error ? { error } : {}),
    });
    printSummary(result, run.resultPath);
    process.exit(result.exitCode);
  });
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const brief = readBrief(opts);
  if (!brief.trim()) fail("empty brief (pass --brief <file> or pipe the brief on stdin)");

  const bin = piBinary();
  const timeoutMs = opts.timeout === null ? VERSION_PROBE_TIMEOUT_MS : parseDuration(opts.timeout);
  const probe = piVersion(bin, timeoutMs);
  await new Promise((resolve) => setImmediate(resolve));
  const run = prepareRunDir(opts, brief);
  const writeResult = makeResultWriter(opts, probe.version, run);
  if (!probe.version && !probe.error) {
    const result = writeResult({
      status: "pi_unavailable",
      exitCode: 127,
      signal: null,
      sessionId: opts.session,
      resolvedModel: null,
      finalMessage: "",
      touchedFiles: null,
    });
    printSummary(result, run.resultPath);
    process.stderr.write("relay: `pi` not found on PATH. Install it (npm i -g @mariozechner/pi-coding-agent or the earendil-works build) and configure auth.\n");
    process.exit(127);
  }
  if (probe.error) {
    const stderr = String(probe.error?.stderr || "").trim();
    if (stderr) writeFileSync(run.stderrPath, `${stderr}\n`, "utf8");
    const timedOut = probe.error?.code === "ETIMEDOUT";
    const result = writeResult({
      status: timedOut ? "timeout" : "failed",
      exitCode: timedOut ? 124 : Number.isInteger(probe.error?.status) ? probe.error.status : 1,
      signal: null,
      sessionId: opts.session,
      resolvedModel: null,
      finalMessage: "",
      touchedFiles: gitTouchedFiles(opts.cd),
      ...(stderr ? { stderrTail: stderr.split("\n").slice(-20) } : {}),
      error: `pi --version preflight failed${timedOut ? " (timed out)" : ""}; pi was not dispatched`,
    });
    printSummary(result, run.resultPath);
    process.exit(result.exitCode);
  }
  dispatchToPi(opts, brief, run, writeResult, bin);
}

main();
