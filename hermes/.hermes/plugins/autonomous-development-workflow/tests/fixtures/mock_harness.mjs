#!/usr/bin/env node
/**
 * Deterministic Coding Agent Harness double for Workflow Controller smoke tests.
 *
 * Rules:
 * 1. Read a real coding-agent.job.v1 document.
 * 2. Return a fixed Result keyed by (stage, businessAttempt, transportRetry).
 * 3. Write canonical Artifact bytes and hash them; never invent hashes.
 * 4. Atomically write result.json and events.jsonl.
 * 5. Honor an explicit crash point.
 * 6. Never parse final.txt / final message as protocol.
 */
import {
  appendFileSync,
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";

const JOB_SCHEMA = "coding-agent.job.v1";
const RESULT_SCHEMA = "coding-agent.result.v1";
const ARTIFACT_SCHEMA = "coding-agent.artifact.v1";
const STAGE_OUTPUT = {
  plan: { kind: "plan", schema: "plan.v1" },
  plan_review: { kind: "plan-review", schema: "plan-review.v1" },
  implement: { kind: "implementation", schema: "implementation.v1" },
  execute_review: { kind: "execute-review", schema: "execute-review.v1" },
  direct_implement: { kind: "direct-implementation", schema: "direct-implementation.v1" },
};

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(2);
}

function sha256Buffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function sha256File(path) {
  return sha256Buffer(readFileSync(path));
}

function canonicalJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function atomicWriteFile(path, contents) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, contents);
  const fd = openSync(temporary, "r");
  try {
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(temporary, path);
}

function parseArgs(argv) {
  const args = { job: null, outDir: null };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "run") continue;
    if (argv[i] === "--job") args.job = argv[++i];
    else if (argv[i] === "--out-dir") args.outDir = argv[++i];
  }
  if (!args.job || !args.outDir) fail("mock harness requires run --job <abs> --out-dir <abs>");
  if (!args.job.startsWith("/") || !args.outDir.startsWith("/")) fail("job and out-dir must be absolute");
  return args;
}

function loadScript() {
  const path = process.env.MOCK_HARNESS_SCRIPT;
  if (!path) return {};
  return JSON.parse(readFileSync(path, "utf8"));
}

function identity(job) {
  const parts = String(job.idempotencyKey || "").split(":");
  const businessAttempt = Number(parts[3] || job.attempt || 1);
  const transportRetry = Number(parts[4] || 0);
  return {
    stage: job.stage,
    businessAttempt,
    transportRetry,
    key: `${job.stage}:${businessAttempt}:${transportRetry}`,
  };
}

function payloadFor(job, spec) {
  const output = STAGE_OUTPUT[job.stage];
  if (job.stage === "plan") {
    return {
      schema: output.schema,
      outcome: spec.outcome || "completed",
      title: "Smoke plan",
      goal: "Deliver the fixture greeting.",
      architecture: "Single module in src/app.txt.",
      techStack: ["text"],
      requirements: [{ id: "R1", text: "Write hello to src/app.txt" }],
      contracts: [{ id: "C1", requirementIds: ["R1"], text: "src/app.txt contains hello" }],
      workPackages: [
        {
          id: "WP1",
          title: "Implement greeting",
          objective: "Write the greeting file",
          dependsOn: [],
          contractIds: ["C1"],
          fileChanges: [{ action: "modify", path: "src/app.txt" }],
          steps: ["Write hello"],
          verificationIds: ["V1"],
        },
      ],
      verification: [
        {
          id: "V1",
          kind: "focused",
          cwd: ".",
          argv: ["node", "-e", "process.exit(0)"],
          expected: "exit 0",
          contractIds: ["C1"],
        },
      ],
      risks: [{ risk: "none", mitigation: "keep the change small" }],
      blockingIssues: [],
    };
  }
  if (job.stage === "plan_review" || job.stage === "execute_review") {
    const review = {
      schema: output.schema,
      verdict: spec.verdict || "approved",
      summary: spec.summary || "Looks good.",
      findings: spec.findings || [],
    };
    if (job.stage === "execute_review") review.acceptanceCoverage = spec.acceptanceCoverage || ["login"];
    return review;
  }
  if (job.stage === "direct_implement") {
    return {
      schema: output.schema,
      outcome: spec.outcome || "completed",
      summary: spec.summary || "Implemented the requirement.",
      residualRisks: spec.residualRisks || [],
      blockingIssues: spec.blockingIssues || [],
    };
  }
  return {
    schema: output.schema,
    outcome: spec.outcome || "completed",
    summary: spec.summary || "Implemented the greeting.",
    completedWorkPackages: ["WP1"],
    deviations: [],
    residualRisks: [],
    blockingIssues: [],
  };
}

