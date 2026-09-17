import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawn, spawnSync } from "node:child_process";
import {
  chmodSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { writeStageArtifacts } from "../src/artifacts.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const HARNESS = join(ROOT, "scripts", "harness.mjs");
const STUB = join(ROOT, "tests", "fixtures", "stub-pi.mjs");
const FIXTURE_REPO = join(ROOT, "tests", "fixtures", "repo");
const JOBS = join(ROOT, "tests", "fixtures", "jobs");
const SRC_DIR = join(ROOT, "src");

function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function git(cwd, args) {
  return spawnSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
}

function toolEnd(tool, payload, { isError = false } = {}) {
  return {
    type: "tool_execution_end",
    toolCallId: "call-1",
    toolName: tool,
    result: { content: [{ type: "text", text: `Submitted ${tool}` }], details: payload },
    isError,
  };
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

function directImplementationPayload() {
  return {
    schema: "direct-implementation.v1",
    outcome: "completed",
    summary: "done",
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

function setupWorld() {
  const tmp = mkdtempSync(join(tmpdir(), "harness-int-"));
  const repo = join(tmp, "repo");
  const outRoot = join(tmp, "out");
  const delegate = join(tmp, "delegate-agent");
  const autoHandoff = join(tmp, "pi-auto-handoff");
  mkdirSync(outRoot, { recursive: true });
  mkdirSync(delegate, { recursive: true });
  writeFileSync(join(delegate, "index.ts"), "export {};\n");
  mkdirSync(join(autoHandoff, "src"), { recursive: true });
  writeFileSync(join(autoHandoff, "package.json"), '{"name":"pi-auto-handoff"}\n');
  writeFileSync(join(autoHandoff, "src", "index.ts"), "export {};\n");
  const todos = join(tmp, "todos-tool", "src");
  mkdirSync(todos, { recursive: true });
  writeFileSync(join(todos, "index.ts"), "export {};\n");
  cpSync(FIXTURE_REPO, repo, { recursive: true });
  git(repo, ["init", "-b", "main"]);
  git(repo, ["config", "user.email", "test@example.com"]);
  git(repo, ["config", "user.name", "Test"]);
  git(repo, ["add", "."]);
  git(repo, ["commit", "-m", "init"]);
  const repoRoot = realpathSync(repo);
  const head = git(repoRoot, ["rev-parse", "HEAD"]).stdout.trim();
  const requirementPath = join(repoRoot, "requirement.md");
  return {
    tmp, repoRoot, outRoot, delegate, autoHandoff, todos, head, requirementPath,
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

function runHarness(world, jobPath, outDir, envExtra = {}, { createOutDir = true } = {}) {
  if (createOutDir) mkdirSync(outDir, { recursive: true });
  const dumpPath = join(outDir, "stub-dump.json");
  const env = {
    ...process.env,
    PI_BIN: STUB,
    PI_DELEGATE_AGENT_ROOT: world.delegate,
    PI_AUTO_HANDOFF_ROOT: world.autoHandoff,
    PI_TODOS_TOOL_ROOT: world.todos,
  };
  for (const key of Object.keys(env)) {
    if (key.startsWith("PI_STUB_")) delete env[key];
  }
  env.PI_STUB_DUMP = dumpPath;
  Object.assign(env, envExtra);
  const spawned = spawnSync(process.execPath, [HARNESS, "run", "--job", jobPath, "--out-dir", outDir], {
    env,
    encoding: "utf8",
    timeout: 20_000,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const resultPath = join(outDir, "result.json");
  const result = existsSync(resultPath) ? JSON.parse(readFileSync(resultPath, "utf8")) : null;
  const dump = existsSync(dumpPath) ? JSON.parse(readFileSync(dumpPath, "utf8")) : null;
  return { spawned, result, dump, dumpPath, resultPath };
}

test("--job rejects non-regular and unreadable files before Pi dispatch", () => {
  const world = setupWorld();
  try {
    const directoryJob = runHarness(world, world.tmp, join(world.outRoot, "job-directory"));
    assert.equal(directoryJob.spawned.status, 2, directoryJob.spawned.stderr);
    assert.match(directoryJob.spawned.stderr, /regular file/);
    assert.equal(directoryJob.result, null);
    assert.equal(existsSync(directoryJob.dumpPath), false);

    const unreadablePath = join(world.tmp, "unreadable-job.json");
    writeFileSync(unreadablePath, "{}\n");
    chmodSync(unreadablePath, 0o000);
    const unreadableJob = runHarness(world, unreadablePath, join(world.outRoot, "job-unreadable"));
    assert.equal(unreadableJob.spawned.status, 2, unreadableJob.spawned.stderr);
    assert.match(unreadableJob.spawned.stderr, /not readable/);
    assert.equal(unreadableJob.result, null);
    assert.equal(existsSync(unreadableJob.dumpPath), false);
    chmodSync(unreadablePath, 0o600);
  } finally {
    world.cleanup();
  }
});

test("--job rejects a FIFO without blocking", () => {
  const world = setupWorld();
  try {
    const fifoPath = join(world.tmp, "job.fifo");
    const outDir = join(world.outRoot, "job-fifo");
    const dumpPath = join(outDir, "stub-dump.json");
    mkdirSync(outDir);
    execFileSync("mkfifo", [fifoPath]);
    const spawned = spawnSync(
      process.execPath,
      [HARNESS, "run", "--job", fifoPath, "--out-dir", outDir],
      {
        env: {
          ...process.env,
          PI_BIN: STUB,
          PI_DELEGATE_AGENT_ROOT: world.delegate,
          PI_STUB_DUMP: dumpPath,
        },
        encoding: "utf8",
        timeout: 1_500,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    assert.equal(spawned.error, undefined, spawned.error?.message);
    assert.equal(spawned.status, 2, spawned.stderr);
    assert.match(spawned.stderr, /regular file/);
    assert.equal(existsSync(join(outDir, "result.json")), false);
    assert.equal(existsSync(dumpPath), false);
  } finally {
    world.cleanup();
  }
});

test("pre-existing external out-dir publishes terminal Results for invalid Jobs", () => {
  const world = setupWorld();
  try {
    const cases = [
      {
        name: "malformed",
        raw: "{not json\n",
        stored: "{not json\n",
      },
      {
        name: "identityless",
        raw: "[ ]\n",
        stored: "[]\n",
      },
    ];
    for (const item of cases) {
      const jobPath = join(world.tmp, `${item.name}.job.json`);
      const outDir = join(world.outRoot, `invalid-${item.name}`);
      writeFileSync(jobPath, item.raw);
      const run = runHarness(world, jobPath, outDir);
      assert.equal(run.spawned.status, 1, `${item.name}: ${run.spawned.stderr}`);
      assert.equal(run.result.status, "failed", item.name);
      assert.equal(run.result.error.kind, "invalid_job", item.name);
      assert.equal(run.result.jobId, null, item.name);
      assert.equal(run.result.idempotencyKey, null, item.name);
      assert.equal(run.result.taskId, null, item.name);
      assert.equal(run.result.stage, null, item.name);
      assert.equal(readFileSync(join(outDir, "job.json"), "utf8"), item.stored, item.name);
      assert.match(readFileSync(join(outDir, "job.sha256"), "utf8"), /^[a-f0-9]{64}\n$/, item.name);
      const eventTypes = readFileSync(join(outDir, "events.jsonl"), "utf8")
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line).type);
      assert.deepEqual(eventTypes, ["run_started", "run_finished"], item.name);
      assert.equal(existsSync(run.dumpPath), false, item.name);
      assert.equal(existsSync(join(outDir, "run.lock")), false, item.name);

      const storedResult = readFileSync(run.resultPath, "utf8");
      const storedEvents = readFileSync(join(outDir, "events.jsonl"), "utf8");
      const replay = runHarness(world, jobPath, outDir);
      assert.equal(replay.spawned.status, 1, `${item.name} replay: ${replay.spawned.stderr}`);
      assert.equal(readFileSync(run.resultPath, "utf8"), storedResult, `${item.name} replay result`);
      assert.equal(readFileSync(join(outDir, "events.jsonl"), "utf8"), storedEvents, `${item.name} replay events`);
      assert.equal(existsSync(replay.dumpPath), false, `${item.name} replay`);
    }
  } finally {
    world.cleanup();
  }
});

test("established external out-dir publishes workspace failures for invalid repository roots", () => {
  const world = setupWorld();
  try {
    const missingRepo = join(world.tmp, "missing-repo");
    const nonGitRepo = join(world.tmp, "not-a-git-repo");
    mkdirSync(nonGitRepo);
    for (const [name, repoRoot] of [["missing", missingRepo], ["non-git", nonGitRepo]]) {
      const { job, jobPath } = materialize("plan.job.template.json", world);
      job.workspace.repoRoot = repoRoot;
      writeFileSync(jobPath, `${JSON.stringify(job, null, 2)}\n`);
      const outDir = join(world.outRoot, `established-${name}`);
      const run = runHarness(world, jobPath, outDir);
      assert.equal(run.spawned.status, 1, `${name}: ${run.spawned.stderr}`);
      assert.equal(run.result.status, "failed", name);
      assert.equal(run.result.error.kind, "workspace_mismatch", name);
      assert.equal(run.result.jobId, job.jobId, name);
      assert.equal(readFileSync(join(outDir, "job.json"), "utf8"), `${JSON.stringify(job, null, 2)}\n`, name);
      assert.match(readFileSync(join(outDir, "job.sha256"), "utf8"), /^[a-f0-9]{64}\n$/, name);
      const eventTypes = readFileSync(join(outDir, "events.jsonl"), "utf8")
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line).type);
      assert.deepEqual(eventTypes, ["run_started", "run_finished"], name);
      assert.equal(existsSync(run.dumpPath), false, name);
      assert.equal(existsSync(join(outDir, "run.lock")), false, name);
    }
  } finally {
    world.cleanup();
  }
});

test("invalid repository identity never creates a new out-dir", () => {
  const world = setupWorld();
  try {
    const missingRepo = join(world.tmp, "missing-repo");
    const nonGitRepo = join(world.tmp, "not-a-git-repo");
    mkdirSync(nonGitRepo);
    for (const [name, repoRoot] of [["missing", missingRepo], ["non-git", nonGitRepo]]) {
      const { job, jobPath } = materialize("plan.job.template.json", world);
      job.workspace.repoRoot = repoRoot;
      writeFileSync(jobPath, `${JSON.stringify(job, null, 2)}\n`);
      const outDir = join(world.tmp, `unestablished-${name}`);
      const run = runHarness(world, jobPath, outDir, {}, { createOutDir: false });
      assert.equal(run.spawned.status, 2, `${name}: ${run.spawned.stderr}`);
      assert.equal(run.result, null, name);
      assert.equal(existsSync(outDir), false, name);
      assert.equal(existsSync(run.dumpPath), false, name);
    }
  } finally {
    world.cleanup();
  }
});

test("an existing non-directory out-dir remains a CLI usage error", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const outDir = join(world.tmp, "out-is-a-file");
    writeFileSync(outDir, "preserve\n");
    const run = runHarness(world, jobPath, outDir, {}, { createOutDir: false });
    assert.equal(run.spawned.status, 2, run.spawned.stderr);
    assert.equal(run.result, null);
    assert.equal(readFileSync(outDir, "utf8"), "preserve\n");
  } finally {
    world.cleanup();
  }
});

test("V9.1 Planner writes canonical plan JSON, markdown, and completed Result", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const outDir = join(world.outRoot, "plan");
    const run = runHarness(world, jobPath, outDir, {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", planPayload())]),
    });
    assert.equal(run.spawned.status, 0, run.spawned.stderr);
    assert.equal(run.result.status, "completed");
    assert.equal(run.result.structuredOutput.kind, "plan");
    assert.ok(run.result.artifacts.some((item) => item.canonical && item.path.endsWith(".json")));
    assert.ok(run.result.artifacts.some((item) => item.canonical === false && item.path.endsWith(".md")));
    const md = readFileSync(run.result.artifacts.find((item) => item.path.endsWith(".md")).path, "utf8");
    assert.match(md, /Greet helper/);
  } finally {
    world.cleanup();
  }
});

test("V9.2 Plan Reviewer persists unicode/quotes and a unique verdict", () => {
  const world = setupWorld();
  try {
    const plan = writeCanonicalPlan(world);
    const payload = {
      schema: "plan-review.v1",
      verdict: "approved",
      summary: 'OK: "quotes", colon: value, 你好\nmultiline',
      findings: [],
    };
    const { jobPath } = materialize("plan-review.job.template.json", world, {
      planPath: plan.path,
      planSha: plan.sha256,
    });
    const run = runHarness(world, jobPath, join(world.outRoot, "plan-review"), {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan_review", payload)]),
    });
    assert.equal(run.spawned.status, 0, run.spawned.stderr);
    assert.equal(run.result.structuredOutput.payload.summary, payload.summary);
    assert.equal(run.result.structuredOutput.payload.verdict, "approved");
    assert.deepEqual(run.result.touchedFiles, []);
  } finally {
    world.cleanup();
  }
});

test("V9.3 Implementer records git touched files and check results", () => {
  const world = setupWorld();
  try {
    const plan = writeCanonicalPlan(world);
    const { job, jobPath } = materialize("implement.job.template.json", world, {
      planPath: plan.path,
      planSha: plan.sha256,
    });
    job.verification.push({
      id: "always-fail",
      argv: [process.execPath, "-e", "process.exit(2)"],
      cwd: world.repoRoot,
      timeoutSeconds: 10,
      expectedExitCode: 0,
    });
    writeFileSync(jobPath, `${JSON.stringify(job, null, 2)}\n`);
    const run = runHarness(world, jobPath, join(world.outRoot, "implement"), {
      PI_STUB_WRITE_RELPATH: "src/greet.mjs",
      PI_STUB_WRITE_CONTENTS: "export function greet(name) { return `Hello, ${name}`; }\n",
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_implementation", {
        schema: "implementation.v1",
        outcome: "completed",
        summary: "done",
        completedWorkPackages: ["WP-01"],
        deviations: [],
        residualRisks: [],
        blockingIssues: [],
      })]),
    });
    assert.equal(run.spawned.status, 0, run.spawned.stderr);
    assert.equal(run.result.status, "completed");
    assert.ok(run.result.touchedFiles.includes("src/greet.mjs"));
    assert.equal(run.result.checks.find((item) => item.id === "check-unit").status, "passed");
    assert.equal(run.result.checks.find((item) => item.id === "always-fail").status, "failed");
  } finally {
    world.cleanup();
  }
});

