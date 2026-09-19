#!/usr/bin/env node
/**
 * Real Cursor smoke for coding-agent-harness.
 *
 * Creates an independent fixture Git repo under the system temp directory,
 * preflights the authenticated Cursor CLI, then runs three acceptance
 * scenarios: A read-only plan, B write direct_implement, C missing→recovery.
 * Temp roots are kept for audit. Never mutates ~/.cursor/mcp.json or
 * ~/.cursor/skills.
 */
import { spawn, spawnSync } from "node:child_process";
import {
  existsSync,
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { parseCanonicalArtifact, SUBMIT_TOOLS, validatePayload } from "../src/contracts.mjs";
import { listAttempts } from "../extensions/cursor-stage-submit/server.mjs";
import { classifySubmissions } from "../src/cursor-submit-bridge.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const HARNESS = join(ROOT, "scripts", "harness.mjs");
const FIXTURE_REPO = join(ROOT, "tests", "fixtures", "repo");
const JOBS = join(ROOT, "tests", "fixtures", "jobs");
const SKILLS_SRC = "/Users/kenan/Secret-Projects/agent_skills/skills";
const DEFAULT_MODEL = "cursor-grok-4.6-high";
const MODEL = process.env.SMOKE_CURSOR_MODEL || DEFAULT_MODEL;
const PROBE_MODEL = process.env.SMOKE_CURSOR_PROBE_MODEL || "composer-2.5-fast";
const JOB_TIMEOUT_SECONDS = Number(process.env.SMOKE_CURSOR_TIMEOUT_SECONDS || 1200);
const SPAWN_TIMEOUT_MS = 35 * 60 * 1000;
const AGENT_BIN = process.env.CURSOR_AGENT_BIN || "agent";

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

function readJson(path) {
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8"));
}

function readJsonl(path) {
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return { _unparsed: line };
      }
    });
}

function flagValue(argv, flag) {
  const index = argv.indexOf(flag);
  if (index < 0) return null;
  return argv[index + 1] ?? null;
}

function hermeticEnv(extra = {}) {
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (key.startsWith("PI_STUB_") || key.startsWith("PI_AUTO_HANDOFF_") || key.startsWith("CURSOR_STUB_")) {
      delete env[key];
    }
  }
  delete env.PI_BIN;
  delete env.PI_DELEGATE_AGENT_ROOT;
  delete env.CURSOR_AGENT_BIN;
  delete env.CURSOR_SMOKE_SUPPRESS_TOOL;
  Object.assign(env, extra);
  return env;
}

function spawnAgent(args, { cwd, env, timeoutMs = 180_000, input = null } = {}) {
  return spawnSync(AGENT_BIN, args, {
    cwd,
    env: hermeticEnv(env),
    encoding: "utf8",
    timeout: timeoutMs,
    maxBuffer: 32 * 1024 * 1024,
    stdio: input == null ? ["ignore", "pipe", "pipe"] : ["pipe", "pipe", "pipe"],
    input: input == null ? undefined : input,
  });
}

function runHarness(jobPath, outDir, extraEnv = {}) {
  mkdirSync(outDir, { recursive: true });
  console.log(`RUN job=${jobPath} out=${outDir}`);
  const spawned = spawnSync(process.execPath, [HARNESS, "run", "--job", jobPath, "--out-dir", outDir], {
    encoding: "utf8",
    timeout: SPAWN_TIMEOUT_MS,
    maxBuffer: 32 * 1024 * 1024,
    stdio: ["ignore", "pipe", "pipe"],
    env: hermeticEnv(extraEnv),
  });
  if (spawned.stdout) process.stdout.write(spawned.stdout);
  if (spawned.stderr) process.stderr.write(spawned.stderr);
  const resultPath = join(outDir, "result.json");
  const result = readJson(resultPath);
  if (!result) {
    console.log(`  missing result.json exit=${spawned.status}`);
    return {
      spawned,
      result: { status: "failed", error: { kind: "adapter_failed", message: spawned.stderr || "missing result.json" } },
      resultPath,
      outDir,
    };
  }
  console.log(`  status=${result.status} exit=${spawned.status} session=${result.sessionId} error=${result.error?.kind || "null"}`);
  console.log(`  result=${resultPath}`);
  console.log(`  resolvedModel=${result.resolvedModel || "unknown"}`);
  if (result.artifacts?.length) {
    for (const artifact of result.artifacts) console.log(`  artifact=${artifact.path}`);
  }
  return { spawned, result, resultPath, outDir };
}