function isoNow() {
  return new Date().toISOString().replace(/\.\d+Z$/, "Z");
}

function crash(point, wanted) {
  if (wanted && wanted === point) {
    process.stderr.write(`mock harness crash:${point}\n`);
    process.exit(99);
  }
}

const args = parseArgs(process.argv.slice(2));
const job = JSON.parse(readFileSync(args.job, "utf8"));
if (job.schema !== JOB_SCHEMA) fail(`unknown job schema ${job.schema}`);
if (!STAGE_OUTPUT[job.stage]) fail(`unknown stage ${job.stage}`);
const jobSha256 = sha256File(args.job);
const ident = identity(job);
const script = loadScript();
const spec = script[ident.key] || script.default || {};
const crashPoint = process.env.MOCK_HARNESS_CRASH || spec.crash || null;

mkdirSync(args.outDir, { recursive: true });
const storedJobPath = join(args.outDir, "job.json");
const storedHashPath = join(args.outDir, "job.sha256");
if (existsSync(storedJobPath) !== existsSync(storedHashPath)) {
  fail("harness: incomplete stored Job ownership evidence");
}
const launchLog = process.env.MOCK_HARNESS_LAUNCH_LOG;
if (launchLog) {
  appendFileSync(
    launchLog,
    `${JSON.stringify({ jobId: job.jobId, stage: job.stage, attempt: ident.businessAttempt, retry: ident.transportRetry, outDir: args.outDir })}\n`,
  );
}

crash("before_lock", crashPoint);
atomicWriteFile(
  join(args.outDir, "run.lock"),
  canonicalJson({ pid: process.pid, jobId: job.jobId, jobSha256, outDir: args.outDir }),
);
crash("after_lock", crashPoint);

const output = STAGE_OUTPUT[job.stage];
const status = spec.status || "completed";
let sessionId;
if (Object.prototype.hasOwnProperty.call(spec, "sessionId")) {
  sessionId = spec.sessionId;
} else if (job.agent?.sessionId) {
  sessionId = job.agent.sessionId;
} else {
  sessionId = `sess_${job.stage}_${ident.businessAttempt}`;
}
const startedAt = isoNow();

if (status === "completed" && (job.stage === "implement" || job.stage === "direct_implement") && spec.dirty !== false) {
  const target = join(job.workspace.repoRoot, "src", "app.txt");
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, spec.fileContents || "hello from implementer\n");
}

crash("before_artifact", crashPoint);
const artifacts = [];
let structuredOutput = null;
if (status === "completed") {
  const payload = payloadFor(job, spec);
  const artifactsDir = join(args.outDir, "artifacts");
  mkdirSync(artifactsDir, { recursive: true });
  const artifactPath = join(artifactsDir, `${output.kind}-attempt-${job.attempt}.json`);
  const artifact = {
    schema: ARTIFACT_SCHEMA,
    kind: output.kind,
    job: {
      jobId: job.jobId,
      idempotencyKey: job.idempotencyKey,
      taskId: job.taskId,
      stage: job.stage,
      attempt: job.attempt,
      jobSha256,
    },
    sessionId,
    inputs: job.inputs,
    workspace: {
      repoRoot: job.workspace.repoRoot,
      branch: job.workspace.branch,
      head: job.workspace.expectedHead,
      baselineSnapshotSha256: "0".repeat(64),
    },
    payload,
  };
  const artifactBytes = canonicalJson(artifact);
  atomicWriteFile(artifactPath, artifactBytes);
  artifacts.push({
    kind: output.kind,
    path: artifactPath,
    sha256: sha256File(artifactPath),
    schema: ARTIFACT_SCHEMA,
    canonical: true,
  });
  structuredOutput = { kind: output.kind, payload };
}

