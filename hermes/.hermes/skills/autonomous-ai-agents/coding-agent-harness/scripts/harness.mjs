#!/usr/bin/env node
/**
 * coding-agent-harness · harness.mjs
 *
 * Consume one coding-agent.job.v1 file and write one coding-agent.result.v1.
 * This is an execution protocol, not a workflow controller. It does not read
 * Kanban, change card state, commit, push, tag, release, or deploy.
 *
 * Usage:
 *   node harness.mjs run --job /absolute/job.json --out-dir /absolute/run-dir
 *
 * Options:
 *   run                 Required subcommand.
 *   --job <file>        Absolute path to a readable Job JSON file.
 *   --out-dir <dir>     Absolute run directory; must not be inside repoRoot.
 *   -h, --help          Show this help.
 *
 * Exit codes:
 *   0   Result status=completed
 *   1   other terminal failure
 *   2   CLI usage / out-dir ownership conflict
 *   75  run_in_progress
 *   124 timed_out
 *   127 unavailable
 *   130 aborted
 */

import {
  accessSync,
  constants as fsConstants,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import { writeStageArtifacts } from "../src/artifacts.mjs";
import { runChecks } from "../src/checks.mjs";
import {
  STAGE_CONTRACTS,
  STAGES,
  STRUCTURED_INPUT_KINDS,
  parseCanonicalArtifact,
  typedError,
  validateJob,
  validatePayload,
  validateResult,
} from "../src/contracts.mjs";
import { createEventWriter } from "../src/events.mjs";
import { assertOutDirOutsideRepo, assertPostflight, captureSnapshot, preflightWorkspace } from "../src/git-workspace.mjs";
import { constants } from "node:os";
import { getActiveAdapterChild } from "../src/active-adapter-child.mjs";
import { runCursorAdapter } from "../src/cursor-adapter.mjs";
import { runPiAdapter } from "../src/pi-adapter.mjs";
import { compileBrief } from "../src/prompts.mjs";
import {
  atomicWriteFile,
  canonicalJson,
  exclusiveWriteFile,
  sha256Text,
} from "../src/util.mjs";

function failUsage(message) {
  process.stderr.write(`harness: ${message}\n`);
  process.exit(2);
}

function headerComment() {
  const src = readFileSync(new URL(import.meta.url), "utf8");
  const match = src.match(/\/\*\*([\s\S]*?)\*\//);
  if (!match) return "harness.mjs — run a coding-agent Job\n";
  return `${match[1].replace(/^\s*\* ?/gm, "").trim()}\n`;
}

function parseArgs(argv) {
  if (argv[0] === "-h" || argv[0] === "--help") {
    process.stdout.write(headerComment());
    process.exit(0);
  }
  if (argv[0] !== "run") failUsage("expected subcommand run --job <abs> --out-dir <abs>");
  const opts = { job: null, outDir: null };
  for (let i = 1; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (value === undefined) failUsage(`${arg} requires a value`);
      i += 1;
      return value;
    };
    if (arg === "--job") opts.job = next();
    else if (arg === "--out-dir") opts.outDir = next();
    else if (arg === "-h" || arg === "--help") {
      process.stdout.write(headerComment());
      process.exit(0);
    } else failUsage(`unknown option: ${arg}`);
  }
  if (!opts.job || !opts.outDir) failUsage("run requires --job and --out-dir");
  if (!isAbsolute(opts.job) || !isAbsolute(opts.outDir)) {
    failUsage("--job and --out-dir must be absolute paths");
  }
  opts.job = resolve(opts.job);
  opts.outDir = resolve(opts.outDir);
  return opts;
}

function exitCodeFor(status, errorKind) {
  if (errorKind === "run_in_progress") return 75;
  if (errorKind === "idempotency_conflict") return 2;
  if (status === "completed") return 0;
  if (status === "unavailable") return 127;
  if (status === "timed_out") return 124;
  if (status === "aborted") return 130;
  return 1;
}

function isoNow() {
  return new Date().toISOString();
}

function emptyWorkspace(repoRoot = "/invalid") {
  return {
    repoRoot,
    branchBefore: "unknown",
    branchAfter: "unknown",
    headBefore: "0".repeat(40),
    headAfter: "0".repeat(40),
    snapshotBeforeSha256: "0".repeat(64),
    snapshotAfterSha256: "0".repeat(64),
  };
}

function resultMatchesCurrentJob(result, job, jobHash) {
  const id = (value) => (typeof value === "string" && value.length > 0 ? value : null);
  const stage = STAGES.includes(job?.stage) ? job.stage : null;
  return result.jobSha256 === jobHash
    && result.jobId === id(job?.jobId)
    && result.idempotencyKey === id(job?.idempotencyKey)
    && result.taskId === id(job?.taskId)
    && result.stage === stage;
}

function remapStructuredInputError(error, index) {
  const raw = error.path || "";
  const suffix = raw === "" || raw === "/" ? "" : (raw.startsWith("/") ? raw : `/${raw}`);
  return typedError(error.kind || "invalid_job", `/inputs/${index}${suffix}`, error.message, error.details);
}

function loadStructuredInputArtifacts(job) {
  const order = ["plan", "plan-review", "implementation"];
  const items = job.inputs
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => STRUCTURED_INPUT_KINDS.includes(item.kind))
    .sort((left, right) => order.indexOf(left.item.kind) - order.indexOf(right.item.kind));
  const payloads = Object.create(null);
  for (const { item, index } of items) {
    let text;
    try {
      text = readFileSync(item.path, "utf8");
    } catch (error) {
      return {
        ok: false,
        error: typedError("invalid_job", `/inputs/${index}/path`, `structured input is not readable: ${item.path}`, {
          message: String(error.message || error),
        }),
      };
    }
    const validated = parseCanonicalArtifact(text, {
      expectedKind: item.kind,
      planPayload: payloads.plan,
    });
    if (!validated.ok) {
      return { ok: false, error: remapStructuredInputError(validated.error, index) };
    }
    payloads[item.kind] = validated.value.payload;
  }
  return { ok: true, value: { planPayload: payloads.plan || null, payloads } };
}

