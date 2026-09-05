#!/usr/bin/env node
/**
 * opencode-delegate · relay.mjs
 *
 * Dispatch a brief to `opencode run`, capture JSON events, export the finished
 * session, and publish delegate-relay.result.v1 artifacts.
 *
 * Fresh runs default to read-only: OpenCode's plan agent plus process-level
 * deny rules for edit, bash, and external-directory access. `--write` is an
 * explicit writable transition and passes `--auto`; it is not an OS sandbox.
 * The relay never commits.
 *
 * Usage:
 *   node relay.mjs --brief <file> [options]
 *   cat brief.txt | node relay.mjs [options]
 *
 * Options:
 *   --brief <file>       Brief path; omit to read stdin.
 *   --cd <dir>           OpenCode working root (default: current directory).
 *   --read-only          Plan agent + edit/bash/external-directory denies (default).
 *   --write              Build agent + --auto; explicit writable mode.
 *   --model <id>         Outer model in provider/model form.
 *   --variant <level>    Provider-specific reasoning variant.
 *   --agent <name>       Primary agent override (default: plan or build).
 *   --session <id>       Resume one exact OpenCode session.
 *   --resume-last        Resume the latest session when no exact id exists.
 *   --timeout <dur>      Optional relay watchdog (h/m/s; default: off).
 *   --out-dir <dir>      Artifact directory (default: system temp).
 *   -h, --help           Show this help.
 */

import { constants, tmpdir } from 'node:os';
import { spawn, execFileSync } from 'node:child_process';
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { StringDecoder } from 'node:string_decoder';

const VERSION_PROBE_TIMEOUT_MS = 10_000;
const EXPORT_TIMEOUT_MS = 30_000;
const MAX_TIMER_MS = 2_147_483_647;
const SAFE_MODEL = /^[A-Za-z0-9][A-Za-z0-9._:/-]*$/;
const SAFE_TOKEN = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;

function fail(message, code = 2) {
  process.stderr.write(`relay: ${message}\n`);
  process.exit(code);
}

function headerComment() {
  const src = readFileSync(new URL(import.meta.url), 'utf8');
  const match = src.match(/\/\*\*([\s\S]*?)\*\//);
  return match ? `${match[1].replace(/^\s*\* ?/gm, '').trim()}\n` : 'relay.mjs — dispatch a brief to opencode run\n';
}

function parseDuration(value) {
  const match = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/.exec(value);
  if (!match || (!match[1] && !match[2] && !match[3])) return null;
  try {
    const seconds = BigInt(match[1] || 0) * 3600n + BigInt(match[2] || 0) * 60n + BigInt(match[3] || 0);
    const milliseconds = seconds * 1000n;
    if (milliseconds <= 0n || milliseconds > BigInt(MAX_TIMER_MS)) return null;
    return Number(milliseconds);
  } catch {
    return null;
  }
}

function parseArgs(argv) {
  const opts = {
    brief: null,
    cd: process.cwd(),
    readOnly: true,
    model: null,
    variant: null,
    agent: null,
    session: null,
    resumeLast: false,
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
      case '-h':
      case '--help':
        process.stdout.write(headerComment());
        process.exit(0);
        break;
      case '--brief': opts.brief = next(); break;
      case '--cd': opts.cd = resolve(next()); break;
      case '--read-only': opts.readOnly = true; break;
      case '--write': opts.readOnly = false; break;
      case '--model': opts.model = next(); break;
      case '--variant': opts.variant = next(); break;
      case '--agent': opts.agent = next(); break;
      case '--session': opts.session = next(); break;
      case '--resume-last': opts.resumeLast = true; break;
      case '--timeout': opts.timeout = next(); break;
      case '--out-dir': opts.outDir = resolve(next()); break;
      default: fail(`unknown option: ${arg}`);
    }
  }
  if (opts.session && opts.resumeLast) fail('--session and --resume-last are mutually exclusive; pass only one');
  if (opts.model && !SAFE_MODEL.test(opts.model)) fail('--model must be a shell-safe provider/model identifier');
  for (const [flag, value] of [['--variant', opts.variant], ['--agent', opts.agent], ['--session', opts.session]]) {
    if (value && !SAFE_TOKEN.test(value)) fail(`${flag} contains unsupported characters`);
  }
  if (opts.timeout !== null && parseDuration(opts.timeout) === null) {
    fail(`--timeout "${opts.timeout}" is invalid or too long; use a positive h/m/s duration`);
  }
  return opts;
}

