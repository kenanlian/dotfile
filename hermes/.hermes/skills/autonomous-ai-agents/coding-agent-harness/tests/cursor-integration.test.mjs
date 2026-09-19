import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import {
  chmodSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { writeStageArtifacts } from "../src/artifacts.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const HARNESS = join(ROOT, "scripts", "harness.mjs");
const STUB = join(ROOT, "tests", "fixtures", "stub-cursor-agent.mjs");
const FIXTURE_REPO = join(ROOT, "tests", "fixtures", "repo");
const JOBS = join(ROOT, "tests", "fixtures", "jobs");
const DEFAULT_SESSION = "cursor-stub-session-1";
const GREET_FIXED = "export function greet(name) { return `Hello, ${name}`; }\n";

function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function git(cwd, args) {
  return spawnSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
}

function flagValue(argv, flag) {
  const index = argv.indexOf(flag);
  return index === -1 ? undefined : argv[index + 1];
}

function planPayload() {
  return {
    schema: "plan.v1",
    outcome: "completed",
    title: "Greet helper",
    goal: "Add a greet function",
    architecture: "Single module plus unit test",
    techStack: ["Node.js"],
    requirements: [{ id: "R1", text: "greet returns a greeting" }],
    contracts: [{ id: "C1", requirementIds: ["R1"], text: "greet(name) returns Hello, name" }],
    workPackages: [{
      id: "WP-01",
      title: "Implement greet",
      objective: "Add greet and a test",
      dependsOn: [],
      contractIds: ["C1"],
      fileChanges: [{ action: "modify", path: "src/greet.mjs" }],
      steps: ["Write greet", "Write test"],
      verificationIds: ["V1"],
    }],
    verification: [{
      id: "V1",
      kind: "focused",
      cwd: ".",
      argv: ["node", "--test", "test/greet.test.mjs"],
      expected: "tests pass",
      contractIds: ["C1"],
    }],
    risks: [{ risk: "none material", mitigation: "keep scope tiny" }],
    blockingIssues: [],
  };
}

function implementationPayload() {
  return {
    schema: "implementation.v1",
    outcome: "completed",
    summary: "done",
    completedWorkPackages: ["WP-01"],
    deviations: [],
    residualRisks: [],
    blockingIssues: [],
  };
}

function writeCanonicalArtifact(world, { stage, payload, extraInputs = [] }) {
  const outDir = mkdtempSync(join(world.tmp, `${stage}-artifact-`));
  const written = writeStageArtifacts({
    job: {
      jobId: `job_${stage}`,
      idempotencyKey: `task_fixture:${stage}:1`,
      taskId: "task_fixture",
      stage,
      attempt: 1,
      inputs: [
        { kind: "requirement", path: world.requirementPath, sha256: world.requirementSha },
        ...extraInputs,
      ],
    },
    jobSha256: "c".repeat(64),
    sessionId: "sess-canonical",
    workspace: {
      repoRoot: world.repoRoot,
      branch: "main",
      head: world.head,
      baselineSnapshotSha256: "d".repeat(64),
    },
    outDir,
  }, payload);
  assert.equal(written.ok, true, written.error && written.error.message);
  const descriptor = written.descriptors.find((item) => item.canonical);
  return { path: descriptor.path, sha256: descriptor.sha256, artifact: written.artifact, outDir };
}

function writeCanonicalPlan(world) {
  return writeCanonicalArtifact(world, { stage: "plan", payload: planPayload() });
}

function writeCanonicalImplementation(world) {
  return writeCanonicalArtifact(world, { stage: "implement", payload: implementationPayload() });
}

function installStubBin(dir) {
  const stubBin = join(dir, "stub-cursor-agent");
  writeFileSync(
    stubBin,
    `#!/bin/sh\nexec ${JSON.stringify(process.execPath)} ${JSON.stringify(STUB)} "$@"\n`,
    "utf8",
  );
  chmodSync(stubBin, 0o755);
  return stubBin;
}

function setupWorld() {
  const tmp = mkdtempSync(join(tmpdir(), "cursor-int-"));
  const repo = join(tmp, "repo");
  const outRoot = join(tmp, "out");
  mkdirSync(outRoot, { recursive: true });
  cpSync(FIXTURE_REPO, repo, { recursive: true });
  git(repo, ["init", "-b", "main"]);
  git(repo, ["config", "user.email", "test@example.com"]);
  git(repo, ["config", "user.name", "Test"]);
  git(repo, ["add", "."]);
  git(repo, ["commit", "-m", "init"]);
  const repoRoot = realpathSync(repo);
  const head = git(repoRoot, ["rev-parse", "HEAD"]).stdout.trim();
  const requirementPath = join(repoRoot, "requirement.md");
  const stubBin = installStubBin(tmp);
  return {
    tmp, repoRoot, outRoot, head, requirementPath, stubBin,
    requirementSha: sha256File(requirementPath),
    cleanup() { rmSync(tmp, { recursive: true, force: true }); },
  };
}

function materialize(templateName, world, extra = {}) {
  const template = JSON.parse(readFileSync(join(JOBS, templateName), "utf8"));
  const raw = JSON.stringify(template)
    .replaceAll("__REPO_ROOT__", extra.repoRoot || world.repoRoot)
    .replaceAll("__HEAD__", extra.head || world.head)
    .replaceAll("__REQUIREMENT_PATH__", world.requirementPath)
    .replaceAll("__REQUIREMENT_SHA256__", world.requirementSha)
    .replaceAll("__PLAN_PATH__", extra.planPath || "")
    .replaceAll("__PLAN_SHA256__", extra.planSha || "")
    .replaceAll("__IMPLEMENTATION_PATH__", extra.implementationPath || "")
    .replaceAll("__IMPLEMENTATION_SHA256__", extra.implementationSha || "");
  const job = JSON.parse(raw);
  if (extra.sessionId !== undefined) job.agent.sessionId = extra.sessionId;
  if (extra.verification) job.verification = extra.verification;
  if (extra.requireCleanAtStart !== undefined) job.workspace.requireCleanAtStart = extra.requireCleanAtStart;
  if (extra.timeoutSeconds !== undefined) job.limits.timeoutSeconds = extra.timeoutSeconds;
  const jobPath = join(world.tmp, `${templateName.replace(".json", "")}.json`);
  writeFileSync(jobPath, `${JSON.stringify(job, null, 2)}\n`);
  return { job, jobPath };
}

function runHarness(world, jobPath, outDir, envExtra = {}, { createOutDir = true, timeout = 60_000 } = {}) {
  if (createOutDir) mkdirSync(outDir, { recursive: true });
  const dumpPath = join(outDir, "stub-dump.json");
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (key.startsWith("CURSOR_STUB_") || key.startsWith("PI_STUB_")) delete env[key];
  }
  env.CURSOR_AGENT_BIN = world.stubBin;
  env.CURSOR_STUB_DUMP = dumpPath;
  Object.assign(env, envExtra);
  const spawned = spawnSync(process.execPath, [HARNESS, "run", "--job", jobPath, "--out-dir", outDir], {
    env,
    encoding: "utf8",
    timeout,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const resultPath = join(outDir, "result.json");
  const result = existsSync(resultPath) ? JSON.parse(readFileSync(resultPath, "utf8")) : null;
  const dump = existsSync(dumpPath) ? JSON.parse(readFileSync(dumpPath, "utf8")) : null;
  return { spawned, result, dump, dumpPath, resultPath, outDir };
}

function readSpawnRecord(outDir, phase = "primary") {
  const path = join(outDir, "adapter", phase, "spawn-record.json");
  assert.equal(existsSync(path), true, `missing spawn-record at ${path}`);
  return JSON.parse(readFileSync(path, "utf8"));
}

function readEventTypes(outDir) {
  const path = join(outDir, "events.jsonl");
  return readFileSync(path, "utf8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line).type);
}

function assertCursorHappyMeta(run, { write = false } = {}) {
  assert.equal(run.spawned.status, 0, run.spawned.stderr);
  assert.equal(run.result.status, "completed", run.result.error && JSON.stringify(run.result.error));
  assert.equal(run.result.adapter, "cursor");
  assert.equal(typeof run.result.resolvedModel, "string");
  assert.notEqual(run.result.resolvedModel, "");
  const spawn = readSpawnRecord(run.outDir);
  assert.equal(spawn.adapter, "cursor");
  assert.ok(Array.isArray(spawn.argv), "spawn-record argv");
  assert.ok(spawn.argv.includes("--plugin-dir"), spawn.argv.join(" "));
  if (write) {
    assert.ok(spawn.argv.includes("--force"), spawn.argv.join(" "));
    assert.equal(spawn.argv.includes("--mode"), false, spawn.argv.join(" "));
  } else {
    assert.equal(flagValue(spawn.argv, "--mode"), "plan", spawn.argv.join(" "));
    assert.equal(spawn.argv.includes("--force"), false, spawn.argv.join(" "));
  }
  const types = readEventTypes(run.outDir);
  for (const expected of ["agent_session_started", "stage_message", "agent_settled"]) {
    assert.ok(types.includes(expected), `missing ${expected} in ${types.join(",")}`);
  }
}

test("plan: read-only submit_plan produces canonical artifact, plan.md, empty touchedFiles", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "plan"));
    assertCursorHappyMeta(run);
    assert.equal(run.result.structuredOutput.kind, "plan");
    assert.equal(run.result.structuredOutput.payload.title, "Greet helper");
    assert.ok(run.result.artifacts.some((item) => item.canonical && item.path.endsWith(".json")));
    assert.ok(run.result.artifacts.some((item) => item.canonical === false && item.path.endsWith(".md")));
    const md = readFileSync(run.result.artifacts.find((item) => item.path.endsWith(".md")).path, "utf8");
    assert.match(md, /Greet helper/);
    assert.deepEqual(run.result.touchedFiles, []);
    const spawn = readSpawnRecord(run.outDir);
    assert.equal(spawn.expectedTool, "submit_plan");
  } finally {
    world.cleanup();
  }
});