function runWithRetry(job, jobPath, outDir, tmp, extraEnv = {}) {
  writeJob(jobPath, job);
  console.log(`JOB ${job.stage} model=${job.agent.model} thinking=${job.agent.thinking} session=${job.agent.sessionId}`);
  let attempt = runHarness(jobPath, outDir, extraEnv);
  if (attempt.result.status === "completed") return attempt;
  if (isAuthFailure(attempt.result)) {
    fail(`Cursor/auth unavailable (${attempt.result.error?.message || "auth failure"})`, tmp);
  }
  if (isTransient(attempt.result)) {
    console.log("  transient failure; retrying the same Job once");
    attempt = runHarness(jobPath, `${outDir}-retry`, extraEnv);
    if (attempt.result.status === "completed") return attempt;
    if (isAuthFailure(attempt.result)) {
      fail("Cursor/auth unavailable on retry", tmp);
    }
  }
  return attempt;
}

function fail(message, tmp) {
  console.error(`FAIL: ${message}`);
  if (tmp) console.error(`temp root retained: ${tmp}`);
  process.exit(1);
}

function blocker(message, tmp) {
  console.error(`BLOCKER: ${message}`);
  if (tmp) console.error(`temp root retained: ${tmp}`);
  process.exit(2);
}

function readSpawnRecord(outDir, phase = "primary") {
  const path = join(outDir, "adapter", phase, "spawn-record.json");
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8"));
}

function eventTypes(outDir) {
  return readJsonl(join(outDir, "events.jsonl")).map((event) => event.type).filter(Boolean);
}

function submitClassification(outDir, phase = "primary") {
  return classifySubmissions(join(outDir, "adapter", phase, "submit"));
}

function assertNormalizedEvents(outDir, tmp, label) {
  const types = eventTypes(outDir);
  for (const expected of ["agent_session_started", "stage_message", "agent_settled"]) {
    if (!types.includes(expected)) {
      fail(`${label}: missing ${expected} in events (${types.join(",") || "empty"})`, tmp);
    }
  }
}

function exposeProjectSkills(repo) {
  const destRoot = join(repo, ".cursor", "skills");
  mkdirSync(destRoot, { recursive: true });
  const copied = [];
  for (const name of ["write-plan", "delegate-work"]) {
    const src = join(SKILLS_SRC, name);
    if (!existsSync(join(src, "SKILL.md"))) {
      throw new Error(`skill source missing: ${src}/SKILL.md`);
    }
    cpSync(src, join(destRoot, name), { recursive: true });
    copied.push(name);
  }
  return { destRoot, copied };
}

function writeEchoPlugin(dir) {
  mkdirSync(dir, { recursive: true });
  const handshakePath = join(dir, "handshake.jsonl");
  const serverPath = join(dir, "echo-server.mjs");
  writeFileSync(serverPath, `#!/usr/bin/env node
import { appendFileSync } from "node:fs";
const logPath = ${JSON.stringify(handshakePath)};
function send(msg) { process.stdout.write(JSON.stringify(msg) + "\\n"); }
function log(entry) { appendFileSync(logPath, JSON.stringify({ t: new Date().toISOString(), ...entry }) + "\\n"); }
let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buf += chunk;
  while (true) {
    const nl = buf.indexOf("\\n");
    if (nl < 0) break;
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    log({ method: msg.method, id: msg.id });
    if (msg.method === "initialize") {
      send({ jsonrpc: "2.0", id: msg.id, result: { protocolVersion: msg.params?.protocolVersion || "2024-11-05", capabilities: { tools: {} }, serverInfo: { name: "echo-probe", version: "0.0.1" } } });
    } else if (msg.method === "tools/list" || msg.method === "tools-list") {
      send({ jsonrpc: "2.0", id: msg.id, result: { tools: [{ name: "echo_probe", description: "Echo a token", inputSchema: { type: "object", properties: { token: { type: "string" } } } }] } });
    } else if (msg.method === "tools/call" || msg.method === "tools-call") {
      send({ jsonrpc: "2.0", id: msg.id, result: { content: [{ type: "text", text: "ECHO_OK" }] } });
    } else if (msg.id !== undefined) {
      send({ jsonrpc: "2.0", id: msg.id, result: {} });
    }
  }
});
`);
  writeFileSync(join(dir, "plugin.json"), `${JSON.stringify({
    $schema: "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
    name: "echo-probe",
    version: "0.0.1",
    description: "Throwaway echo MCP for --plugin-dir smoke preflight",
  }, null, 2)}\n`);
  writeFileSync(join(dir, "mcp.json"), `${JSON.stringify({
    mcpServers: {
      "echo-probe": {
        type: "stdio",
        command: process.execPath,
        args: [serverPath],
      },
    },
  }, null, 2)}\n`);
  writeFileSync(handshakePath, "");
  return { handshakePath, serverPath };
}