test("direct_implement uses requirement-only input, typed submit, and host checks", () => {
  const world = setupWorld();
  try {
    const { job, jobPath } = materialize("direct-implement.job.template.json", world);
    assert.equal(job.stage, "direct_implement");
    assert.deepEqual(job.inputs.map((item) => item.kind), ["requirement"]);
    assert.equal(job.expectedOutput.kind, "direct-implementation");
    job.verification.push({
      id: "always-fail",
      argv: [process.execPath, "-e", "process.exit(2)"],
      cwd: world.repoRoot,
      timeoutSeconds: 10,
      expectedExitCode: 0,
    });
    writeFileSync(jobPath, `${JSON.stringify(job, null, 2)}\n`);
    const run = runHarness(world, jobPath, join(world.outRoot, "direct-implement"), {
      PI_STUB_WRITE_RELPATH: "src/greet.mjs",
      PI_STUB_WRITE_CONTENTS: "export function greet(name) { return `Hello, ${name}`; }\n",
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_direct_implementation", directImplementationPayload())]),
    });
    assert.equal(run.spawned.status, 0, run.spawned.stderr);
    assert.equal(run.result.status, "completed");
    assert.equal(run.result.stage, "direct_implement");
    assert.equal(run.result.structuredOutput.kind, "direct-implementation");
    assert.equal(run.result.structuredOutput.payload.schema, "direct-implementation.v1");
    assert.ok(run.result.artifacts.some((item) => item.canonical && item.path.includes("direct-implementation")));
    assert.ok(run.result.touchedFiles.includes("src/greet.mjs"));
    assert.equal(run.result.checks.find((item) => item.id === "check-unit").status, "passed");
    assert.equal(run.result.checks.find((item) => item.id === "always-fail").status, "failed");
    assert.match(readFileSync(join(world.outRoot, "direct-implement", "brief.txt"), "utf8"), /submit_direct_implementation/);
    assert.doesNotMatch(JSON.stringify(job.inputs), /"kind":"plan"/);
  } finally {
    world.cleanup();
  }
});

