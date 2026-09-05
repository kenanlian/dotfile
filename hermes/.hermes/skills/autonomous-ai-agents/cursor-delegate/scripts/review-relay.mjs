#!/usr/bin/env node
/**
 * delegate-skills · cursor-delegate · review-relay.mjs
 *
 * Deterministic wrapper around relay.mjs for persisted external review.
 * Public CLI (frozen): --cd --artifact --model [--session]
 * Contract on stdin; C6 receipt on stdout. Writable paths are derived.
 *
 * Usage:
 *   node review-relay.mjs --cd <repo> --artifact <path> --model <id> [--session <id>]
 */

import { spawnSync } from "node:child_process";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const COMPACT_DELIM = "===COMPACT===";
const REPORT_DELIM = "===REPORT===";
const BINDING_NAME = "binding.json";
const RESULT_NAME = "result.json";

const WHITELIST_PLAN_REVIEW = /^\.dev\/plan-review\/[^/]+\/round-[^/]*-review\.md$/;
const WHITELIST_REVIEW = /^\.dev\/review\/[^/]+\/round-[^/]*-[^/]*\.md$/;
const RAW_ARTIFACT_FIELD = /^[ \t]*(?:[-*][ \t]+)?`?Raw Review Artifact`?[ \t]*:[ \t]*(.+?)\s*$/;

export {
  COMPACT_DELIM,
  REPORT_DELIM,
  BINDING_NAME,
  parseArgs,
  normalizeArtifact,
  matchesWhitelist,
  approvedWriteRoots,
  resolveCanonical,
  isPathContained,
  validateWritePaths,
  deriveTransportDir,
  extractRawReviewArtifact,
  checkFreshIdentity,
  checkResumeBinding,
  checkIdentity,
  splitEnvelope,
  renderReceipt,
  parseAgentModels,
  normalizeModelLabel,
  modelsMatch,
  decideOutcome,
  writeArtifactExclusive,
  run,
};

function usageError(message) {
  return { ok: false, error: message, exitCode: 2 };
}

function parseArgs(argv) {
  const opts = { cd: null, artifact: null, model: null, session: null };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (value === undefined || value === "") {
        return { error: `${arg} requires a value` };
      }
      i += 1;
      return { value };
    };
    switch (arg) {
      case "--cd":
      case "--artifact":
      case "--model":
      case "--session": {
        const got = next();
        if (got.error) return usageError(got.error);
        const key = arg.slice(2);
        opts[key] = got.value;
        break;
      }
      default:
        return usageError(`unknown option: ${arg}`);
    }
  }
  if (!opts.cd) return usageError("missing --cd");
  if (!opts.artifact) return usageError("missing --artifact");
  if (!opts.model) return usageError("missing --model");
  return { ok: true, ...opts };
}

function normalizeArtifact(cd, artifact) {
  if (typeof cd !== "string" || cd === "" || typeof artifact !== "string" || artifact === "") {
    return { ok: false, error: "artifact is not lexically under --cd" };
  }
  if (cd.includes("\0") || artifact.includes("\0")) {
    return { ok: false, error: "artifact is not lexically under --cd" };
  }
  const cdLexical = resolve(cd);
  const artifactLexical = isAbsolute(artifact) ? resolve(artifact) : resolve(cdLexical, artifact);
  const relToCd = relative(cdLexical, artifactLexical);
  if (relToCd === "" || relToCd.startsWith("..") || isAbsolute(relToCd)) {
    return { ok: false, error: "artifact is not lexically under --cd" };
  }
  const posixRel = relToCd.split(sep).join("/");
  if (posixRel.split("/").some((seg) => seg === ".." || seg === ".")) {
    return { ok: false, error: "artifact is not lexically under --cd" };
  }
  const relativeForm = isAbsolute(artifact) ? posixRel : artifact.split(sep).join("/");
  return { ok: true, relative: relativeForm, lexicalAbs: artifactLexical };
}

function matchesWhitelist(relativePath) {
  if (typeof relativePath !== "string" || relativePath === "") return false;
  const posix = relativePath.split(sep).join("/");
  if (posix.split("/").some((seg) => seg === "" || seg === "." || seg === "..")) return false;
  return WHITELIST_PLAN_REVIEW.test(posix) || WHITELIST_REVIEW.test(posix);
}