function publishResult(outDir, result) {
  const validated = validateResult(result);
  if (!validated.ok) {
    result.error = {
      kind: result.error?.kind || "adapter_failed",
      message: `result failed runtime validation: ${validated.error.message}`,
      details: { path: validated.error.path, secondary: result.error || null },
    };
    if (result.status === "completed") result.status = "failed";
  }
  atomicWriteFile(join(outDir, "result.json"), canonicalJson(result));
  return result;
}

function printSummary(result, resultPath) {
  const kind = result.error?.kind ? ` ${result.error.kind}` : "";
  process.stdout.write(`harness: ${result.status}${kind}  result: ${resultPath}\n`);
}

function loadExistingResult(outDir) {
  const path = join(outDir, "result.json");
  if (!existsSync(path)) return null;
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8"));
    const validated = validateResult(parsed);
    return validated.ok ? validated.value : null;
  } catch {
    return null;
  }
}

function readJobFile(path) {
  let stat;
  try {
    stat = statSync(path);
  } catch (error) {
    if (error.code === "ENOENT") failUsage(`job file not found: ${path}`);
    failUsage(`job file is not accessible: ${error.message}`);
  }
  if (!stat.isFile()) {
    failUsage(`job path must be a readable regular file: ${path}`);
  }
  try {
    accessSync(path, fsConstants.R_OK);
  } catch (error) {
    failUsage(`job file not readable: ${error.message}`);
  }
  try {
    return readFileSync(path, "utf8");
  } catch (error) {
    failUsage(`job file not readable: ${error.message}`);
  }
}