function preflight(tmp, repoRoot) {
  const evidence = {
    version: null,
    status: null,
    model: MODEL,
    modelListed: false,
    pluginDirHelp: false,
    pluginDirProbe: null,
    globalSkills: existsSync(join(homedir(), ".cursor", "skills")),
    projectSkills: null,
    skillProbe: null,
  };

  const version = spawnAgent(["--version"], { cwd: repoRoot, timeoutMs: 30_000 });
  evidence.version = (version.stdout || version.stderr || "").trim();
  console.log(`PREFLIGHT version=${evidence.version || "unknown"} exit=${version.status}`);
  if (version.status !== 0 || !evidence.version) {
    blocker(`agent --version failed: ${version.stderr || version.stdout}`, tmp);
  }

  const status = spawnAgent(["status"], { cwd: repoRoot, timeoutMs: 30_000 });
  evidence.status = (status.stdout || status.stderr || "").trim();
  console.log(`PREFLIGHT status=${evidence.status.split("\n")[0]}`);
  if (status.status !== 0 || /not logged|unauthor/i.test(evidence.status)) {
    blocker(`agent status not authenticated: ${evidence.status}`, tmp);
  }

  const help = spawnAgent(["--help"], { cwd: repoRoot, timeoutMs: 30_000 });
  const helpText = `${help.stdout || ""}\n${help.stderr || ""}`;
  evidence.pluginDirHelp = /--plugin-dir/.test(helpText);
  if (!evidence.pluginDirHelp) blocker("agent --help missing --plugin-dir", tmp);
  if (!/--list-models/.test(helpText)) blocker("agent --help missing --list-models", tmp);

  const models = spawnAgent(["--list-models"], { cwd: repoRoot, timeoutMs: 60_000 });
  const modelText = `${models.stdout || ""}\n${models.stderr || ""}`;
  evidence.modelListed = modelText.split("\n").some((line) => line.includes(MODEL));
  console.log(`PREFLIGHT model=${MODEL} listed=${evidence.modelListed}`);
  if (!evidence.modelListed) {
    blocker(`chosen model ${MODEL} not in agent --list-models output`, tmp);
  }

  const pluginDir = join(tmp, "plugin-dir-probe");
  const echo = writeEchoPlugin(pluginDir);
  const pluginRepo = join(tmp, "plugin-probe-repo");
  mkdirSync(pluginRepo, { recursive: true });
  git(pluginRepo, ["init", "-b", "main"]);
  writeFileSync(join(pluginRepo, "README.md"), "plugin-dir probe\n");
  git(pluginRepo, ["add", "."]);
  git(pluginRepo, ["-c", "user.email=smoke@example.com", "-c", "user.name=Smoke", "commit", "-m", "init"]);
  const pluginRun = spawnAgent([
    "--print",
    "--output-format", "text",
    "--mode", "ask",
    "--trust",
    "--approve-mcps",
    "--plugin-dir", pluginDir,
    "--workspace", pluginRepo,
    "--model", PROBE_MODEL,
    "This is a plugin-dir probe. If the echo_probe MCP tool is available, call it with token=PLUGIN_DIR_OK then reply PLUGIN_DIR_OK. If it is not available, reply PLUGIN_DIR_MISSING.",
  ], { cwd: pluginRepo, timeoutMs: 180_000 });
  const pluginOut = `${pluginRun.stdout || ""}\n${pluginRun.stderr || ""}`;
  const handshake = existsSync(echo.handshakePath) ? readFileSync(echo.handshakePath, "utf8") : "";
  evidence.pluginDirProbe = {
    exit: pluginRun.status,
    handshakeBytes: handshake.length,
    handshakeHasInitialize: /"initialize"/.test(handshake),
    handshakeHasToolsList: /tools\/list|tools-list/.test(handshake),
    outputSnippet: pluginOut.slice(0, 500),
  };
  console.log(`PREFLIGHT plugin-dir handshake initialize=${evidence.pluginDirProbe.handshakeHasInitialize} tools/list=${evidence.pluginDirProbe.handshakeHasToolsList}`);
  if (!evidence.pluginDirProbe.handshakeHasInitialize) {
    blocker(`WP-03 plugin-dir probe did not handshake (exit=${pluginRun.status}): ${pluginOut.slice(0, 800)}`, tmp);
  }

  const skillPrompt = `/write-plan

This is an invocation-only smoke test, not a real task. Explicitly load write-plan. As soon as loading is confirmed, stop. Do not inspect the repository, ask questions, create or modify files, run commands or tests, execute the Skill workflow, or invoke another Skill. Return only \`SMOKE_OK write-plan\`; if loading fails, return \`SMOKE_FAIL write-plan\` and one short reason.`;
  const skillRun = spawnAgent([
    "--print",
    "--output-format", "stream-json",
    "--mode", "plan",
    "--trust",
    "--workspace", repoRoot,
    "--model", PROBE_MODEL,
    skillPrompt,
  ], { cwd: repoRoot, timeoutMs: 180_000 });
  const skillOut = `${skillRun.stdout || ""}\n${skillRun.stderr || ""}`;
  const skillPath = join(repoRoot, ".cursor", "skills", "write-plan", "SKILL.md");
  evidence.projectSkills = existsSync(skillPath) ? skillPath : null;
  evidence.skillProbe = {
    exit: skillRun.status,
    sawSmokeOk: /SMOKE_OK write-plan/.test(skillOut),
    sawSmokeFail: /SMOKE_FAIL write-plan/.test(skillOut),
    sawSkillPath: skillOut.includes(skillPath) || skillOut.includes(".cursor/skills/write-plan"),
    outputSnippet: skillOut.slice(0, 800),
  };
  console.log(`PREFLIGHT skills global=${evidence.globalSkills} project=${Boolean(evidence.projectSkills)} smokeOk=${evidence.skillProbe.sawSmokeOk} sawPath=${evidence.skillProbe.sawSkillPath}`);
  if (!evidence.skillProbe.sawSmokeOk && !evidence.skillProbe.sawSkillPath) {
    blocker(
      `entry-skill /write-plan not discoverable (global=${evidence.globalSkills}, project=${evidence.projectSkills}): ${skillOut.slice(0, 1200)}`,
      tmp,
    );
  }

  writeFileSync(join(tmp, "preflight.json"), `${JSON.stringify(evidence, null, 2)}\n`);
  return evidence;
}