function approvedWriteRoots(cd) {
  const cdAbs = resolve(cd);
  const roots = [realpathSync(cdAbs)];
  const dev = join(cdAbs, ".dev");
  try {
    if (lstatSync(dev).isSymbolicLink()) {
      roots.push(realpathSync(dev));
    }
  } catch {
    // .dev missing or unreadable: only realpath(--cd)
  }
  return [...new Set(roots)];
}

function resolveCanonical(inputPath) {
  const abs = resolve(inputPath);
  const root = abs.startsWith(sep) ? sep : abs.slice(0, abs.indexOf(sep) + 1) || sep;
  const segments = abs.slice(root.length).split(sep).filter(Boolean);
  let current = root === sep ? sep : abs.slice(0, root.length);
  if (root === sep) current = sep;
  for (let i = 0; i < segments.length; i += 1) {
    const next = join(current, segments[i]);
    if (existsSync(next)) {
      current = realpathSync(next);
    } else {
      current = join(current, ...segments.slice(i));
      break;
    }
  }
  return current;
}

function isPathContained(canonicalPath, roots) {
  if (typeof canonicalPath !== "string" || !Array.isArray(roots)) return false;
  const candidate = resolve(canonicalPath);
  return roots.some((root) => {
    const base = resolve(root);
    if (candidate === base) return true;
    const prefix = base.endsWith(sep) ? base : `${base}${sep}`;
    return candidate.startsWith(prefix);
  });
}

function deriveTransportDir(artifactAbs) {
  return join(dirname(artifactAbs), "transport");
}

function validateWritePaths(cd, artifact) {
  const cdAbs = resolve(cd);
  try {
    if (!existsSync(cdAbs) || !statSync(cdAbs).isDirectory()) {
      return { ok: false, error: "--cd is not an existing directory", exitCode: 2 };
    }
  } catch {
    return { ok: false, error: "--cd is not an existing directory", exitCode: 2 };
  }

  const normalized = normalizeArtifact(cd, artifact);
  if (!normalized.ok) return { ok: false, error: normalized.error, exitCode: 2 };
  if (!matchesWhitelist(normalized.relative)) {
    return { ok: false, error: "artifact is not a whitelisted audit path", exitCode: 2 };
  }

  let roots;
  try {
    roots = approvedWriteRoots(cd);
  } catch (error) {
    return { ok: false, error: `cannot resolve approved write roots: ${error.message}`, exitCode: 2 };
  }

  let artifactCanonical;
  let transportCanonical;
  const transportDir = deriveTransportDir(normalized.lexicalAbs);
  try {
    artifactCanonical = resolveCanonical(normalized.lexicalAbs);
    transportCanonical = resolveCanonical(transportDir);
  } catch (error) {
    return { ok: false, error: `cannot resolve writable path: ${error.message}`, exitCode: 2 };
  }

  if (!isPathContained(artifactCanonical, roots) || !isPathContained(transportCanonical, roots)) {
    return { ok: false, error: "writable path escapes approved write roots", exitCode: 2 };
  }

  return {
    ok: true,
    relative: normalized.relative,
    artifactAbs: normalized.lexicalAbs,
    artifactCanonical,
    transportDir,
    transportCanonical,
    roots,
  };
}

function extractRawReviewArtifact(text) {
  if (typeof text !== "string") return null;
  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    const match = RAW_ARTIFACT_FIELD.exec(line);
    if (match) return match[1];
  }
  return null;
}

function checkFreshIdentity(stdin, artifactArg) {
  const value = extractRawReviewArtifact(stdin);
  if (value === null) {
    return { ok: false, reason: "missing Raw Review Artifact field" };
  }
  if (value !== artifactArg) {
    return { ok: false, reason: "Raw Review Artifact does not match --artifact" };
  }
  return { ok: true, value };
}

function checkResumeBinding(binding, { session, artifact, cd }) {
  if (!binding || typeof binding !== "object") {
    return { ok: false, reason: "missing binding.json" };
  }
  if (binding.sessionId !== session || binding.artifact !== artifact || binding.cd !== cd) {
    return { ok: false, reason: "binding.json identity mismatch" };
  }
  return { ok: true };
}

function checkIdentity({ session, artifact, cd, stdin, binding }) {
  if (session) return checkResumeBinding(binding, { session, artifact, cd });
  return checkFreshIdentity(stdin, artifact);
}