test("V9.4 Execute Reviewer stays read-only on a dirty implementation", () => {
  const world = setupWorld();
  try {
    writeFileSync(join(world.repoRoot, "src/greet.mjs"), "export function greet(name) { return `Hello, ${name}`; }\n");
    const plan = writeCanonicalPlan(world);
    const impl = writeCanonicalImplementation(world);
    const { jobPath } = materialize("execute-review.job.template.json", world, {
      planPath: plan.path,
      planSha: plan.sha256,
      implementationPath: impl.path,
      implementationSha: impl.sha256,
    });
    const run = runHarness(world, jobPath, join(world.outRoot, "exec-review"), {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_execute_review", {
        schema: "execute-review.v1",
        verdict: "approved",
        summary: "ok",
        findings: [],
        acceptanceCoverage: ["C1: greet test"],
      })]),
    });
    assert.equal(run.spawned.status, 0, run.spawned.stderr);
    assert.deepEqual(run.result.touchedFiles, []);
    assert.equal(run.result.workspace.snapshotBeforeSha256, run.result.workspace.snapshotAfterSha256);
  } finally {
    world.cleanup();
  }
});

test("V9.5 Exact resume passes session through and rejects mismatch", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world, { sessionId: "sess-exact" });
    const ok = runHarness(world, jobPath, join(world.outRoot, "resume-ok"), {
      PI_STUB_SESSION: "sess-exact",
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", planPayload())]),
    });
    assert.equal(ok.spawned.status, 0, ok.spawned.stderr);
    assert.equal(ok.result.sessionId, "sess-exact");
    assert.equal(ok.dump.argv[ok.dump.argv.indexOf("--session") + 1], "sess-exact");

    const { jobPath: badPath } = materialize("plan.job.template.json", world, { sessionId: "sess-exact" });
    const bad = runHarness(world, badPath, join(world.outRoot, "resume-bad"), {
      PI_STUB_SESSION_MISMATCH: "other-sess",
    });
    assert.notEqual(bad.spawned.status, 0);
    assert.equal(bad.result.status, "failed");
    assert.equal(bad.result.error.kind, "session_mismatch");

    const { jobPath: missingPath } = materialize("plan.job.template.json", world, { sessionId: "sess-exact" });
    const missing = runHarness(world, missingPath, join(world.outRoot, "resume-missing"), {
      PI_STUB_NO_SESSION: "1",
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", planPayload())]),
    });
    assert.notEqual(missing.spawned.status, 0);
    assert.equal(missing.result.status, "failed");
    assert.equal(missing.result.error.kind, "session_mismatch");
  } finally {
    world.cleanup();
  }
});