const tmp = mkdtempSync(join(tmpdir(), "coding-agent-real-cursor-"));
const repo = join(tmp, "repo");
const outRoot = join(tmp, "out");
mkdirSync(outRoot, { recursive: true });
cpSync(FIXTURE_REPO, repo, { recursive: true });
let skillExposure = { destRoot: null, copied: [] };
try {
  skillExposure = exposeProjectSkills(repo);
} catch (error) {
  blocker(`failed to copy project skills into fixture: ${error instanceof Error ? error.message : error}`, tmp);
}
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
console.log(`project skills: ${skillExposure.copied.join(",")} -> ${skillExposure.destRoot}`);

const evidence = preflight(tmp, repoRoot);

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

function applySmokeJobDefaults(job) {
  job.agent.model = MODEL;
  job.agent.thinking = "high";
  job.limits = { timeoutSeconds: JOB_TIMEOUT_SECONDS };
  return job;
}

// --- Scenario A: read-only plan ---
const planJob = applySmokeJobDefaults(materialize("cursor-plan.job.template.json", replacements));
const planRun = runWithRetry(planJob, join(tmp, "plan.job.json"), join(outRoot, "plan"), tmp);
if (planRun.result.status !== "completed") fail(`scenario A did not complete: ${planRun.result.error?.kind || planRun.result.status} ${planRun.result.error?.message || ""}`, tmp);
if (planRun.result.adapter !== "cursor") fail(`scenario A adapter=${planRun.result.adapter}`, tmp);
if (!planRun.result.resolvedModel) fail("scenario A missing resolvedModel", tmp);
if ((planRun.result.touchedFiles || []).length) {
  fail(`scenario A touchedFiles=${JSON.stringify(planRun.result.touchedFiles)}`, tmp);
}
const planArtifact = planRun.result.artifacts?.find((item) => item.canonical);
if (!planArtifact) fail("scenario A missing canonical artifact", tmp);
const parsedPlan = parseCanonicalArtifact(readFileSync(planArtifact.path, "utf8"), { expectedKind: "plan" });
if (!parsedPlan.ok) fail(`scenario A parseCanonicalArtifact: ${parsedPlan.error?.message}`, tmp);
const aClass = submitClassification(planRun.outDir, "primary");
if (aClass.kind !== "ok" || aClass.attempts.filter((item) => item.outcome === "accepted").length !== 1) {
  fail(`scenario A receipts kind=${aClass.kind} accepted=${aClass.attempts.filter((item) => item.outcome === "accepted").length}`, tmp);
}
if (aClass.accepted?.tool !== SUBMIT_TOOLS.plan) fail(`scenario A tool=${aClass.accepted?.tool}`, tmp);
assertNormalizedEvents(planRun.outDir, tmp, "scenario A");
console.log(`SCENARIO A PASS session=${planRun.result.sessionId} out=${planRun.outDir} resolvedModel=${planRun.result.resolvedModel}`);

