#!/usr/bin/env node
/**
 * Real Pi smoke for coding-agent-harness.
 *
 * Creates an independent fixture Git repo under the system temp directory,
 * runs Planner → Plan Reviewer, one exact-session Planner rework while the
 * tree is still clean, then Implementer → Execute Reviewer. Temp roots are
 * kept for audit.
 */
import { spawnSync } from "node:child_process";
import {
  existsSync,
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { SUBMIT_TOOLS, validatePayload } from "../src/contracts.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const HARNESS = join(ROOT, "scripts", "harness.mjs");
const FIXTURE_REPO = join(ROOT, "tests", "fixtures", "repo");
const JOBS = join(ROOT, "tests", "fixtures", "jobs");
const READ_MODEL = "zai-coding-cn/glm-5.3";
const WRITE_MODEL = "kimi-coding/k3";
const WRITE_FALLBACK = "zai-coding-cn/glm-5.3";

function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function git(cwd, args) {
  const result = spawnSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (result.status !== 0) {
    throw new Error(`git ${args.join(" ")} failed: ${result.stderr}`);
  }
  return result.stdout.trim();
}

function materialize(templateName, replacements) {
  let raw = readFileSync(join(JOBS, templateName), "utf8");
  for (const [token, value] of Object.entries(replacements)) {
    raw = raw.replaceAll(token, value);
  }
  return JSON.parse(raw);
}

function writeJob(path, job) {
  writeFileSync(path, `${JSON.stringify(job, null, 2)}\n`);
}

function blob(result) {
  return `${result?.error?.message || ""} ${result?.error?.kind || ""} ${result?.status || ""}`.toLowerCase();
}

function isAuthFailure(result) {
  return /auth|unauthoriz|api key|not logged in|credential|401/.test(blob(result));
}

function isTransient(result) {
  if (isAuthFailure(result)) return false;
  return result?.status === "unavailable"
    || result?.error?.kind === "adapter_unavailable"
    || /quota|unavailable|rate limit|timeout|temporar/.test(blob(result));
}

function isProviderUnavailable(result) {
  if (isAuthFailure(result)) return false;
  return result?.status === "unavailable"
    || result?.error?.kind === "adapter_unavailable"
    || /quota|provider.*unavail|unavailable/.test(blob(result));
}

function readJson(path) {
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8"));
}

function readJsonl(path) {
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function relayResult(outDir) {
  return readJson(join(outDir, "adapter", "primary", "result.json"));
}

function assertAdapterEvidence(outDir, expectedTool, tmp) {
  const events = readJsonl(join(outDir, "adapter", "primary", "events.jsonl"));
  if (!events.some((event) => event.type === "session" && typeof event.id === "string" && event.id.length > 0)) {
    fail(`adapter events missing session in ${outDir}`, tmp);
  }
  const toolEnds = events.filter((event) => event.type === "tool_execution_end" && event.toolName === expectedTool && !event.isError);
  if (toolEnds.length !== 1) {
    fail(`expected exactly one ${expectedTool} in ${outDir}, got ${toolEnds.length}`, tmp);
  }
  if (!toolEnds[0]?.result?.details) {
    fail(`expected ${expectedTool} native details in ${outDir}`, tmp);
  }
  if (!events.some((event) => event.type === "agent_settled")) {
    fail(`adapter events missing agent_settled in ${outDir}`, tmp);
  }
}

function hermeticEnv() {
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (key.startsWith("PI_STUB_") || key.startsWith("PI_AUTO_HANDOFF_")) delete env[key];
  }
  delete env.PI_BIN;
  delete env.PI_DELEGATE_AGENT_ROOT;
  return env;
}

function runHarness(jobPath, outDir) {
  mkdirSync(outDir, { recursive: true });
  console.log(`RUN job=${jobPath} out=${outDir}`);
  const spawned = spawnSync(process.execPath, [HARNESS, "run", "--job", jobPath, "--out-dir", outDir], {
    encoding: "utf8",
    timeout: 30 * 60 * 1000,
    stdio: ["ignore", "pipe", "pipe"],
    env: hermeticEnv(),
  });
  if (spawned.stdout) process.stdout.write(spawned.stdout);
  if (spawned.stderr) process.stderr.write(spawned.stderr);
  const resultPath = join(outDir, "result.json");
  const result = readJson(resultPath);
  if (!result) {
    console.log(`  missing result.json exit=${spawned.status}`);
    return { spawned, result: { status: "failed", error: { kind: "adapter_failed", message: spawned.stderr || "missing result.json" } }, resultPath, outDir };
  }
  console.log(`  status=${result.status} exit=${spawned.status} session=${result.sessionId} error=${result.error?.kind || "null"}`);
  console.log(`  result=${resultPath}`);
  console.log(`  resolvedModel=${relayResult(outDir)?.resolvedModel || "unknown"}`);
  if (result.artifacts?.length) {
    for (const artifact of result.artifacts) console.log(`  artifact=${artifact.path}`);
  }
  return { spawned, result, resultPath, outDir };
}

function runWithRetry(job, jobPath, outDir, tmp, { allowWriteFallback = false } = {}) {
  writeJob(jobPath, job);
  console.log(`JOB ${job.stage} model=${job.agent.model} thinking=${job.agent.thinking} session=${job.agent.sessionId}`);
  let attempt = runHarness(jobPath, outDir);
  if (attempt.result.status === "completed") return attempt;
  if (isAuthFailure(attempt.result)) {
    fail(`Pi/auth unavailable (${attempt.result.error?.message || "auth failure"}); WP-10 is incomplete`, tmp);
  }
  if (isTransient(attempt.result)) {
    console.log("  transient failure; retrying the same Job once");
    attempt = runHarness(jobPath, `${outDir}-retry`);
    if (attempt.result.status === "completed") return attempt;
    if (isAuthFailure(attempt.result)) {
      fail(`Pi/auth unavailable on retry; WP-10 is incomplete`, tmp);
    }
  }
  if (allowWriteFallback && job.agent.model === WRITE_MODEL && isProviderUnavailable(attempt.result)) {
    console.log(`  implement provider unavailable/quota; falling back to ${WRITE_FALLBACK} on the same session`);
    job.agent.model = WRITE_FALLBACK;
    if (attempt.result.sessionId) job.agent.sessionId = attempt.result.sessionId;
    writeJob(jobPath, job);
    attempt = runHarness(jobPath, `${outDir}-fallback`);
    console.log(`  resolved model=${relayResult(attempt.outDir)?.resolvedModel || job.agent.model}`);
    writeFileSync(join(tmp, "resolved-model.txt"), `${relayResult(attempt.outDir)?.resolvedModel || job.agent.model}\n`);
  }
  return attempt;
}

function fail(message, tmp) {
  console.error(`FAIL: ${message}`);
  console.error(`temp root retained: ${tmp}`);
  process.exit(1);
}

const tmp = mkdtempSync(join(tmpdir(), "coding-agent-real-pi-"));
const repo = join(tmp, "repo");
const outRoot = join(tmp, "out");
mkdirSync(outRoot, { recursive: true });
cpSync(FIXTURE_REPO, repo, { recursive: true });
git(repo, ["init", "-b", "main"]);
git(repo, ["config", "user.email", "smoke@example.com"]);
git(repo, ["config", "user.name", "Smoke"]);
git(repo, ["add", "."]);
git(repo, ["commit", "-m", "init"]);
const repoRoot = realpathSync(repo);
const head = git(repoRoot, ["rev-parse", "HEAD"]);
const requirementPath = join(repoRoot, "requirement.md");
const requirementSha = sha256File(requirementPath);
console.log(`temp root: ${tmp}`);
console.log(`repo: ${repoRoot} head=${head}`);

const replacements = {
  __REPO_ROOT__: repoRoot,
  __HEAD__: head,
  __REQUIREMENT_PATH__: requirementPath,
  __REQUIREMENT_SHA256__: requirementSha,
  __PLAN_PATH__: "",
  __PLAN_SHA256__: "",
  __IMPLEMENTATION_PATH__: "",
  __IMPLEMENTATION_SHA256__: "",
};

const planJob = materialize("plan.job.template.json", replacements);
planJob.agent.model = READ_MODEL;
planJob.agent.thinking = "high";
const planRun = runWithRetry(planJob, join(tmp, "plan.job.json"), join(outRoot, "plan"), tmp);
if (planRun.result.status !== "completed") fail("planner did not complete", tmp);
const planArtifact = planRun.result.artifacts.find((item) => item.canonical);
if (!planArtifact) fail("planner missing canonical artifact", tmp);
if (!planRun.result.artifacts.some((item) => item.path.endsWith(".md"))) fail("planner missing plan.md", tmp);
assertAdapterEvidence(planRun.outDir, SUBMIT_TOOLS.plan, tmp);

const reviewJob = materialize("plan-review.job.template.json", {
  ...replacements,
  __PLAN_PATH__: planArtifact.path,
  __PLAN_SHA256__: planArtifact.sha256,
});
reviewJob.agent.model = READ_MODEL;
reviewJob.agent.thinking = "high";
reviewJob.agent.sessionId = null;
const reviewRun = runWithRetry(reviewJob, join(tmp, "plan-review.job.json"), join(outRoot, "plan-review"), tmp);
if (reviewRun.result.status !== "completed") fail("plan reviewer did not complete", tmp);
if (reviewRun.result.touchedFiles.length) fail("plan reviewer wrote files", tmp);
if (reviewRun.result.workspace.snapshotBeforeSha256 !== reviewRun.result.workspace.snapshotAfterSha256) {
  fail("plan reviewer snapshot changed", tmp);
}
const reviewPayload = validatePayload("plan-review", reviewRun.result.structuredOutput.payload);
if (!reviewPayload.ok) fail(`plan review payload invalid: ${reviewPayload.error.message}`, tmp);
assertAdapterEvidence(reviewRun.outDir, SUBMIT_TOOLS.plan_review, tmp);

const resumeJob = structuredClone(planJob);
resumeJob.jobId = "job_plan_rework";
resumeJob.idempotencyKey = "task_fixture:plan:2";
resumeJob.attempt = 2;
resumeJob.agent.sessionId = planRun.result.sessionId;
const resumeRun = runWithRetry(resumeJob, join(tmp, "plan-rework.job.json"), join(outRoot, "plan-rework"), tmp);
if (resumeRun.result.status !== "completed") fail("resume planner did not complete", tmp);
if (resumeRun.result.sessionId !== planRun.result.sessionId) {
  fail(`resume session ${resumeRun.result.sessionId} != ${planRun.result.sessionId}`, tmp);
}
assertAdapterEvidence(resumeRun.outDir, SUBMIT_TOOLS.plan, tmp);

const implementJob = materialize("implement.job.template.json", {
  ...replacements,
  __PLAN_PATH__: planArtifact.path,
  __PLAN_SHA256__: planArtifact.sha256,
});
implementJob.agent.model = WRITE_MODEL;
implementJob.agent.thinking = "high";
const implementRun = runWithRetry(
  implementJob,
  join(tmp, "implement.job.json"),
  join(outRoot, "implement"),
  tmp,
  { allowWriteFallback: true },
);
if (implementRun.result.status !== "completed") fail("implementer did not complete", tmp);
if (!implementRun.result.touchedFiles.includes("src/greet.mjs")) {
  fail(`implementer touchedFiles=${JSON.stringify(implementRun.result.touchedFiles)}`, tmp);
}
if (!implementRun.result.checks.length) fail("implementer recorded no checks", tmp);
const implArtifact = implementRun.result.artifacts.find((item) => item.canonical);
if (!implArtifact) fail("implementer missing canonical artifact", tmp);
assertAdapterEvidence(implementRun.outDir, SUBMIT_TOOLS.implement, tmp);
writeFileSync(
  join(tmp, "resolved-model.txt"),
  `${relayResult(implementRun.outDir)?.resolvedModel || implementJob.agent.model}\n`,
);

const execJob = materialize("execute-review.job.template.json", {
  ...replacements,
  __PLAN_PATH__: planArtifact.path,
  __PLAN_SHA256__: planArtifact.sha256,
  __IMPLEMENTATION_PATH__: implArtifact.path,
  __IMPLEMENTATION_SHA256__: implArtifact.sha256,
  __HEAD__: implementRun.result.workspace.headAfter,
});
execJob.workspace.expectedHead = implementRun.result.workspace.headAfter;
execJob.agent.model = READ_MODEL;
execJob.agent.thinking = "high";
execJob.agent.sessionId = null;
const execRun = runWithRetry(execJob, join(tmp, "execute-review.job.json"), join(outRoot, "execute-review"), tmp);
if (execRun.result.status !== "completed") fail("execute reviewer did not complete", tmp);
if (execRun.result.touchedFiles.length) fail("execute reviewer wrote files", tmp);
if (execRun.result.workspace.snapshotBeforeSha256 !== execRun.result.workspace.snapshotAfterSha256) {
  fail("execute reviewer snapshot changed", tmp);
}
const execPayload = validatePayload("execute-review", execRun.result.structuredOutput.payload);
if (!execPayload.ok) fail(`execute review payload invalid: ${execPayload.error.message}`, tmp);
assertAdapterEvidence(execRun.outDir, SUBMIT_TOOLS.execute_review, tmp);

if (reviewRun.result.sessionId === implementRun.result.sessionId) fail("reviewer session collided with implementer", tmp);
if (execRun.result.sessionId === implementRun.result.sessionId) fail("execute reviewer session collided with implementer", tmp);
if (reviewRun.result.sessionId === execRun.result.sessionId) fail("reviewer sessions were not distinct", tmp);
if (resumeRun.result.sessionId === reviewRun.result.sessionId) fail("resume planner session collided with reviewer", tmp);

console.log("PASS real Pi smoke");
console.log(`temp root retained: ${tmp}`);
console.log(`implement resolvedModel=${readFileSync(join(tmp, "resolved-model.txt"), "utf8").trim()}`);
process.exit(0);