function splitEnvelope(message) {
  if (typeof message !== "string") return { ok: false, error: "missing finalMessage" };
  const lines = message.split(/\r?\n/);
  let first = 0;
  while (first < lines.length && lines[first].trim() === "") first += 1;
  const compactIdx = [];
  const reportIdx = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (lines[i] === COMPACT_DELIM) compactIdx.push(i);
    if (lines[i] === REPORT_DELIM) reportIdx.push(i);
  }
  if (compactIdx.length !== 1 || reportIdx.length !== 1) {
    return { ok: false, error: "envelope delimiter count or identity is invalid" };
  }
  if (compactIdx[0] !== first) {
    return { ok: false, error: "envelope does not start with ===COMPACT===" };
  }
  if (compactIdx[0] >= reportIdx[0]) {
    return { ok: false, error: "envelope section order is invalid" };
  }
  return {
    ok: true,
    compact: lines.slice(compactIdx[0] + 1, reportIdx[0]).join("\n"),
    report: lines.slice(reportIdx[0] + 1).join("\n"),
  };
}

function renderReceipt({
  outcome,
  artifact,
  session,
  model,
  artifactWritten,
  modelMatch,
  blockers,
  compact,
}) {
  const lines = [
    `Outcome: ${outcome}`,
    `Artifact: ${artifact}`,
    `Session: ${session ? session : "None"}`,
    `Model: ${model ? model : "None"}`,
    "Verification:",
    `  - artifact-written: ${artifactWritten ? "PASS" : "FAIL"}`,
    `  - model-match: ${modelMatch ? "PASS" : "FAIL"}`,
    `Blockers: ${blockers ? blockers : "None"}`,
  ];
  let text = `${lines.join("\n")}\n`;
  if (typeof compact === "string") {
    text += `---\n${compact}`;
    if (!compact.endsWith("\n")) text += "\n";
  }
  return text;
}

function summarizeResult(result, relayStatus) {
  if (!result) return `missing result.json (relay exit ${relayStatus ?? "unknown"})`;
  const bits = [`status=${result.status ?? "missing"}`];
  if (result.exitCode != null) bits.push(`exitCode=${result.exitCode}`);
  if (result.error) bits.push(String(result.error).replace(/\s+/g, " ").slice(0, 160));
  return bits.join(" ");
}

function hasField(object, key) {
  return object != null && Object.prototype.hasOwnProperty.call(object, key);
}

const CATALOG_STATUS_MARKER = /\s+\((current|default|selected|active)\)\s*$/i;

function normalizeModelLabel(label) {
  if (typeof label !== "string") return "";
  return label.replace(CATALOG_STATUS_MARKER, "").trim();
}

function parseAgentModels(text) {
  const map = new Map();
  if (typeof text !== "string") return map;
  for (const line of text.split(/\r?\n/)) {
    const match = /^(\S+)\s+-\s+(.+?)\s*$/.exec(line.trim());
    if (match) map.set(match[1], normalizeModelLabel(match[2]));
  }
  return map;
}

function defaultLookupModelLabel(slug) {
  const child = spawnSync("agent", ["models"], {
    encoding: "utf8",
    timeout: 20_000,
    maxBuffer: 2 * 1024 * 1024,
  });
  if (child.status !== 0) return null;
  return parseAgentModels(child.stdout || "").get(slug) ?? null;
}

const EFFORT_TIER_SUFFIX = /-(low|medium|high|xhigh)(?:-fast)?$/;

function parseEffortTier(slug) {
  if (typeof slug !== "string") return null;
  const match = EFFORT_TIER_SUFFIX.exec(slug);
  return match ? match[1] : null;
}

function modelsMatch(requested, resolved, lookupLabel) {
  if (typeof requested !== "string" || typeof resolved !== "string") return false;
  if (resolved === requested) return true;
  if (typeof lookupLabel !== "function") return false;
  const label = lookupLabel(requested);
  if (typeof label !== "string" || label === "") return false;
  if (resolved === label) return true;
  const tier = parseEffortTier(requested);
  if (!tier) return false;
  const prefix = `${label} `;
  if (!resolved.startsWith(prefix)) return false;
  return resolved.slice(prefix.length).toLowerCase() === tier;
}