function isEstablishedRunDirectory(path) {
  try {
    const stat = lstatSync(path);
    return stat.isDirectory() && !stat.isSymbolicLink();
  } catch {
    return false;
  }
}

function isDirectorySymlink(path) {
  try {
    return lstatSync(path).isSymbolicLink() && statSync(path).isDirectory();
  } catch {
    return false;
  }
}

function hasTrustedRepoIdentity(repoRoot) {
  try {
    const snapshot = captureSnapshot(repoRoot);
    return snapshot.ok && snapshot.value.toplevel === realpathSync(repoRoot);
  } catch {
    return false;
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const raw = readJobFile(opts.job);

  let parsedJob = null;
  let parseError = null;
  try {
    parsedJob = JSON.parse(raw);
  } catch (error) {
    parseError = typedError("invalid_job", "", `Job JSON parse failed: ${error.message}`);
  }

  const repoRoot = parsedJob?.workspace?.repoRoot;
  const outDirExists = existsSync(opts.outDir);
  const establishedOutDir = isEstablishedRunDirectory(opts.outDir);
  if (typeof repoRoot === "string" && isAbsolute(repoRoot)) {
    if (existsSync(repoRoot)) {
      const containment = assertOutDirOutsideRepo(opts.outDir, repoRoot);
      if (!containment.ok) {
        failUsage(containment.error.message);
      }
    }
    if (!outDirExists) {
      if (!existsSync(repoRoot) || !hasTrustedRepoIdentity(repoRoot)) {
        failUsage("out-dir must already exist when repository identity cannot be validated");
      }
      try {
        mkdirSync(opts.outDir, { recursive: true });
      } catch (error) {
        failUsage(`unable to create out-dir: ${error.message}`);
      }
    } else if (
      !establishedOutDir
      && (!isDirectorySymlink(opts.outDir) || !hasTrustedRepoIdentity(repoRoot))
    ) {
      failUsage("out-dir must be a directory; symlinks require a validated repository identity");
    }
  } else {
    if (!establishedOutDir) {
      failUsage("out-dir must be an existing non-symlink directory when Job workspace identity is unavailable");
    }
  }

  const startedAt = isoNow();
  const resultPath = join(opts.outDir, "result.json");
  const eventsPath = join(opts.outDir, "events.jsonl");
  const stderrPath = join(opts.outDir, "stderr.log");
  const finalPath = join(opts.outDir, "final.txt");
  const lockPath = join(opts.outDir, "run.lock");
  writeFileSync(stderrPath, "", { flag: "a" });

  const jobHash = parseError ? sha256Text(raw) : sha256Text(canonicalJson(parsedJob));
  const storedHashPath = join(opts.outDir, "job.sha256");
  const storedJobPath = join(opts.outDir, "job.json");
  const existing = loadExistingResult(opts.outDir);
  if (existsSync(storedJobPath) !== existsSync(storedHashPath)) {
    process.stderr.write("harness: incomplete stored Job ownership evidence\n");
    process.exit(2);
  }
  if (existing && existsSync(storedHashPath)) {
    const storedHash = readFileSync(storedHashPath, "utf8").trim();
    if (storedHash === jobHash && resultMatchesCurrentJob(existing, parsedJob, jobHash)) {
      printSummary(existing, resultPath);
      process.exit(exitCodeFor(existing.status, existing.error?.kind));
    }
    process.stderr.write("harness: idempotency_conflict\n");
    process.exit(2);
  }
  if (existing && !existsSync(storedHashPath)) {
    process.stderr.write("harness: existing result without stored job hash\n");
    process.exit(2);
  }

  if (existsSync(lockPath) && !existing) {
    process.stderr.write("harness: run_in_progress\n");
    process.exit(75);
  }

  try {
    exclusiveWriteFile(lockPath, canonicalJson({
      pid: process.pid,
      startedAt,
      jobId: parsedJob && typeof parsedJob === "object" ? parsedJob.jobId ?? null : null,
      jobSha256: jobHash,
      outDir: opts.outDir,
    }));
  } catch (error) {
    if (error.code === "EEXIST") {
      process.stderr.write("harness: run_in_progress\n");
      process.exit(75);
    }
    throw error;
  }

  if (!existsSync(storedJobPath)) {
    atomicWriteFile(storedJobPath, parseError ? raw : canonicalJson(parsedJob));
    atomicWriteFile(storedHashPath, `${jobHash}\n`);
  } else {
    const storedHash = readFileSync(storedHashPath, "utf8").trim();
    if (storedHash !== jobHash) {
      unlinkSync(lockPath);
      process.stderr.write("harness: idempotency_conflict\n");
      process.exit(2);
    }
  }

  const identity = parsedJob && typeof parsedJob === "object" ? parsedJob : {};
  const events = createEventWriter({
    path: eventsPath,
    jobId: identity.jobId ?? null,
    stage: identity.stage ?? null,
  });
  events.append("run_started", { jobSha256: jobHash });
  events.startHeartbeat();

  let finishing = false;
  const finish = (result) => {
    if (finishing) return;
    finishing = true;
    events.append("run_finished", { status: result.status, errorKind: result.error?.kind ?? null });
    events.stopHeartbeat();
    publishResult(opts.outDir, result);
    try { unlinkSync(lockPath); } catch { /* lock may already be gone */ }
    printSummary(result, resultPath);
    process.exit(exitCodeFor(result.status, result.error?.kind));
  };

  let abortRequested = null;
  const abortResult = (sig) => makeFailedResult({
    job: parsedJob,
    jobSha256: jobHash,
    startedAt,
    finishedAt: isoNow(),
    status: "aborted",
    error: typedError("aborted", "/adapter", `the harness was killed by ${sig}`, {
      signal: sig,
      signalNumber: constants.signals[sig],
    }),
    eventsPath,
    stderrPath,
    finalPath,
    adapterRuns: [],
  });
  const killActiveRelay = (group = false) => {
    const child = getActiveAdapterChild();
    if (!child?.pid) return;
    try { child.kill("SIGTERM"); } catch { /* already exited */ }
    if (group) {
      try { process.kill(-child.pid, "SIGTERM"); } catch { /* group may already be gone */ }
    }
  };
  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => {
      if (abortRequested) return;
      abortRequested = sig;
      killActiveRelay(false);
      setTimeout(() => {
        killActiveRelay(true);
        finish(abortResult(sig));
      }, 2000);
    });
  }

  if (parseError) {
    finish(makeFailedResult({
      job: null,
      jobSha256: jobHash,
      startedAt,
      finishedAt: isoNow(),
      status: "failed",
      error: parseError,
      eventsPath,
      stderrPath,
      finalPath,
      adapterRuns: [],
    }));
  }

  const jobResult = validateJob(parsedJob);
  if (!jobResult.ok) {
    finish(makeFailedResult({
      job: parsedJob,
      jobSha256: jobHash,
      startedAt,
      finishedAt: isoNow(),
      status: "failed",
      error: jobResult.error,
      eventsPath,
      stderrPath,
      finalPath,
      adapterRuns: [],
    }));
  }
  const job = jobResult.value;

  const preflight = preflightWorkspace(job, opts.outDir);
  if (!preflight.ok) {
    finish(makeFailedResult({
      job,
      jobSha256: jobHash,
      startedAt,
      finishedAt: isoNow(),
      status: "failed",
      error: preflight.error,
      eventsPath,
      stderrPath,
      finalPath,
      adapterRuns: [],
      workspace: snapshotToResultWorkspace(preflight.value?.snapshot, preflight.value?.snapshot, job.workspace.repoRoot),
    }));
  }

  const before = preflight.value.snapshot;
  const evidencePaths = preflight.value.evidencePaths;
  const structuredInputs = loadStructuredInputArtifacts(job);
  if (!structuredInputs.ok) {
    finish(makeFailedResult({
      job,
      jobSha256: jobHash,
      startedAt,
      finishedAt: isoNow(),
      status: "failed",
      error: structuredInputs.error,
      eventsPath,
      stderrPath,
      finalPath,
      adapterRuns: [],
      workspace: snapshotToResultWorkspace(before, before, job.workspace.repoRoot),
    }));
  }
  const canonicalPlanPayload = structuredInputs.value.planPayload;
  const brief = compileBrief(job, evidencePaths || {});
  writeFileSync(join(opts.outDir, "brief.txt"), brief);

  const adapterContext = {
    job,
    brief,
    outDir: opts.outDir,
    events,
  };
  let adapter;
  try {
    adapter = job.agent.adapter === "cursor"
      ? await runCursorAdapter(adapterContext)
      : await runPiAdapter(adapterContext);
  } catch (error) {
    adapter = {
      status: abortRequested ? "aborted" : "failed",
      sessionId: job.agent.sessionId,
      structuredOutput: null,
      usage: {},
      resolvedModel: null,
      adapterRuns: [],
      error: abortRequested
        ? typedError("aborted", "/adapter", `the harness was killed by ${abortRequested}`)
        : typedError("adapter_failed", "/adapter", String(error.message || error)),
    };
  }

  if (abortRequested) {
    finish(abortResult(abortRequested));
  }

  let afterSnapshot = captureSnapshot(job.workspace.repoRoot);
  let after = afterSnapshot.ok ? afterSnapshot.value : before;
  let secondary = afterSnapshot.ok ? null : afterSnapshot.error;
  let checks = [];
  let artifacts = [];
  let structuredOutput = null;
  let error = adapter.error;
  let status = adapter.status;

  if (!error && adapter.structuredOutput?.payload) {
    const planPayload = job.stage === "implement" ? canonicalPlanPayload : undefined;
    const payloadResult = validatePayload(
      STAGE_CONTRACTS[job.stage].outputKind,
      adapter.structuredOutput.payload,
      { planPayload },
    );
    if (!payloadResult.ok) {
      error = typedError("structured_output_invalid", payloadResult.error.path, payloadResult.error.message);
      status = "failed";
    } else {
      const written = writeStageArtifacts({
        job,
        jobSha256: jobHash,
        sessionId: adapter.sessionId,
        workspace: {
          repoRoot: job.workspace.repoRoot,
          branch: before.branch,
          head: before.head,
          baselineSnapshotSha256: before.sha256,
        },
        outDir: opts.outDir,
      }, payloadResult.value);
      if (!written.ok) {
        error = written.error;
        status = "failed";
      } else {
        artifacts = written.descriptors;
        events.append("artifact_written", { paths: artifacts.map((item) => item.path) });
        structuredOutput = {
          kind: STAGE_CONTRACTS[job.stage].outputKind,
          payload: payloadResult.value,
        };
        if (STAGE_CONTRACTS[job.stage].verificationAllowed) {
          checks = await runChecks(preflight.value.verifiedVerification || job.verification, {
            outDir: opts.outDir,
            cwd: job.workspace.repoRoot,
            events,
          });
          afterSnapshot = captureSnapshot(job.workspace.repoRoot);
          if (afterSnapshot.ok) after = afterSnapshot.value;
          else secondary = afterSnapshot.error;
        }
      }
    }
  } else if (!error && adapter.status === "completed") {
    error = typedError("structured_output_missing", "/structuredOutput", "structured output was null");
    status = "failed";
  }

  const post = assertPostflight(job, before, after);
  let touchedFiles = post.ok ? post.value.touchedFiles : (post.error.details?.touchedFiles || []);
  if (!error && !post.ok) {
    error = post.error;
    status = "failed";
  } else if (!post.ok && error) {
    secondary = post.error;
  }

  if (existsSync(join(opts.outDir, "adapter", "primary", "final.txt"))) {
    writeFileSync(finalPath, readFileSync(join(opts.outDir, "adapter", "primary", "final.txt")));
  } else {
    writeFileSync(finalPath, "");
  }

  const finishedAt = isoNow();
  if (error && status === "completed") status = "failed";
  const result = {
    schema: "coding-agent.result.v1",
    jobId: job.jobId,
    idempotencyKey: job.idempotencyKey,
    jobSha256: jobHash,
    taskId: job.taskId,
    stage: job.stage,
    status: error ? (status === "completed" ? "failed" : status) : "completed",
    adapter: job.agent.adapter,
    resolvedModel: adapter.resolvedModel ?? null,
    sessionId: adapter.sessionId,
    startedAt,
    finishedAt,
    structuredOutput,
    artifacts,
    touchedFiles,
    checks,
    usage: adapter.usage && typeof adapter.usage === "object" ? adapter.usage : {},
    workspace: snapshotToResultWorkspace(before, after, job.workspace.repoRoot),
    error: error
      ? { kind: error.kind, message: error.message, details: { path: error.path, ...(error.details || {}), ...(secondary ? { secondary } : {}) } }
      : null,
    paths: {
      events: eventsPath,
      stderr: stderrPath,
      final: finalPath,
      adapterRuns: adapter.adapterRuns || [],
    },
  };
  if (result.status !== "completed" && result.error === null) {
    result.error = { kind: "adapter_failed", message: "run failed without typed error", details: {} };
  }
  if (result.status !== "completed") {
    // completed requires structuredOutput; failures may null it
  } else if (!result.sessionId) {
    result.status = "failed";
    result.error = { kind: "session_mismatch", message: "completed result missing sessionId", details: {} };
  }
  finish(result);
}