test("V9.6 Output protocol: missing recovers once; duplicate/error/invalid do not", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const missing = runHarness(world, jobPath, join(world.outRoot, "missing"));
    assert.equal(missing.result.error.kind, "structured_output_missing");
    assert.equal(missing.result.paths.adapterRuns.length, 2);

    const first = toolEnd("submit_plan", planPayload());
    const second = { ...toolEnd("submit_plan", { ...planPayload(), title: "dup" }), toolCallId: "call-2" };
    const dup = runHarness(world, jobPath, join(world.outRoot, "dup"), {
      PI_STUB_EVENTS: JSON.stringify([first, second]),
    });
    assert.equal(dup.result.error.kind, "structured_output_duplicate");
    assert.equal(dup.result.paths.adapterRuns.length, 1);

    const errored = runHarness(world, jobPath, join(world.outRoot, "tool-error"), {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", planPayload(), { isError: true })]),
    });
    assert.equal(errored.result.error.kind, "structured_output_invalid");
    assert.equal(errored.result.paths.adapterRuns.length, 1);

    const invalid = runHarness(world, jobPath, join(world.outRoot, "bad-schema"), {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", { schema: "nope" })]),
    });
    assert.equal(invalid.result.error.kind, "structured_output_invalid");

    const wrongTool = runHarness(world, jobPath, join(world.outRoot, "wrong-tool"), {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan_review", {
        schema: "plan-review.v1",
        verdict: "approved",
        summary: "wrong stage",
        findings: [],
      })]),
    });
    assert.notEqual(wrongTool.spawned.status, 0);
    assert.notEqual(wrongTool.result.status, "completed");
    assert.ok(["structured_output_missing", "structured_output_invalid"].includes(wrongTool.result.error.kind));
  } finally {
    world.cleanup();
  }
});