test("plan_review: fresh session, unicode payload, read-only", () => {
  const world = setupWorld();
  try {
    const plan = writeCanonicalPlan(world);
    const payload = {
      schema: "plan-review.v1",
      verdict: "approved",
      summary: 'OK: "quotes", colon: value, 你好\nmultiline',
      findings: [],
    };
    const { job, jobPath } = materialize("cursor-plan-review.job.template.json", world, {
      planPath: plan.path,
      planSha: plan.sha256,
    });
    assert.equal(job.agent.sessionId, null);
    const run = runHarness(world, jobPath, join(world.outRoot, "plan-review"), {
      CURSOR_STUB_PAYLOAD: JSON.stringify(payload),
    });
    assertCursorHappyMeta(run);
    assert.equal(run.result.structuredOutput.payload.summary, payload.summary);
    assert.equal(run.result.structuredOutput.payload.verdict, "approved");
    assert.deepEqual(run.result.touchedFiles, []);
    const spawn = readSpawnRecord(run.outDir);
    assert.equal(spawn.argv.includes("--resume"), false);
    assert.equal(spawn.expectedTool, "submit_plan_review");
  } finally {
    world.cleanup();
  }
});

test("implement: consumes canonical plan, --force, touched files, deterministic check", () => {
  const world = setupWorld();
  try {
    const plan = writeCanonicalPlan(world);
    const { job, jobPath } = materialize("cursor-implement.job.template.json", world, {
      planPath: plan.path,
      planSha: plan.sha256,
    });
    assert.equal(job.inputs.length, 1);
    assert.equal(job.inputs[0].kind, "plan");
    const run = runHarness(world, jobPath, join(world.outRoot, "implement"), {
      CURSOR_STUB_WRITE_RELPATH: "src/greet.mjs",
      CURSOR_STUB_WRITE_CONTENTS: GREET_FIXED,
    });
    assertCursorHappyMeta(run, { write: true });
    assert.equal(run.result.structuredOutput.kind, "implementation");
    assert.ok(run.result.touchedFiles.includes("src/greet.mjs"));
    assert.equal(run.result.checks.find((item) => item.id === "check-unit").status, "passed");
    const spawn = readSpawnRecord(run.outDir);
    assert.equal(spawn.expectedTool, "submit_implementation");
  } finally {
    world.cleanup();
  }
});