function snapshotToResultWorkspace(before, after, repoRoot) {
  if (!before && !after) return emptyWorkspace(repoRoot);
  const src = after || before;
  return {
    repoRoot,
    branchBefore: before?.branch || src.branch,
    branchAfter: after?.branch || src.branch,
    headBefore: before?.head || src.head,
    headAfter: after?.head || src.head,
    snapshotBeforeSha256: before?.sha256 || "0".repeat(64),
    snapshotAfterSha256: after?.sha256 || before?.sha256 || "0".repeat(64),
  };
}

function makeFailedResult({
  job, jobSha256, startedAt, finishedAt, status, error, eventsPath, stderrPath, finalPath, adapterRuns, workspace,
}) {
  const id = (value) => (typeof value === "string" && value.length > 0 ? value : null);
  const stage = STAGES.includes(job?.stage) ? job.stage : null;
  const repoRoot = typeof job?.workspace?.repoRoot === "string" && job.workspace.repoRoot.startsWith("/")
    ? job.workspace.repoRoot
    : "/invalid";
  return {
    schema: "coding-agent.result.v1",
    jobId: id(job?.jobId),
    idempotencyKey: id(job?.idempotencyKey),
    jobSha256: jobSha256 || "0".repeat(64),
    taskId: id(job?.taskId),
    stage,
    status,
    adapter: job?.agent?.adapter || "pi",
    resolvedModel: null,
    sessionId: id(job?.agent?.sessionId),
    startedAt,
    finishedAt,
    structuredOutput: null,
    artifacts: [],
    touchedFiles: [],
    checks: [],
    usage: {},
    workspace: workspace || emptyWorkspace(repoRoot),
    error: error
      ? { kind: error.kind, message: error.message, details: { path: error.path, ...(error.details || {}) } }
      : { kind: "adapter_failed", message: "failed", details: {} },
    paths: {
      events: eventsPath,
      stderr: stderrPath,
      final: finalPath,
      adapterRuns: adapterRuns || [],
    },
  };
}

main();