test("V9.7 Terminal truth maps settled/nonzero/timeout/unavailable", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const unsettled = runHarness(world, jobPath, join(world.outRoot, "unsettled"), { PI_STUB_NO_SETTLED: "1" });
    assert.equal(unsettled.result.status, "failed");
    assert.equal(unsettled.result.error.kind, "agent_not_settled");

    const nonzero = runHarness(world, jobPath, join(world.outRoot, "nonzero"), { PI_STUB_EXIT: "1" });
    assert.equal(nonzero.result.status, "failed");

    const { job, jobPath: timeoutJob } = materialize("plan.job.template.json", world);
    job.limits.timeoutSeconds = 1;
    writeFileSync(timeoutJob, `${JSON.stringify(job, null, 2)}\n`);
    const timed = runHarness(world, timeoutJob, join(world.outRoot, "timeout"), { PI_STUB_SLEEP_MS: "4000" });
    assert.equal(timed.result.status, "timed_out");
    assert.equal(timed.spawned.status, 124);

    const missingPi = runHarness(world, jobPath, join(world.outRoot, "nopi"), {
      PI_BIN: join(world.tmp, "no-pi-bin"),
    });
    assert.equal(missingPi.result.status, "unavailable");
    assert.equal(missingPi.spawned.status, 127);
  } finally {
    world.cleanup();
  }
});