function decideOutcome({ result, requestedModel, artifactExists, relayStatus, lookupLabel }) {
  if (relayStatus === 127) {
    return {
      outcome: "blocked",
      exitCode: 127,
      writeArtifact: false,
      persistBinding: false,
      modelMatch: false,
      artifactWritten: false,
      compact: null,
      report: null,
      blockers: "agent binary missing",
      session: result && result.sessionId ? result.sessionId : null,
      model: result && result.resolvedModel ? result.resolvedModel : null,
    };
  }

  if (!result || typeof result !== "object") {
    return {
      outcome: "blocked",
      exitCode: 1,
      writeArtifact: false,
      persistBinding: false,
      modelMatch: false,
      artifactWritten: false,
      compact: null,
      report: null,
      blockers: summarizeResult(null, relayStatus),
      session: null,
      model: null,
    };
  }

  const missing = [];
  if (!hasField(result, "status")) missing.push("status");
  if (!hasField(result, "resolvedModel")) missing.push("resolvedModel");
  if (!hasField(result, "finalMessage")) missing.push("finalMessage");
  if (!hasField(result, "sessionId")) missing.push("sessionId");
  if (missing.length) {
    return {
      outcome: "blocked",
      exitCode: 1,
      writeArtifact: false,
      persistBinding: false,
      modelMatch: false,
      artifactWritten: false,
      compact: null,
      report: null,
      blockers: `result.json missing fields: ${missing.join(", ")}`,
      session: hasField(result, "sessionId") ? result.sessionId : null,
      model: hasField(result, "resolvedModel") ? result.resolvedModel : null,
    };
  }

  const session = result.sessionId || null;
  const model = result.resolvedModel || null;

  if (relayStatus != null && relayStatus !== 0) {
    return {
      outcome: "blocked",
      exitCode: 1,
      writeArtifact: false,
      persistBinding: false,
      modelMatch: false,
      artifactWritten: false,
      compact: null,
      report: null,
      blockers: summarizeResult(result, relayStatus),
      session,
      model,
    };
  }

  if (result.status !== "completed") {
    return {
      outcome: "blocked",
      exitCode: 1,
      writeArtifact: false,
      persistBinding: false,
      modelMatch: false,
      artifactWritten: false,
      compact: null,
      report: null,
      blockers: summarizeResult(result, relayStatus),
      session,
      model,
    };
  }

  const expectedLabel = typeof lookupLabel === "function" ? lookupLabel(requestedModel) : null;
  const modelMatch = modelsMatch(requestedModel, result.resolvedModel, () => expectedLabel);
  if (!modelMatch) {
    const expected = expectedLabel ? `${requestedModel} (label ${expectedLabel})` : requestedModel;
    return {
      outcome: "blocked",
      exitCode: 1,
      writeArtifact: false,
      persistBinding: false,
      modelMatch: false,
      artifactWritten: false,
      compact: null,
      report: null,
      blockers: `resolvedModel ${result.resolvedModel == null ? "None" : result.resolvedModel} != requested ${expected}`,
      session,
      model,
    };
  }

  if (!result.sessionId) {
    return {
      outcome: "blocked",
      exitCode: 1,
      writeArtifact: false,
      persistBinding: false,
      modelMatch: true,
      artifactWritten: false,
      compact: null,
      report: null,
      blockers: "result.json missing sessionId",
      session: null,
      model,
    };
  }

  const envelope = splitEnvelope(result.finalMessage);
  if (!envelope.ok) {
    return {
      outcome: "invalid-return",
      exitCode: 1,
      writeArtifact: false,
      persistBinding: true,
      modelMatch: true,
      artifactWritten: false,
      compact: null,
      report: null,
      blockers: envelope.error,
      session,
      model,
    };
  }

  if (artifactExists) {
    return {
      outcome: "persistence-failure",
      exitCode: 1,
      writeArtifact: false,
      persistBinding: true,
      modelMatch: true,
      artifactWritten: false,
      compact: null,
      report: null,
      blockers: "artifact already exists",
      session,
      model,
    };
  }

  return {
    outcome: "completed",
    exitCode: 0,
    writeArtifact: true,
    persistBinding: true,
    modelMatch: true,
    artifactWritten: true,
    compact: envelope.compact,
    report: envelope.report,
    blockers: null,
    session,
    model,
  };
}

function writeArtifactExclusive(file, content) {
  try {
    writeFileSync(file, content, { encoding: "utf8", flag: "wx" });
    return { ok: true };
  } catch (error) {
    if (error && error.code !== "EEXIST") {
      try {
        if (existsSync(file)) unlinkSync(file);
      } catch {
        // best-effort: do not leave a partial artifact
      }
    }
    return { ok: false, error };
  }
}

function writeBinding(transportDir, { sessionId, artifact, cd }) {
  mkdirSync(transportDir, { recursive: true });
  writeFileSync(
    join(transportDir, BINDING_NAME),
    `${JSON.stringify({ sessionId, artifact, cd }, null, 2)}\n`,
    "utf8",
  );
}