crash("before_result", crashPoint);
function boundChecks(checkStatus) {
  const verification = Array.isArray(job.verification) ? job.verification : [];
  const checksDir = join(args.outDir, "checks");
  mkdirSync(checksDir, { recursive: true });
  const finishedAt = isoNow();
  return verification.map((item) => {
    const safeId = String(item.id ?? "check").replace(/[^A-Za-z0-9._-]+/g, "-");
    const stdoutPath = join(checksDir, `${safeId}.stdout.log`);
    const stderrPath = join(checksDir, `${safeId}.stderr.log`);
    writeFileSync(stdoutPath, "");
    writeFileSync(stderrPath, "");
    const expected = item.expectedExitCode;
    let exitCode = expected;
    let signal = null;
    if (checkStatus === "failed") {
      exitCode = expected === 0 ? 1 : 0;
    } else if (checkStatus === "timed_out") {
      exitCode = null;
      signal = "SIGTERM";
    } else if (checkStatus === "unavailable") {
      exitCode = null;
    }
    return {
      id: item.id,
      status: checkStatus,
      argv: Array.isArray(item.argv) ? item.argv : [],
      cwd: item.cwd,
      expectedExitCode: expected,
      exitCode,
      signal,
      startedAt,
      finishedAt,
      stdoutPath,
      stderrPath,
    };
  });
}
const checks = job.stage === "implement" || job.stage === "direct_implement"
  ? boundChecks(spec.checks === "failed" ? "failed" : "passed")
  : [];

const result = {
  schema: RESULT_SCHEMA,
  jobId: job.jobId,
  idempotencyKey: job.idempotencyKey,
  jobSha256,
  taskId: job.taskId,
  stage: job.stage,
  status,
  adapter: job.agent?.adapter || "pi",
  sessionId,
  startedAt,
  finishedAt: isoNow(),
  structuredOutput,
  artifacts,
  touchedFiles: job.stage === "implement" || job.stage === "direct_implement" ? ["src/app.txt"] : [],
  checks,
  usage: {},
  workspace: {
    repoRoot: job.workspace.repoRoot,
    branchBefore: job.workspace.branch,
    branchAfter: job.workspace.branch,
    headBefore: job.workspace.expectedHead,
    headAfter: job.workspace.expectedHead,
    snapshotBeforeSha256: "c".repeat(64),
    snapshotAfterSha256: "d".repeat(64),
  },
  error: status === "completed" ? null : { code: status, message: spec.error || status },
  paths: {
    events: join(args.outDir, "events.jsonl"),
    stderr: join(args.outDir, "stderr.log"),
    final: join(args.outDir, "final.txt"),
    adapterRuns: [],
  },
};

const finalText = spec.finalText || (status === "completed" ? "done\n" : `${status}\n`);
atomicWriteFile(result.paths.final, finalText);
atomicWriteFile(result.paths.stderr, "");
atomicWriteFile(
  result.paths.events,
  `${JSON.stringify({ schema: "coding-agent.event.v1", type: "run.started", jobId: job.jobId })}\n` +
    `${JSON.stringify({ schema: "coding-agent.event.v1", type: "run.finished", jobId: job.jobId, status })}\n`,
);
crash("before_result_write", crashPoint);
atomicWriteFile(join(args.outDir, "result.json"), canonicalJson(result));
crash("after_result", crashPoint);
process.exit(status === "completed" ? 0 : 1);