test("V9.7 aborted maps SIGINT to status aborted and exit 130", async () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const outDir = join(world.outRoot, "aborted");
    mkdirSync(outDir, { recursive: true });
    const env = {
      ...process.env,
      PI_BIN: STUB,
      PI_DELEGATE_AGENT_ROOT: world.delegate,
    };
    for (const key of Object.keys(env)) {
      if (key.startsWith("PI_STUB_")) delete env[key];
    }
    env.PI_STUB_DUMP = join(outDir, "stub-dump.json");
    env.PI_STUB_SLEEP_MS = "20000";
    const child = spawn(process.execPath, [HARNESS, "run", "--job", jobPath, "--out-dir", outDir], {
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const lockPath = join(outDir, "run.lock");
    const deadline = Date.now() + 8000;
    while (!existsSync(lockPath) && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.equal(existsSync(lockPath), true, "run.lock should exist before abort");
    const lock = JSON.parse(readFileSync(lockPath, "utf8"));
    assert.equal(typeof lock.pid, "number");
    assert.equal(lock.jobId, "job_plan");
    assert.match(lock.jobSha256, /^[a-f0-9]{64}$/);
    assert.equal(lock.outDir, outDir);
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

test("V9.8 Guards reject before stub dispatch", () => {
  const world = setupWorld();
  try {
    const { job, jobPath } = materialize("plan.job.template.json", world);
    job.workspace.expectedHead = "a".repeat(40);
    writeFileSync(jobPath, `${JSON.stringify(job, null, 2)}\n`);
    const head = runHarness(world, jobPath, join(world.outRoot, "guard-head"));
    assert.equal(head.result.error.kind, "workspace_mismatch");
    assert.equal(existsSync(head.dumpPath), false);

    const { job: branchJob, jobPath: branchPath } = materialize("plan.job.template.json", world);
    branchJob.workspace.branch = "other";
    writeFileSync(branchPath, `${JSON.stringify(branchJob, null, 2)}\n`);
    const branch = runHarness(world, branchPath, join(world.outRoot, "guard-branch"));
    assert.equal(branch.result.error.kind, "workspace_mismatch");
    assert.equal(existsSync(branch.dumpPath), false);

    const originalGreet = readFileSync(join(world.repoRoot, "src/greet.mjs"));
    writeFileSync(join(world.repoRoot, "src/greet.mjs"), "export function greet() { return \"dirty\"; }\n");
    const { jobPath: dirtyPath } = materialize("plan.job.template.json", world);
    const dirty = runHarness(world, dirtyPath, join(world.outRoot, "guard-dirty"));
    assert.equal(dirty.result.error.kind, "workspace_mismatch");
    assert.equal(existsSync(dirty.dumpPath), false);
    writeFileSync(join(world.repoRoot, "src/greet.mjs"), originalGreet);

    const { job: hashJob, jobPath: hashPath } = materialize("plan.job.template.json", world);
    hashJob.inputs[0].sha256 = "a".repeat(64);
    writeFileSync(hashPath, `${JSON.stringify(hashJob, null, 2)}\n`);
    const hash = runHarness(world, hashPath, join(world.outRoot, "guard-hash"));
    assert.equal(hash.result.error.kind, "input_hash_mismatch");
    assert.equal(existsSync(hash.dumpPath), false);

    const { job: profileJob, jobPath: profilePath } = materialize("plan.job.template.json", world);
    profileJob.agent.profile = "implementer";
    writeFileSync(profilePath, `${JSON.stringify(profileJob, null, 2)}\n`);
    const profile = runHarness(world, profilePath, join(world.outRoot, "guard-profile"));
    assert.equal(profile.result.error.kind, "invalid_job");
    assert.equal(existsSync(profile.dumpPath), false);

    const { job: modeJob, jobPath: modePath } = materialize("plan.job.template.json", world);
    modeJob.permissions.mode = "write";
    writeFileSync(modePath, `${JSON.stringify(modeJob, null, 2)}\n`);
    const mode = runHarness(world, modePath, join(world.outRoot, "guard-mode"));
    assert.equal(mode.result.error.kind, "invalid_job");
    assert.equal(existsSync(mode.dumpPath), false);

    const { job: outputJob, jobPath: outputPath } = materialize("plan.job.template.json", world);
    outputJob.expectedOutput = { kind: "implementation", schema: "implementation.v1" };
    writeFileSync(outputPath, `${JSON.stringify(outputJob, null, 2)}\n`);
    const output = runHarness(world, outputPath, join(world.outRoot, "guard-output"));
    assert.equal(output.result.error.kind, "invalid_job");
    assert.equal(existsSync(output.dumpPath), false);

    const { jobPath: insidePath } = materialize("plan.job.template.json", world);
    const inside = runHarness(world, insidePath, join(world.repoRoot, "nested-out"), {}, { createOutDir: false });
    assert.notEqual(inside.spawned.status, 0);
    assert.equal(inside.result, null);
    assert.equal(existsSync(join(world.repoRoot, "nested-out")), false);
    assert.equal(existsSync(join(world.repoRoot, "nested-out", "stub-dump.json")), false);
  } finally {
    world.cleanup();
  }
});

test("symlink-mediated out-dir inside the repo is rejected without creating files", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const pointer = join(world.tmp, "points-at-repo");
    symlinkSync(world.repoRoot, pointer);
    const outDir = join(pointer, "via-symlink");
    const run = runHarness(world, jobPath, outDir, {}, { createOutDir: false });
    assert.equal(run.spawned.status, 2);
    assert.equal(run.result, null);
    assert.equal(existsSync(join(world.repoRoot, "via-symlink")), false);
    assert.equal(existsSync(join(world.repoRoot, "stub-dump.json")), false);
  } finally {
    world.cleanup();
  }
});

test("verification cwd symlink escape is rejected before stub dispatch", () => {
  const world = setupWorld();
  try {
    mkdirSync(join(world.tmp, "outside"));
    symlinkSync(join(world.tmp, "outside"), join(world.repoRoot, "escape"));
    const plan = writeCanonicalPlan(world);
    const { job, jobPath } = materialize("implement.job.template.json", world, {
      planPath: plan.path,
      planSha: plan.sha256,
    });
    job.verification[0].cwd = join(world.repoRoot, "escape");
    job.workspace.requireCleanAtStart = false;
    writeFileSync(jobPath, `${JSON.stringify(job, null, 2)}\n`);
    const run = runHarness(world, jobPath, join(world.outRoot, "cwd-escape"));
    assert.notEqual(run.spawned.status, 0);
    assert.equal(run.result.error.kind, "workspace_mismatch");
    assert.equal(existsSync(run.dumpPath), false);
  } finally {
    world.cleanup();
  }
});

test("checks execute using the verified realpath of a verification cwd symlink", () => {
  const world = setupWorld();
  try {
    mkdirSync(join(world.repoRoot, "sub"));
    symlinkSync(join(world.repoRoot, "sub"), join(world.repoRoot, "link"));
    const plan = writeCanonicalPlan(world);
    const { job, jobPath } = materialize("implement.job.template.json", world, {
      planPath: plan.path,
      planSha: plan.sha256,
    });
    job.verification = [{
      id: "cwd-probe",
      argv: [process.execPath, "-e", "require('fs').writeFileSync('cwd.txt', process.cwd())"],
      cwd: join(world.repoRoot, "link"),
      timeoutSeconds: 10,
      expectedExitCode: 0,
    }];
    job.workspace.requireCleanAtStart = false;
    writeFileSync(jobPath, `${JSON.stringify(job, null, 2)}\n`);
    const run = runHarness(world, jobPath, join(world.outRoot, "cwd-realpath"), {
      PI_STUB_WRITE_RELPATH: "src/greet.mjs",
      PI_STUB_WRITE_CONTENTS: "export function greet(name) { return `Hello, ${name}`; }\n",
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_implementation", {
        schema: "implementation.v1",
        outcome: "completed",
        summary: "done",
        completedWorkPackages: ["WP-01"],
        deviations: [],
        residualRisks: [],
        blockingIssues: [],
      })]),
    });
    assert.equal(run.spawned.status, 0, run.spawned.stderr);
    assert.equal(run.result.checks[0].status, "passed");
    const expectedCwd = realpathSync(join(world.repoRoot, "sub"));
    assert.equal(run.result.checks[0].cwd, expectedCwd);
    assert.equal(readFileSync(join(expectedCwd, "cwd.txt"), "utf8"), expectedCwd);
  } finally {
    world.cleanup();
  }
});

test("V9.9 Read-only bypass is detected and the tree is left intact", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "bypass"), {
      PI_STUB_WRITE_RELPATH: "hacked.txt",
      PI_STUB_WRITE_CONTENTS: "nope\n",
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", planPayload())]),
    });
    assert.equal(run.result.error.kind, "read_only_violation");
    assert.equal(readFileSync(join(world.repoRoot, "hacked.txt"), "utf8"), "nope\n");
  } finally {
    world.cleanup();
  }
});