test("execute_review: workspace-evidence/candidate-patch, read-only on dirty tree", () => {
  const world = setupWorld();
  try {
    writeFileSync(join(world.repoRoot, "src/greet.mjs"), GREET_FIXED);
    const plan = writeCanonicalPlan(world);
    const impl = writeCanonicalImplementation(world);
    const { jobPath } = materialize("cursor-execute-review.job.template.json", world, {
      planPath: plan.path,
      planSha: plan.sha256,
      implementationPath: impl.path,
      implementationSha: impl.sha256,
    });
    const run = runHarness(world, jobPath, join(world.outRoot, "exec-review"));
    assertCursorHappyMeta(run);
    assert.deepEqual(run.result.touchedFiles, []);
    assert.equal(run.result.workspace.snapshotBeforeSha256, run.result.workspace.snapshotAfterSha256);
    assert.equal(existsSync(join(run.outDir, "derived", "workspace-evidence.json")), true);
    assert.equal(existsSync(join(run.outDir, "derived", "candidate.patch")), true);
    const brief = readFileSync(join(run.outDir, "adapter", "primary", "brief.txt"), "utf8");
    assert.match(brief, /workspace-evidence\.json/);
    assert.match(brief, /candidate\.patch/);
    const spawn = readSpawnRecord(run.outDir);
    assert.equal(spawn.expectedTool, "submit_execute_review");
  } finally {
    world.cleanup();
  }
});