function readBrief(opts) {
  if (opts.brief) {
    if (!existsSync(opts.brief)) fail(`brief file not found: ${opts.brief}`);
    return readFileSync(opts.brief, 'utf8');
  }
  if (process.stdin.isTTY) fail('no --brief given and stdin is a TTY; pass --brief <file> or pipe stdin');
  try {
    return readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

function timestamp() {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

function prepareRunDir(opts, brief) {
  const outDir = opts.outDir || join(tmpdir(), 'delegate-relay', `${basename(opts.cd) || 'repo'}-${timestamp()}`);
  mkdirSync(outDir, { recursive: true });
  const run = {
    startedAt: new Date().toISOString(),
    briefPath: join(outDir, 'brief.txt'),
    eventsPath: join(outDir, 'events.jsonl'),
    finalPath: join(outDir, 'final.txt'),
    stderrPath: join(outDir, 'stderr.txt'),
    exportPath: join(outDir, 'session.json'),
    resultPath: join(outDir, 'result.json'),
  };
  for (const path of [run.finalPath, run.exportPath, run.resultPath]) rmSync(path, { force: true });
  writeFileSync(run.briefPath, brief, 'utf8');
  writeFileSync(run.eventsPath, '', 'utf8');
  writeFileSync(run.stderrPath, '', 'utf8');
  return run;
}

function gitTouchedFiles(cwd) {
  try {
    const output = execFileSync('git', ['status', '--porcelain'], {
      cwd,
      encoding: 'utf8',
      timeout: 10_000,
      killSignal: 'SIGKILL',
      stdio: ['ignore', 'pipe', 'ignore'],
      maxBuffer: 64 * 1024 * 1024,
    });
    return output.split('\n').map((line) => line.trimEnd()).filter(Boolean);
  } catch {
    return null;
  }
}

function opencodeVersion() {
  try {
    const value = execFileSync('opencode', ['--version'], {
      encoding: 'utf8',
      timeout: VERSION_PROBE_TIMEOUT_MS,
      killSignal: 'SIGKILL',
      shell: process.platform === 'win32',
    }).trim();
    return { version: value || 'unknown', error: null };
  } catch (error) {
    if (error?.code === 'ENOENT') return { version: null, error: null };
    if (process.platform === 'win32' && /not recognized as an internal or external command/i.test(String(error?.stderr || ''))) {
      return { version: null, error: null };
    }
    return { version: null, error };
  }
}

function openCodeEnv(opts) {
  const env = { ...process.env };
  if (!opts.readOnly) return env;
  let inherited = {};
  try {
    const parsed = JSON.parse(env.OPENCODE_PERMISSION || '{}');
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) inherited = parsed;
  } catch {
    inherited = {};
  }
  const reviewRelay =
    '/Users/kenan/.hermes/skills/autonomous-ai-agents/cursor-delegate/scripts/review-relay.mjs';
  env.OPENCODE_PERMISSION = JSON.stringify({
    ...inherited,
    edit: 'deny',
    bash: {
      '*': 'deny',
      [`node ${reviewRelay}`]: 'allow',
      [`node ${reviewRelay} *`]: 'allow',
    },
    external_directory: 'deny',
  });
  return env;
}

function buildArgv(opts) {
  const argv = ['run', '--format', 'json', '--agent', opts.agent || (opts.readOnly ? 'plan' : 'build')];
  if (!opts.readOnly) argv.push('--auto');
  if (opts.model) argv.push('--model', opts.model);
  if (opts.variant) argv.push('--variant', opts.variant);
  if (opts.session) argv.push('--session', opts.session);
  else if (opts.resumeLast) argv.push('--continue');
  return argv;
}

function killChild(child, signal = 'SIGTERM') {
  if (!child?.pid) return;
  if (process.platform === 'win32') {
    if (signal !== 'SIGTERM') return;
    try {
      execFileSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: ['ignore', 'ignore', 'ignore'] });
    } catch {
      // Already exited.
    }
    return;
  }
  try {
    process.kill(-child.pid, signal);
  } catch {
    try { child.kill(signal); } catch { /* Already exited. */ }
  }
}