test("V9.10 Idempotency replays, rejects different hashes, and honors orphan locks", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const outDir = join(world.outRoot, "idemp");
    const first = runHarness(world, jobPath, outDir, {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", planPayload())]),
    });
    assert.equal(first.spawned.status, 0, first.spawned.stderr);
    rmSync(first.dumpPath, { force: true });
    const second = runHarness(world, jobPath, outDir);
    assert.equal(second.spawned.status, 0);
    assert.equal(existsSync(second.dumpPath), false);
    assert.equal(second.result.jobSha256, first.result.jobSha256);

    const other = JSON.parse(readFileSync(jobPath, "utf8"));
    other.jobId = "job_other";
    const otherPath = join(world.tmp, "other.json");
    writeFileSync(otherPath, `${JSON.stringify(other, null, 2)}\n`);
    const conflict = runHarness(world, otherPath, outDir);
    assert.equal(conflict.spawned.status, 2);
    assert.equal(JSON.parse(readFileSync(first.resultPath, "utf8")).jobId, "job_plan");

    const locked = join(world.outRoot, "locked");
    mkdirSync(locked);
    writeFileSync(join(locked, "run.lock"), "orphan\n");
    const orphan = runHarness(world, jobPath, locked);
    assert.equal(orphan.spawned.status, 75);
    assert.equal(existsSync(join(locked, "result.json")), false);
  } finally {
    world.cleanup();
  }
});

test("V9.11 Final message JSON is never parsed as protocol", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "prose"), {
      PI_STUB_FINAL: JSON.stringify(planPayload()),
    });
    assert.equal(run.result.status, "failed");
    assert.equal(run.result.error.kind, "structured_output_missing");
    const sources = readdirSync(SRC_DIR).filter((name) => name.endsWith(".mjs"));
    sources.push("harness.mjs");
    for (const name of sources) {
      const path = name === "harness.mjs" ? HARNESS : join(SRC_DIR, name);
      const src = readFileSync(path, "utf8");
      assert.doesNotMatch(src, /JSON\.parse\(finalMessage\)/);
      assert.doesNotMatch(src, /yaml/i);
      assert.doesNotMatch(src, /from\s+['\"]plan\.md['\"]/);
    }
  } finally {
    world.cleanup();
  }
});

test("structured inputs that are not canonical Artifacts fail closed before Pi", () => {
  const world = setupWorld();
  try {
    const cases = [
      {
        name: "malformed",
        write(path) { writeFileSync(path, "{not json\n"); },
      },
      {
        name: "bare-payload",
        write(path) { writeFileSync(path, `${JSON.stringify(planPayload(), null, 2)}\n`); },
      },
      {
        name: "wrong-kind",
        write(path) {
          const impl = writeCanonicalImplementation(world);
          writeFileSync(path, readFileSync(impl.path));
        },
      },
      {
        name: "wrong-wrapper-schema",
        write(path) {
          const plan = writeCanonicalPlan(world);
          const artifact = JSON.parse(readFileSync(plan.path, "utf8"));
          artifact.schema = "coding-agent.artifact.v0";
          writeFileSync(path, `${JSON.stringify(artifact, null, 2)}\n`);
        },
      },
      {
        name: "invalid-nested-payload",
        write(path) {
          const plan = writeCanonicalPlan(world);
          const artifact = JSON.parse(readFileSync(plan.path, "utf8"));
          artifact.payload.schema = "nope";
          writeFileSync(path, `${JSON.stringify(artifact, null, 2)}\n`);
        },
      },
      {
        name: "identity-inconsistent",
        write(path) {
          const plan = writeCanonicalPlan(world);
          const artifact = JSON.parse(readFileSync(plan.path, "utf8"));
          artifact.job.stage = "implement";
          artifact.job.jobSha256 = "not-a-hash";
          writeFileSync(path, `${JSON.stringify(artifact, null, 2)}\n`);
        },
      },
    ];
    for (const item of cases) {
      const planPath = join(world.tmp, `${item.name}.json`);
      item.write(planPath);
      const { jobPath } = materialize("plan-review.job.template.json", world, {
        planPath,
        planSha: sha256File(planPath),
      });
      const outDir = join(world.outRoot, `reject-${item.name}`);
      const run = runHarness(world, jobPath, outDir, {
        PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan_review", {
          schema: "plan-review.v1",
          verdict: "approved",
          summary: "should not run",
          findings: [],
        })]),
      });
      assert.equal(run.spawned.status, 1, item.name);
      assert.equal(run.result.status, "failed", item.name);
      assert.equal(run.result.error.kind, "invalid_job", item.name);
      assert.equal(existsSync(run.dumpPath), false, item.name);
      assert.equal(existsSync(join(outDir, "brief.txt")), false, item.name);
      assert.equal(existsSync(join(outDir, "run.lock")), false, item.name);
    }
  } finally {
    world.cleanup();
  }
});