test("direct_implement: --force, fixture modification, verification required", () => {
  const world = setupWorld();
  try {
    const { job, jobPath } = materialize("cursor-direct-implement.job.template.json", world);
    assert.equal(job.stage, "direct_implement");
    assert.ok(job.verification.length >= 1);
    const run = runHarness(world, jobPath, join(world.outRoot, "direct-implement"), {
      CURSOR_STUB_WRITE_RELPATH: "src/greet.mjs",
      CURSOR_STUB_WRITE_CONTENTS: GREET_FIXED,
    });
    assertCursorHappyMeta(run, { write: true });
    assert.equal(run.result.structuredOutput.kind, "direct-implementation");
    assert.equal(run.result.structuredOutput.payload.schema, "direct-implementation.v1");
    assert.ok(run.result.artifacts.some((item) => item.canonical && item.path.includes("direct-implementation")));
    assert.ok(run.result.touchedFiles.includes("src/greet.mjs"));
    assert.equal(run.result.checks.find((item) => item.id === "check-unit").status, "passed");
    const spawn = readSpawnRecord(run.outDir);
    assert.equal(spawn.expectedTool, "submit_direct_implementation");
  } finally {
    world.cleanup();
  }
});

test("missing submit recovers exactly once on the same session then succeeds", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "missing-recover"), {
      CURSOR_STUB_SUPPRESS_SUBMIT_PRIMARY: "1",
    });
    assertCursorHappyMeta(run);
    assert.equal(run.result.paths.adapterRuns.length, 2);
    assert.equal(run.result.paths.adapterRuns[0].phase, "primary");
    assert.equal(run.result.paths.adapterRuns[1].phase, "output-recovery");
    const primary = readSpawnRecord(run.outDir, "primary");
    const recovery = readSpawnRecord(run.outDir, "output-recovery");
    assert.equal(primary.argv.includes("--resume"), false, primary.argv.join(" "));
    assert.equal(flagValue(recovery.argv, "--resume"), DEFAULT_SESSION);
    assert.equal(flagValue(recovery.argv, "--mode"), "plan");
    assert.equal(recovery.argv.includes("--force"), false);
    assert.notEqual(recovery.pluginDir, primary.pluginDir);
    assert.notEqual(recovery.runNonce, primary.runNonce);
    assert.ok(recovery.argv.includes("--plugin-dir"));
    assert.equal(run.result.sessionId, DEFAULT_SESSION);
    assert.equal(run.result.structuredOutput.kind, "plan");
  } finally {
    world.cleanup();
  }
});

test("still-missing after recovery is structured_output_missing", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "still-missing"), {
      CURSOR_STUB_SUPPRESS_SUBMIT: "1",
    });
    assert.notEqual(run.spawned.status, 0, run.spawned.stderr);
    assert.equal(run.result.status, "failed");
    assert.equal(run.result.error.kind, "structured_output_missing");
    assert.equal(run.result.paths.adapterRuns.length, 2);
    const recovery = readSpawnRecord(run.outDir, "output-recovery");
    assert.equal(flagValue(recovery.argv, "--resume"), DEFAULT_SESSION);
  } finally {
    world.cleanup();
  }
});

test("duplicate receipts are structured_output_duplicate with no recovery", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "duplicate"), {
      CURSOR_STUB_DOUBLE_SUBMIT: "1",
    });
    assert.notEqual(run.spawned.status, 0);
    assert.equal(run.result.error.kind, "structured_output_duplicate");
    assert.equal(run.result.paths.adapterRuns.length, 1);
    assert.equal(existsSync(join(run.outDir, "adapter", "output-recovery")), false);
  } finally {
    world.cleanup();
  }
});