function parseExport(raw) {
  const start = raw.indexOf('{');
  if (start < 0) return null;
  try { return JSON.parse(raw.slice(start)); } catch { return null; }
}

function exportSession(sessionId, cwd, env, run) {
  if (!sessionId) return { data: null, error: null };
  try {
    const raw = execFileSync('opencode', ['export', sessionId], {
      cwd,
      env,
      encoding: 'utf8',
      timeout: EXPORT_TIMEOUT_MS,
      killSignal: 'SIGKILL',
      shell: process.platform === 'win32',
      maxBuffer: 64 * 1024 * 1024,
    });
    const data = parseExport(raw);
    if (!data) return { data: null, error: 'opencode export returned unparseable output' };
    writeFileSync(run.exportPath, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
    return { data, error: null };
  } catch (error) {
    return { data: null, error: `opencode export failed: ${String(error?.message || error)}` };
  }
}

function fieldsFromExport(data) {
  if (!data) return {};
  const messages = Array.isArray(data.messages) ? data.messages : [];
  const assistant = [...messages].reverse().find((item) => item?.info?.role === 'assistant');
  const parts = Array.isArray(assistant?.parts) ? assistant.parts : [];
  const finalMessage = parts.filter((part) => part?.type === 'text' && typeof part.text === 'string').map((part) => part.text).join('\n\n').trim();
  const provider = assistant?.info?.providerID ?? data?.info?.model?.providerID ?? null;
  const model = assistant?.info?.modelID ?? data?.info?.model?.id ?? null;
  return {
    finalMessage,
    resolvedModel: provider && model ? `${provider}/${model}` : model,
    resolvedVariant: data?.info?.model?.variant ?? null,
    resolvedAgent: assistant?.info?.agent ?? data?.info?.agent ?? null,
    usage: assistant?.info?.tokens ? { tokens: assistant.info.tokens, cost: assistant.info.cost ?? null } : null,
  };
}

function makeResultWriter(opts, version, run) {
  return (extra) => {
    const result = {
      schema: 'delegate-relay.result.v1',
      tool: 'opencode',
      workdir: opts.cd,
      readOnly: opts.readOnly,
      permissionMode: opts.readOnly ? 'read-only' : 'writable-auto',
      requestedModel: opts.model,
      requestedVariant: opts.variant,
      requestedAgent: opts.agent,
      effectiveAgent: opts.agent || (opts.readOnly ? 'plan' : 'build'),
      session: opts.session,
      resumeLast: opts.resumeLast,
      resumed: Boolean(opts.session || opts.resumeLast),
      pure: false,
      opencodeVersion: version,
      startedAt: run.startedAt,
      finishedAt: new Date().toISOString(),
      briefPath: run.briefPath,
      eventsPath: run.eventsPath,
      finalPath: existsSync(run.finalPath) ? run.finalPath : null,
      stderrPath: run.stderrPath,
      exportPath: existsSync(run.exportPath) ? run.exportPath : null,
      ...extra,
    };
    const temporary = `${run.resultPath}.${process.pid}.tmp`;
    writeFileSync(temporary, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    renameSync(temporary, run.resultPath);
    return result;
  };
}

function printSummary(result, resultPath) {
  const lines = [
    '',
    `relay: ${result.status} (exit ${result.exitCode}${result.signal ? `, killed by ${result.signal}` : ''})  ·  opencode ${result.opencodeVersion ?? '?'}`,
    `mode: ${result.permissionMode}  ·  agent: ${result.resolvedAgent || result.effectiveAgent}`,
  ];
  if (result.resolvedModel || result.requestedModel) lines.push(`model: ${result.resolvedModel || result.requestedModel}`);
  if (result.sessionId) lines.push(`session id (resume with: --session ${result.sessionId}): ${result.sessionId}`);
  const touched = result.touchedFiles;
  if (touched === null) lines.push('touched files: git unavailable — inspect the working tree directly');
  else {
    lines.push(`touched files: ${touched.length}`);
    for (const file of touched.slice(0, 40)) lines.push(`  ${file}`);
    if (touched.length > 40) lines.push(`  ... and ${touched.length - 40} more`);
  }
  if (result.stderrTail?.length) {
    lines.push('last stderr:');
    for (const line of result.stderrTail.slice(-8)) lines.push(`  ${line}`);
  }
  if (result.exportError) lines.push(`session export: ${result.exportError}`);
  lines.push('', '--- opencode final report ---', result.finalMessage || '(no final message captured)', '--- end report ---', '', `result: ${resultPath}`);
  process.stdout.write(`${lines.join('\n')}\n`);
}

function dispatch(opts, brief, run, writeResult, env) {
  const argv = buildArgv(opts);
  const child = spawn('opencode', argv, {
    cwd: opts.cd,
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: process.platform === 'win32',
    detached: process.platform !== 'win32',
  });

  let sessionId = null;
  let stdoutBuffer = '';
  let eventFinal = '';
  let eventError = null;
  let eventUsage = null;
  const stderrTail = [];
  const stdoutDecoder = new StringDecoder('utf8');
  const stderrDecoder = new StringDecoder('utf8');

  const consumeLine = (line) => {
    if (!line.trim()) return;
    appendFileSync(run.eventsPath, `${line}\n`, 'utf8');
    try {
      const event = JSON.parse(line);
      if (typeof event.sessionID === 'string') sessionId = event.sessionID;
      if (event.type === 'text' && typeof event?.part?.text === 'string') eventFinal = event.part.text;
      if (event.type === 'step_finish') eventUsage = { tokens: event?.part?.tokens ?? null, cost: event?.part?.cost ?? null };
      if (event.type === 'error') eventError = event.error || event;
      if (event.type === 'tool_use' && event?.part?.state?.status === 'error') eventError = event.part.state.error || 'OpenCode tool failed';
    } catch {
      // Preserve non-JSON output in the event log; OpenCode's exit code owns failure.
    }
  };

  child.stdout.on('data', (chunk) => {
    stdoutBuffer += stdoutDecoder.write(chunk);
    let newline;
    while ((newline = stdoutBuffer.indexOf('\n')) !== -1) {
      consumeLine(stdoutBuffer.slice(0, newline));
      stdoutBuffer = stdoutBuffer.slice(newline + 1);
    }
  });
  child.stderr.on('data', (chunk) => {
    appendFileSync(run.stderrPath, chunk);
    process.stderr.write(chunk);
    for (const line of stderrDecoder.write(chunk).split('\n')) if (line.trim()) stderrTail.push(line.trimEnd());
    while (stderrTail.length > 20) stderrTail.shift();
  });
  child.stdin.on('error', () => {});
  child.stdin.write(brief);
  child.stdin.end();

  let settled = false;
  let watchdogFired = false;
  let watchdogTimer = null;
  let killTimer = null;
  const timeoutMs = opts.timeout === null ? null : parseDuration(opts.timeout);
  if (timeoutMs !== null) {
    watchdogTimer = setTimeout(() => {
      watchdogFired = true;
      killChild(child);
      killTimer = setTimeout(() => { if (!settled) killChild(child, 'SIGKILL'); }, 10_000);
    }, timeoutMs);
  }
  const clearTimers = () => {
    if (watchdogTimer) clearTimeout(watchdogTimer);
    if (killTimer) clearTimeout(killTimer);
  };

  const finalizeFields = (base) => {
    if (stdoutBuffer.trim()) consumeLine(stdoutBuffer);
    const exported = exportSession(sessionId, opts.cd, env, run);
    const resolved = fieldsFromExport(exported.data);
    const finalMessage = resolved.finalMessage || eventFinal || '';
    if (finalMessage) writeFileSync(run.finalPath, finalMessage, 'utf8');
    return {
      ...base,
      sessionId,
      resolvedModel: resolved.resolvedModel ?? null,
      resolvedVariant: resolved.resolvedVariant ?? null,
      resolvedAgent: resolved.resolvedAgent ?? null,
      usage: resolved.usage ?? eventUsage,
      finalMessage,
      touchedFiles: gitTouchedFiles(opts.cd),
      ...(exported.error ? { exportError: exported.error } : {}),
    };
  };

  for (const sig of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
    process.on(sig, () => {
      if (settled) return;
      settled = true;
      clearTimers();
      killChild(child);
      const result = writeResult(finalizeFields({
        status: 'aborted',
        exitCode: 128 + (constants.signals[sig] || 15),
        signal: sig,
        stderrTail: stderrTail.slice(-20),
        error: `the relay was killed by ${sig}; OpenCode was terminated with it — inspect the working tree before re-dispatching`,
      }));
      printSummary(result, run.resultPath);
      setTimeout(() => {
        killChild(child, 'SIGKILL');
        writeResult({ ...result, touchedFiles: gitTouchedFiles(opts.cd), finishedAt: new Date().toISOString() });
        process.exit(result.exitCode);
      }, 2000);
    });
  }

  child.on('error', (error) => {
    if (settled) return;
    settled = true;
    clearTimers();
    const result = writeResult(finalizeFields({
      status: 'failed',
      exitCode: 1,
      signal: null,
      stderrTail: stderrTail.slice(-20),
      error: String(error?.message || error),
    }));
    printSummary(result, run.resultPath);
    process.exit(1);
  });

  child.on('close', (code, signal) => {
    if (settled) return;
    settled = true;
    clearTimers();
    if (watchdogFired) killChild(child, 'SIGKILL');
    const succeeded = code === 0 && !watchdogFired && !eventError;
    const mapped = code ?? (constants.signals[signal] ? 128 + constants.signals[signal] : 1);
    const result = writeResult(finalizeFields({
      status: succeeded ? 'completed' : watchdogFired ? 'timeout' : 'failed',
      exitCode: succeeded ? 0 : mapped === 0 ? 1 : mapped,
      signal: signal ?? null,
      ...(!succeeded ? { stderrTail: stderrTail.slice(-20) } : {}),
      ...(watchdogFired ? { error: `opencode did not finish within --timeout ${opts.timeout}; killed by the relay watchdog` } : {}),
      ...(eventError && !watchdogFired ? { error: typeof eventError === 'string' ? eventError : JSON.stringify(eventError) } : {}),
    }));
    printSummary(result, run.resultPath);
    process.exit(result.exitCode);
  });
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  const brief = readBrief(opts);
  if (!brief.trim()) fail('empty brief (pass --brief <file> or pipe stdin)');
  const run = prepareRunDir(opts, brief);
  const probe = opencodeVersion();
  const writeResult = makeResultWriter(opts, probe.version, run);
  if (!probe.version && !probe.error) {
    const result = writeResult({
      status: 'opencode_unavailable',
      exitCode: 127,
      signal: null,
      sessionId: null,
      resolvedModel: null,
      resolvedVariant: null,
      resolvedAgent: null,
      usage: null,
      finalMessage: '',
      touchedFiles: null,
    });
    printSummary(result, run.resultPath);
    process.stderr.write('relay: `opencode` not found on PATH. Install it and run `opencode auth login` when a provider requires credentials.\n');
    process.exit(127);
  }
  if (probe.error) {
    const timedOut = probe.error?.code === 'ETIMEDOUT';
    const result = writeResult({
      status: timedOut ? 'timeout' : 'failed',
      exitCode: timedOut ? 124 : Number.isInteger(probe.error?.status) ? probe.error.status : 1,
      signal: null,
      sessionId: null,
      resolvedModel: null,
      resolvedVariant: null,
      resolvedAgent: null,
      usage: null,
      finalMessage: '',
      touchedFiles: gitTouchedFiles(opts.cd),
      error: `opencode --version preflight ${timedOut ? 'timed out' : 'failed'}; OpenCode was not dispatched`,
    });
    printSummary(result, run.resultPath);
    process.exit(result.exitCode);
  }
  dispatch(opts, brief, run, writeResult, openCodeEnv(opts));
}

main();