test("trusted idempotent replay is bound to the current Job identity", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const mismatches = [
      ["jobId", "job_tampered"],
      ["idempotencyKey", "tampered-key"],
      ["taskId", "tampered-task"],
      ["stage", "implement"],
      ["jobSha256", "1".repeat(64)],
    ];
    for (const [field, value] of mismatches) {
      const outDir = join(world.outRoot, `idemp-${field}`);
      const first = runHarness(world, jobPath, outDir, {
        PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", planPayload())]),
      });
      assert.equal(first.spawned.status, 0, first.spawned.stderr);
      const stored = JSON.parse(readFileSync(first.resultPath, "utf8"));
      stored[field] = value;
      writeFileSync(first.resultPath, `${JSON.stringify(stored, null, 2)}\n`);
      rmSync(first.dumpPath, { force: true });
      const replay = runHarness(world, jobPath, outDir);
      assert.equal(replay.spawned.status, 2, field);
      assert.match(replay.spawned.stderr, /idempotency_conflict/, field);
      assert.equal(existsSync(replay.dumpPath), false, field);
      const after = JSON.parse(readFileSync(first.resultPath, "utf8"));
      assert.equal(after[field], value, field);
    }
  } finally {
    world.cleanup();
  }
});

test("missing harnessAttestation fail-closes with extension_manifest_mismatch", () => {
  const world = setupWorld();
  try {
    const { jobPath } = materialize("plan.job.template.json", world);
    const run = runHarness(world, jobPath, join(world.outRoot, "no-attest"), {
      PI_STUB_NO_ATTESTATION: "1",
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", planPayload())]),
    });
    assert.equal(run.spawned.status, 1, run.spawned.stderr);
    assert.equal(run.result.status, "failed");
    assert.equal(run.result.error.kind, "extension_manifest_mismatch");
    assert.equal(run.result.structuredOutput, null);
  } finally {
    world.cleanup();
  }
});

test("spawn-record.json follows the stage profile (implement vs direct_implement vs plan)", () => {
  const world = setupWorld();
  try {
    const plan = writeCanonicalPlan(world);
    const implement = materialize("implement.job.template.json", world, {
      planPath: plan.path,
      planSha: plan.sha256,
    });
    const implementRun = runHarness(world, implement.jobPath, join(world.outRoot, "spawn-implement"), {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_implementation", implementationPayload())]),
    });
    assert.equal(implementRun.spawned.status, 0, implementRun.spawned.stderr);
    const implementSpawn = JSON.parse(readFileSync(
      join(world.outRoot, "spawn-implement", "adapter", "primary", "spawn-record.json"),
      "utf8",
    ));
    assert.equal(implementSpawn.profileId, "implement-plan");
    assert.deepEqual(implementSpawn.expectedExtensionIds, ["stage-submit", "auto-handoff"]);
    assert.ok(implementSpawn.argv.includes(world.autoHandoff));
    assert.ok(implementSpawn.envKeys.includes("PI_AUTO_HANDOFF_PLAN_FILE"));

    const direct = materialize("direct-implement.job.template.json", world);
    const directRun = runHarness(world, direct.jobPath, join(world.outRoot, "spawn-direct"), {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_direct_implementation", directImplementationPayload())]),
    });
    assert.equal(directRun.spawned.status, 0, directRun.spawned.stderr);
    const directSpawn = JSON.parse(readFileSync(
      join(world.outRoot, "spawn-direct", "adapter", "primary", "spawn-record.json"),
      "utf8",
    ));
    assert.equal(directSpawn.profileId, "implement-direct");
    assert.deepEqual(directSpawn.expectedExtensionIds, ["stage-submit", "todos-tool"]);
    assert.deepEqual(directSpawn.disabledEntries, []);
    assert.ok(!JSON.stringify(directSpawn.argv).includes("auto-handoff"));
    assert.ok(!directSpawn.envKeys.includes("PI_AUTO_HANDOFF_PLAN_FILE"));
    assert.ok(JSON.stringify(directSpawn.argv).includes("todos-tool"));
    const directTools = (directSpawn.argv[directSpawn.argv.indexOf("--tools") + 1] || "").split(",");
    assert.ok(directTools.includes("todo"), "direct_implement pi --tools must include todo");

    const planRun = runHarness(world, materialize("plan.job.template.json", world).jobPath, join(world.outRoot, "spawn-plan"), {
      PI_STUB_EVENTS: JSON.stringify([toolEnd("submit_plan", planPayload())]),
    });
    assert.equal(planRun.spawned.status, 0, planRun.spawned.stderr);
    const planSpawn = JSON.parse(readFileSync(
      join(world.outRoot, "spawn-plan", "adapter", "primary", "spawn-record.json"),
      "utf8",
    ));
    assert.equal(planSpawn.profileId, "plan");
    assert.deepEqual(planSpawn.expectedExtensionIds, ["stage-submit"]);
    assert.deepEqual(planSpawn.disabledEntries, []);
    assert.ok(!JSON.stringify(planSpawn.argv).includes("auto-handoff"));
    assert.ok(planSpawn.argv.includes("-ns"));
    const planSkills = [];
    for (let i = 0; i < planSpawn.argv.length; i += 1) {
      if (planSpawn.argv[i] === "--skill") planSkills.push(planSpawn.argv[i + 1]);
    }
    assert.deepEqual(planSkills.map((item) => item.split("/").at(-1)), ["write-plan", "delegate-work"]);
  } finally {
    world.cleanup();
  }
});