function readBindingFile(transportDir) {
  const file = join(transportDir, BINDING_NAME);
  if (!existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return { invalid: true };
  }
}

function readResultFile(transportDir) {
  const file = join(transportDir, RESULT_NAME);
  if (!existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function defaultSpawnRelay({ model, cd, session, outDir, stdin }) {
  const relay = join(dirname(fileURLToPath(import.meta.url)), "relay.mjs");
  const args = [relay, "--read-only", "--model", model, "--cd", cd];
  if (session) args.push("--session", session);
  args.push("--out-dir", outDir);
  const child = spawnSync(process.execPath, args, {
    input: stdin,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  return {
    status: child.status,
    error: child.error,
    stdout: child.stdout,
    stderr: child.stderr,
  };
}

function contractViolationResult(artifact, blockers) {
  return {
    exitCode: 2,
    stdout: renderReceipt({
      outcome: "contract-violation",
      artifact,
      session: null,
      model: null,
      artifactWritten: false,
      modelMatch: false,
      blockers,
      compact: null,
    }),
    stderr: "",
    spawned: false,
  };
}

function run(argv, stdin, deps = {}) {
  const spawnRelay = deps.spawnRelay || defaultSpawnRelay;
  const lookupLabel = Object.prototype.hasOwnProperty.call(deps, "lookupLabel")
    ? deps.lookupLabel
    : defaultLookupModelLabel;
  let spawned = false;

  const parsed = parseArgs(argv);
  if (!parsed.ok) {
    return {
      exitCode: 2,
      stdout: "",
      stderr: `review-relay: ${parsed.error}\n`,
      spawned: false,
    };
  }

  const paths = validateWritePaths(parsed.cd, parsed.artifact);
  if (!paths.ok) {
    return {
      exitCode: 2,
      stdout: "",
      stderr: `review-relay: ${paths.error}\n`,
      spawned: false,
    };
  }

  const binding = parsed.session ? readBindingFile(paths.transportDir) : null;
  const identity = checkIdentity({
    session: parsed.session,
    artifact: parsed.artifact,
    cd: parsed.cd,
    stdin,
    binding: binding && binding.invalid ? null : binding,
  });
  if (!identity.ok) {
    return contractViolationResult(parsed.artifact, identity.reason);
  }

  const child = spawnRelay({
    model: parsed.model,
    cd: parsed.cd,
    session: parsed.session,
    outDir: paths.transportDir,
    stdin,
  });
  spawned = true;

  const relayStatus = child && child.error && child.error.code === "ENOENT"
    ? 127
    : (child && child.status);
  const stderr = (child && child.stderr) || "";

  if (relayStatus === 127) {
    return { exitCode: 127, stdout: "", stderr, spawned };
  }

  const result = readResultFile(paths.transportDir);
  const artifactExists = existsSync(paths.artifactAbs);
  const decision = decideOutcome({
    result,
    requestedModel: parsed.model,
    artifactExists,
    relayStatus,
    lookupLabel,
  });

  if (decision.persistBinding && decision.session) {
    writeBinding(paths.transportDir, {
      sessionId: decision.session,
      artifact: parsed.artifact,
      cd: parsed.cd,
    });
  }

  let outcome = decision.outcome;
  let exitCode = decision.exitCode;
  let artifactWritten = false;
  let blockers = decision.blockers;
  let compact = decision.compact;

  if (decision.writeArtifact) {
    const written = writeArtifactExclusive(paths.artifactAbs, decision.report);
    if (written.ok) {
      artifactWritten = true;
    } else {
      outcome = "persistence-failure";
      exitCode = 1;
      artifactWritten = false;
      compact = null;
      blockers = written.error && written.error.code === "EEXIST"
        ? "artifact already exists"
        : "artifact write failed";
    }
  }

  const stdout = renderReceipt({
    outcome,
    artifact: parsed.artifact,
    session: decision.session,
    model: decision.model,
    artifactWritten,
    modelMatch: decision.modelMatch,
    blockers,
    compact: outcome === "completed" ? compact : null,
  });

  return { exitCode, stdout, stderr, spawned };
}

function readStdin() {
  try {
    return readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function invokedAsCli() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    return pathToFileURL(realpathSync(entry)).href === import.meta.url;
  } catch {
    try {
      return pathToFileURL(resolve(entry)).href === import.meta.url;
    } catch {
      return false;
    }
  }
}

if (invokedAsCli()) {
  const result = run(process.argv.slice(2), readStdin());
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.stdout) process.stdout.write(result.stdout);
  process.exit(result.exitCode);
}