// --- Scenario C before B so requireCleanAtStart still holds ---
// Mechanism: the Cursor CLI sanitizes the parent environment of MCP server
// children (verified live: CURSOR_* env vars do not propagate), so the env
// knob cannot reach the bridge on the real path. Instead the smoke watches
// for the primary phase's submit dir (created by the harness BEFORE the relay
// is spawned) and drops the SMOKE_SUPPRESS marker into it. The primary phase
// then records zero attempts, and the harness performs its one same-session
// output-only recovery against a FRESH bridge/submit dir (no marker), which
// completes — exactly the plan's "suppression removed" scenario.
function runHarnessWithPrimaryMarker(jobPath, outDir) {
  return new Promise((resolve) => {
    mkdirSync(outDir, { recursive: true });
    console.log(`RUN job=${jobPath} out=${outDir} (marker on primary submit dir)`);
    const child = spawn(process.execPath, [HARNESS, "run", "--job", jobPath, "--out-dir", outDir], {
      stdio: ["ignore", "pipe", "pipe"],
      env: hermeticEnv(),
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    const primarySubmit = join(outDir, "adapter", "primary", "submit");
    let marked = false;
    const watcher = setInterval(() => {
      if (marked) return;
      if (existsSync(primarySubmit)) {
        marked = true;
        try {
          writeFileSync(join(primarySubmit, "SMOKE_SUPPRESS"), "");
          console.log(`  marker dropped: ${join(primarySubmit, "SMOKE_SUPPRESS")}`);
        } catch (error) {
          console.error(`  marker write failed: ${error instanceof Error ? error.message : error}`);
        }
      }
    }, 10);
    child.on("error", (error) => {
      clearInterval(watcher);
      resolve({ stdout, stderr: `${stderr}${String(error)}`, status: null, markerDropped: marked });
    });
    child.on("close", (code) => {
      clearInterval(watcher);
      if (stdout) process.stdout.write(stdout);
      if (stderr) process.stderr.write(stderr);
      const result = readJson(join(outDir, "result.json"));
      console.log(`  status=${result?.status} exit=${code} session=${result?.sessionId} error=${result?.error?.kind || "null"} marker=${marked}`);
      resolve({ stdout, stderr, status: code, result, resultPath: join(outDir, "result.json"), outDir, markerDropped: marked });
    });
  });
}

const missingJob = applySmokeJobDefaults(materialize("cursor-plan.job.template.json", replacements));
missingJob.jobId = "job_cursor_plan_missing";
missingJob.idempotencyKey = "task_fixture:cursor:plan:missing:1";
const missingJobPath = join(tmp, "plan-missing.job.json");
writeJob(missingJobPath, missingJob);
const missingRun = await runHarnessWithPrimaryMarker(missingJobPath, join(outRoot, "plan-missing"));
if (!missingRun.markerDropped) fail("scenario C marker was never dropped (primary submit dir not observed)", tmp);
if (!missingRun.result) fail("scenario C missing result.json", tmp);
// Scenario C asserts the missing-submit recovery mechanism only. Host-side
// plan.v1 payload coverage (contracts.mjs) remains authoritative; a recovery
// payload that fails coverage is recorded here as a warning, not a smoke
// failure.
const cStatus = missingRun.result.status;
const cErrorKind = missingRun.result.error?.kind;
if (!(cStatus === "completed" || (cStatus === "failed" && cErrorKind === "structured_output_invalid"))) {
  fail(`scenario C recovery mechanism failed: ${cErrorKind || cStatus || "no result"} ${missingRun.result.error?.message || ""}`, tmp);
}
if (cStatus === "failed") {
  console.log(`  scenario C payload validity not asserted (host ${cErrorKind}: ${missingRun.result.error?.message || "no message"})`);
}
const cRuns = missingRun.result.paths?.adapterRuns || [];
if (cRuns.length !== 2) {
  fail(`scenario C expected exactly one recovery (2 adapter runs), got ${cRuns.length}`, tmp);
}
if (cRuns[0].phase !== "primary" || cRuns[1].phase !== "output-recovery") {
  fail(`scenario C phases=${cRuns.map((item) => item.phase).join(",")}`, tmp);
}
const cPrimary = readSpawnRecord(missingRun.outDir, "primary");
const cRecovery = readSpawnRecord(missingRun.outDir, "output-recovery");
if (!cPrimary?.argv || !cRecovery?.argv) fail("scenario C missing spawn-record", tmp);
if (cPrimary.argv.includes("--resume")) fail("scenario C primary should not --resume", tmp);
if (flagValue(cRecovery.argv, "--resume") !== missingRun.result.sessionId) {
  fail(`scenario C recovery --resume ${flagValue(cRecovery.argv, "--resume")} != ${missingRun.result.sessionId}`, tmp);
}
if (flagValue(cRecovery.argv, "--mode") !== "plan") fail(`scenario C recovery mode=${flagValue(cRecovery.argv, "--mode")}`, tmp);
if (cRecovery.argv.includes("--force")) fail("scenario C recovery used --force", tmp);
if (cRecovery.pluginDir === cPrimary.pluginDir) fail("scenario C recovery reused pluginDir", tmp);
if (cRecovery.runNonce === cPrimary.runNonce) fail("scenario C recovery reused runNonce", tmp);
const cPrimaryClass = submitClassification(missingRun.outDir, "primary");
if (cPrimaryClass.kind !== "missing" || listAttempts(join(missingRun.outDir, "adapter", "primary", "submit")).length !== 0) {
  fail(`scenario C primary recorded attempts kind=${cPrimaryClass.kind}`, tmp);
}
// The recovery phase may record rejected bridge attempts (for example a stale
// runNonce) before the agent submits again with the fresh phase binding. The
// mechanism contract here is exactly one accepted, correctly bound receipt;
// rejected attempts are reported but do not by themselves fail this scenario.
const cRecoveryAttempts = listAttempts(join(missingRun.outDir, "adapter", "output-recovery", "submit"));
const cAcceptedAttempts = cRecoveryAttempts.filter((item) => item.record?.outcome === "accepted");
const cRejectedAttempts = cRecoveryAttempts.filter((item) => item.record?.outcome === "rejected");
if (cAcceptedAttempts.length !== 1) {
  fail(`scenario C recovery accepted receipts=${cAcceptedAttempts.length} attempts=${cRecoveryAttempts.map((item) => `${item.seq}:${item.record?.outcome || "unknown"}`).join(",") || "none"}`, tmp);
}
if (cRejectedAttempts.length > 0) {
  console.log(`  scenario C rejected recovery attempt(s) tolerated: ${cRejectedAttempts.map((item) => `${item.seq}:${item.record?.reason || "rejected"}`).join(",")}`);
}
const cAccepted = cAcceptedAttempts[0].record;
if (cAccepted?.tool !== SUBMIT_TOOLS.plan) fail(`scenario C recovery tool=${cAccepted?.tool}`, tmp);
if (cAccepted?.bindingMatches !== true) fail("scenario C recovery receipt binding did not match", tmp);
const cExpectedBinding = {
  jobId: missingJob.jobId,
  jobSha256: missingRun.result.jobSha256,
  stage: "plan",
  expectedTool: SUBMIT_TOOLS.plan,
  runNonce: cRecovery.runNonce,
};
for (const [key, expected] of Object.entries(cExpectedBinding)) {
  if (cAccepted?.binding?.[key] !== expected) {
    fail(`scenario C recovery binding ${key}=${cAccepted?.binding?.[key]} != ${expected}`, tmp);
  }
}
if (!missingRun.result.resolvedModel) fail("scenario C missing resolvedModel", tmp);
assertNormalizedEvents(missingRun.outDir, tmp, "scenario C");
console.log(`SCENARIO C PASS (marker-suppressed primary; one same-session output-only recovery accepted; payload validity not asserted) session=${missingRun.result.sessionId} out=${missingRun.outDir}`);

// --- Scenario B: write direct_implement ---
const directJob = applySmokeJobDefaults(materialize("cursor-direct-implement.job.template.json", replacements));
const directRun = runWithRetry(directJob, join(tmp, "direct.job.json"), join(outRoot, "direct"), tmp);
if (directRun.result.status !== "completed") {
  fail(`scenario B did not complete: ${directRun.result.error?.kind || directRun.result.status} ${directRun.result.error?.message || ""}`, tmp);
}
if (!directRun.result.touchedFiles?.includes("src/greet.mjs")) {
  fail(`scenario B touchedFiles=${JSON.stringify(directRun.result.touchedFiles)}`, tmp);
}
const greetSrc = readFileSync(join(repoRoot, "src", "greet.mjs"), "utf8");
if (!/Hello/.test(greetSrc) || /TODO/.test(greetSrc)) {
  fail(`scenario B src/greet.mjs not implemented: ${greetSrc.trim()}`, tmp);
}
const directPayload = validatePayload("direct-implementation", directRun.result.structuredOutput?.payload);
if (!directPayload.ok) fail(`scenario B payload invalid: ${directPayload.error?.message}`, tmp);
if (directRun.result.structuredOutput?.kind !== "direct-implementation") {
  fail(`scenario B kind=${directRun.result.structuredOutput?.kind}`, tmp);
}
if (!directRun.result.checks?.length) fail("scenario B recorded no checks", tmp);
const unit = directRun.result.checks.find((item) => item.id === "check-unit");
if (!unit || unit.status !== "passed") {
  fail(`scenario B check-unit status=${unit?.status}`, tmp);
}
if (directRun.result.workspace.headAfter !== directRun.result.workspace.headBefore) {
  fail("scenario B postflight HEAD changed", tmp);
}
if (directRun.result.workspace.branchAfter !== "main") fail("scenario B branch changed", tmp);
if (!directRun.result.resolvedModel) fail("scenario B missing resolvedModel", tmp);
assertNormalizedEvents(directRun.outDir, tmp, "scenario B");
const bClass = submitClassification(directRun.outDir, "primary");
if (bClass.kind !== "ok") fail(`scenario B receipts kind=${bClass.kind}`, tmp);
console.log(`SCENARIO B PASS session=${directRun.result.sessionId} out=${directRun.outDir} resolvedModel=${directRun.result.resolvedModel}`);

const summary = {
  tmp,
  repoRoot,
  model: MODEL,
  probeModel: PROBE_MODEL,
  skillExposure,
  preflight: evidence,
  scenarioA: { outDir: planRun.outDir, sessionId: planRun.result.sessionId, resolvedModel: planRun.result.resolvedModel, status: planRun.result.status },
  scenarioB: { outDir: directRun.outDir, sessionId: directRun.result.sessionId, resolvedModel: directRun.result.resolvedModel, status: directRun.result.status, touchedFiles: directRun.result.touchedFiles },
  scenarioC: {
    missingOutDir: missingRun.outDir,
    sessionId: missingRun.result.sessionId,
    status: missingRun.result.status,
    adapterRuns: cRuns.map((item) => item.phase),
    primaryAttempts: cPrimaryClass.attempts.length,
    recoveryAttempts: cRecoveryAttempts.map((item) => `${item.seq}:${item.record?.outcome || "unknown"}`),
    recoveryAccepted: cAcceptedAttempts.length,
    mechanism: "SMOKE_SUPPRESS marker file dropped into the primary submit dir (Cursor CLI sanitizes MCP-child env, verified live); primary records 0 attempts and the harness runs exactly one same-session output-only recovery with a fresh unmarked bridge",
  },
};
writeFileSync(join(tmp, "summary.json"), `${JSON.stringify(summary, null, 2)}\n`);

console.log("PASS real Cursor smoke");
console.log(`temp root retained: ${tmp}`);
console.log(`out-dir roots: A=${planRun.outDir} C=${missingRun.outDir} B=${directRun.outDir}`);
console.log(`skill discovery: global ~/.cursor/skills absent; project .cursor/skills used (${skillExposure.copied.join(", ")})`);
process.exit(0);