test("rejected receipt (bad binding) is structured_output_invalid with no recovery", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "bad-binding"), {
      CURSOR_STUB_BAD_BINDING: "1",
    });
    assert.notEqual(run.spawned.status, 0);
    assert.equal(run.result.error.kind, "structured_output_invalid");
    assert.equal(run.result.paths.adapterRuns.length, 1);
    assert.equal(existsSync(join(run.outDir, "adapter", "output-recovery")), false);
  } finally {
    world.cleanup();
  }
});

test("rejected receipt (bad payload) is structured_output_invalid with no recovery", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "bad-payload"), {
      CURSOR_STUB_BAD_PAYLOAD: "1",
    });
    assert.notEqual(run.spawned.status, 0);
    assert.equal(run.result.error.kind, "structured_output_invalid");
    assert.equal(run.result.paths.adapterRuns.length, 1);
    assert.equal(existsSync(join(run.outDir, "adapter", "output-recovery")), false);
  } finally {
    world.cleanup();
  }
});

test("timeout with sleeping stub is timed_out and is not retried", () => {
  const world = setupWorld();
  try {
    const { job, jobPath } = materialize("cursor-plan.job.template.json", world);
    job.limits.timeoutSeconds = 1;
    writeFileSync(jobPath, `${JSON.stringify(job, null, 2)}\n`);
    const run = runHarness(world, jobPath, join(world.outRoot, "timeout"), {
      CURSOR_STUB_SLEEP_MS: "8000",
    });
    assert.equal(run.result.status, "timed_out");
    assert.equal(run.spawned.status, 124);
    assert.equal(run.result.paths.adapterRuns.length, 1);
  } finally {
    world.cleanup();
  }
});

test("CURSOR_AGENT_BIN=/nonexistent is unavailable", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "unavailable"), {
      CURSOR_AGENT_BIN: "/nonexistent-cursor-agent-bin",
    });
    assert.equal(run.result.status, "unavailable");
    assert.equal(run.spawned.status, 127);
    assert.equal(run.result.paths.adapterRuns.length, 1);
  } finally {
    world.cleanup();
  }
});

test("SIGINT maps to aborted with exit 130", async () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const outDir = join(world.outRoot, "aborted");
    mkdirSync(outDir, { recursive: true });
    const env = { ...process.env };
    for (const key of Object.keys(env)) {
      if (key.startsWith("CURSOR_STUB_") || key.startsWith("PI_STUB_")) delete env[key];
    }
    env.CURSOR_AGENT_BIN = world.stubBin;
    env.CURSOR_STUB_DUMP = join(outDir, "stub-dump.json");
    env.CURSOR_STUB_SLEEP_MS = "20000";
    const child = spawn(process.execPath, [HARNESS, "run", "--job", jobPath, "--out-dir", outDir], {
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const lockPath = join(outDir, "run.lock");
    const deadline = Date.now() + 15_000;
    while (!existsSync(lockPath) && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.equal(existsSync(lockPath), true, "run.lock should exist before abort");
    child.kill("SIGINT");
    const code = await new Promise((resolve) => child.once("exit", (status) => resolve(status)));
    const result = JSON.parse(readFileSync(join(outDir, "result.json"), "utf8"));
    assert.equal(result.status, "aborted");
    assert.equal(result.error.kind, "aborted");
    assert.equal(code, 130);
  } finally {
    world.cleanup();
  }
});

test("plan-stage repo write is read_only_violation", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "bypass"), {
      CURSOR_STUB_WRITE_RELPATH: "hacked.txt",
      CURSOR_STUB_WRITE_CONTENTS: "nope\n",
    });
    assert.equal(run.result.error.kind, "read_only_violation");
    assert.equal(readFileSync(join(world.repoRoot, "hacked.txt"), "utf8"), "nope\n");
  } finally {
    world.cleanup();
  }
});

test("idempotent replay returns the stored result without respawning", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("cursor-plan.job.template.json", world);
    const outDir = join(world.outRoot, "idemp");
    const first = runHarness(world, jobPath, outDir);
    assert.equal(first.spawned.status, 0, first.spawned.stderr);
    rmSync(first.dumpPath, { force: true });
    const second = runHarness(world, jobPath, outDir);
    assert.equal(second.spawned.status, 0, second.spawned.stderr);
    assert.equal(existsSync(second.dumpPath), false);
    assert.equal(second.result.jobSha256, first.result.jobSha256);
    assert.equal(second.result.adapter, "cursor");
    assert.equal(second.result.status, "completed");
  } finally {
    world.cleanup();
  }
});
