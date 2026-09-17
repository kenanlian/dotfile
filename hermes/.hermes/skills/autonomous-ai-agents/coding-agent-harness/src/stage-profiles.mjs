/**
 * Declarative stage-profile assembly.
 *
 * New profiles are data: add a record to stage-profiles.json. This module
 * stays branch-free on stage names. stage-submit is inherent to every Harness
 * run and is not listed in the JSON.
 *
 * Pi 0.85.1 print/json mode empirically fail-closes on a bad `-e` path
 * (missing, empty dir, or invalid factory) with exit 1 and
 * `Failed to load extension ...` on stderr — it does not warn-and-continue.
 * Attestation is still required: argv presence is not proof that
 * stage-submit actually ran, and a later Pi change could reopen the
 * warn-and-continue path.
 *
 * Skills are a separate axis. `skills.mode=explicit` is all-or-nothing:
 * relay emits `-ns` plus one `--skill` per resolved directory. `mode=auto`
 * adds neither flag (Pi's default discovery). Skill correctness is the
 * golden argv set plus parse-time existence/SKILL.md checks — attestation
 * stays extension-only because stage-submit cannot observe which Skills
 * the CLI loaded, and Pi has no equivalent presence event.
 *
 * Measured Pi 0.85.1 (2026-09-17, `zai-coding-cn/glm-5.3-flash`):
 * `--skill` of a `disable-model-invocation: true` Skill (write-plan) plus
 * `-ns` loads it; `/skill:write-plan ` expansion inlines SKILL.md as
 * `<skill>`, but the Skill does **not** appear in `<available_skills>`.
 * `-ns` without `--skill` drops discovery of `~/.pi/agent/skills` and
 * project `.agents/skills` alike. `skills.inline` makes the Harness brief
 * start with `/skill:<name> ` (trailing space, then newline) so Pi inlines
 * that one Skill into the first message; other mounted Skills stay
 * `--skill` only.
 *
 * Third-party extension tools (todos-tool registers `todo`) ride
 * `toolsExtra` onto the relay `--tools` allowlist. Pi 0.85.1 silently
 * ignores unknown `--tools` names, so listing a tool on `-t` is the
 * allowlist hook, not a load proof.
 */
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { STAGES, typedError } from "./contracts.mjs";
import {
  ATTESTATION_VERSION,
  EXPECT_EXTENSIONS_ENV,
  STAGE_SUBMIT_EXTENSION_ID,
  parseExpectedExtensions,
} from "../extensions/stage-submit/keys.mjs";

export const STAGE_PROFILES_SCHEMA = "coding-agent.stage-profiles.v1";
export const DEFAULT_PROFILES_PATH = join(dirname(fileURLToPath(import.meta.url)), "..", "stage-profiles.json");

export {
  ATTESTATION_VERSION,
  EXPECT_EXTENSIONS_ENV,
  STAGE_SUBMIT_EXTENSION_ID,
};

/** Keys `--env` / profile.env must never override. Mirrored in pi-delegate relay.mjs. */
export const ENV_INJECT_BLACKLIST = Object.freeze([
  "PATH",
  "HOME",
  "USER",
  "LOGNAME",
  "SHELL",
  "TMPDIR",
  "TEMP",
  "TMP",
  "PWD",
  "OLDPWD",
  "NODE_OPTIONS",
  "NODE_PATH",
  "LD_PRELOAD",
  "LD_LIBRARY_PATH",
  "DYLD_INSERT_LIBRARIES",
  "DYLD_LIBRARY_PATH",
  "DYLD_FALLBACK_LIBRARY_PATH",
  "PI_BIN",
  "PI_AUTO_HANDOFF_PLAN_FILE",
  "PI_AUTO_HANDOFF_HANDOFF_DIR",
]);

const ENV_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function expandUserPath(value, home = homedir()) {
  if (typeof value !== "string" || value.length === 0) return value;
  if (value === "~") return home;
  if (value.startsWith("~/")) return join(home, value.slice(2));
  return value;
}

/**
 * Agent Skills repo root (parent of the `skills/` tree). Override with
 * `PI_AGENT_SKILLS_ROOT`. Default: realpath of `~/.pi/agent/skills` (a
 * symlink to `~/Secret-Projects/agent_skills/skills`) then its parent;
 * otherwise `~/Secret-Projects/agent_skills`. Profile `skills.paths`
 * entries such as `skills/write-plan` resolve against this root.
 */
export function resolveAgentSkillsRoot(env = process.env, home = homedir()) {
  const fromEnv = env.PI_AGENT_SKILLS_ROOT;
  if (typeof fromEnv === "string" && fromEnv.length > 0) {
    return resolve(expandUserPath(fromEnv, home));
  }
  const linked = join(home, ".pi", "agent", "skills");
  if (existsSync(linked)) {
    let real;
    try {
      real = realpathSync(linked);
    } catch {
      real = resolve(linked);
    }
    return basename(real) === "skills" ? dirname(real) : real;
  }
  return resolve(expandUserPath("~/Secret-Projects/agent_skills", home));
}

function parseInline(raw, names, profileId) {
  if (!Object.prototype.hasOwnProperty.call(raw, "inline") || raw.inline == null) {
    return { ok: true, value: null };
  }
  if (typeof raw.inline !== "string" || raw.inline.length === 0) {
    return fail("invalid_job", "/stage", `profile ${profileId} skills.inline must be a non-empty string`);
  }
  if (!names.includes(raw.inline)) {
    return fail(
      "invalid_job",
      "/stage",
      `profile ${profileId} skills.inline ${raw.inline} is not in skills.paths`,
    );
  }
  return { ok: true, value: raw.inline };
}

function resolveSkills(profile, profileId, env, home) {
  const raw = profile.skills;
  if (raw == null) {
    return { ok: true, value: { mode: "auto", paths: [], names: [], inline: null, root: null } };
  }
  if (!isPlainObject(raw)) {
    return fail("invalid_job", "/stage", `profile ${profileId} skills must be an object`);
  }
  const mode = raw.mode;
  if (mode !== "explicit" && mode !== "auto") {
    return fail(
      "invalid_job",
      "/stage",
      `profile ${profileId} skills.mode must be explicit or auto`,
    );
  }
  if (mode === "auto") {
    const autoNames = Array.isArray(raw.paths)
      ? raw.paths.filter((item) => typeof item === "string" && item.length > 0).map((item) => basename(item))
      : [];
    const autoInline = parseInline(raw, autoNames, profileId);
    if (!autoInline.ok) return autoInline;
    return { ok: true, value: { mode: "auto", paths: [], names: [], inline: autoInline.value, root: null } };
  }
  if (!Array.isArray(raw.paths)) {
    return fail("invalid_job", "/stage", `profile ${profileId} skills.paths must be an array`);
  }
  const root = resolveAgentSkillsRoot(env, home);
  const paths = [];
  const names = [];
  const seen = new Set();
  for (let i = 0; i < raw.paths.length; i += 1) {
    const item = raw.paths[i];
    if (typeof item !== "string" || item.length === 0) {
      return fail(
        "invalid_job",
        "/stage",
        `profile ${profileId} skills.paths/${i} must be a non-empty string`,
      );
    }
    const resolved = isAbsolute(item) || item.startsWith("~")
      ? resolve(expandUserPath(item, home))
      : resolve(root, item);
    if (!isAbsolute(resolved)) {
      return fail("adapter_failed", "/adapter", `skill path is not absolute: ${item}`);
    }
    if (seen.has(resolved)) {
      return fail("invalid_job", "/stage", `profile ${profileId} duplicate skill path ${item}`);
    }
    seen.add(resolved);
    paths.push(resolved);
    names.push(basename(resolved));
  }
  const inline = parseInline(raw, names, profileId);
  if (!inline.ok) return inline;
  return { ok: true, value: { mode: "explicit", paths, names, inline: inline.value, root } };
}

export function loadProfiles(path = DEFAULT_PROFILES_PATH) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    return {
      ok: false,
      error: typedError("invalid_job", "/stage", `stage-profiles.json is not readable JSON: ${error.message}`),
    };
  }
  if (!isPlainObject(parsed) || parsed.schema !== STAGE_PROFILES_SCHEMA) {
    return {
      ok: false,
      error: typedError("invalid_job", "/stage", `expected ${STAGE_PROFILES_SCHEMA}`),
    };
  }
  if (!isPlainObject(parsed.profiles) || !isPlainObject(parsed.stageToProfile)) {
    return {
      ok: false,
      error: typedError("invalid_job", "/stage", "stage-profiles.json requires profiles and stageToProfile objects"),
    };
  }
  return { ok: true, value: parsed };
}

function fail(kind, path, message, details) {
  return { ok: false, error: typedError(kind, path, message, details) };
}

function resolveEnabledRoot(entry, env, home) {
  const fromEnv = typeof entry.rootEnv === "string" && entry.rootEnv.length > 0
    ? env[entry.rootEnv]
    : undefined;
  const raw = (typeof fromEnv === "string" && fromEnv.length > 0)
    ? fromEnv
    : (typeof entry.root === "string" && entry.root.length > 0
      ? entry.root
      : (typeof entry.rootDefault === "string" && entry.rootDefault.length > 0
        ? entry.rootDefault
        : null));
  if (!raw) {
    return fail("adapter_failed", "/adapter", `enabled extension ${entry.id} has no resolvable root`);
  }
  const resolved = resolve(expandUserPath(raw, home));
  if (!isAbsolute(resolved)) {
    return fail("adapter_failed", "/adapter", `enabled extension ${entry.id} root is not absolute: ${raw}`);
  }
  return { ok: true, value: resolved };
}

export function resolveStageProfile(stage, options = {}) {
  const env = options.env || process.env;
  const home = options.home || homedir();
  const loaded = options.manifest
    ? { ok: true, value: options.manifest }
    : loadProfiles(options.path);
  if (!loaded.ok) return loaded;
  const manifest = loaded.value;

  if (!STAGES.includes(stage)) {
    return fail("invalid_job", "/stage", `unknown stage ${stage}`);
  }
  const profileId = manifest.stageToProfile[stage];
  if (typeof profileId !== "string" || profileId.length === 0) {
    return fail("invalid_job", "/stage", `no stage profile mapping for ${stage}`);
  }
  const profile = manifest.profiles[profileId];
  if (!isPlainObject(profile)) {
    return fail("invalid_job", "/stage", `unknown stage profile ${profileId}`);
  }
  if (!Array.isArray(profile.extensions)) {
    return fail("invalid_job", "/stage", `profile ${profileId} extensions must be an array`);
  }
  if (!isPlainObject(profile.env)) {
    return fail("invalid_job", "/stage", `profile ${profileId} env must be an object`);
  }
  const toolsExtra = [];
  if (profile.toolsExtra !== undefined) {
    if (!Array.isArray(profile.toolsExtra)) {
      return fail("invalid_job", "/stage", `profile ${profileId} toolsExtra must be an array`);
    }
    for (const name of profile.toolsExtra) {
      if (typeof name !== "string" || !/^[a-zA-Z0-9_-]+$/.test(name)) {
        return fail("invalid_job", "/stage", `profile ${profileId} toolsExtra has invalid tool name: ${name}`);
      }
      if (!toolsExtra.includes(name)) toolsExtra.push(name);
    }
  }
  const skills = resolveSkills(profile, profileId, env, home);
  if (!skills.ok) return skills;

  const profileEnv = {};
  for (const [key, value] of Object.entries(profile.env)) {
    if (!ENV_KEY.test(key) || ENV_INJECT_BLACKLIST.includes(key) || key === EXPECT_EXTENSIONS_ENV) {
      return fail("invalid_job", "/stage", `profile ${profileId} env key ${key} is reserved or invalid`);
    }
    if (typeof value !== "string") {
      return fail("invalid_job", "/stage", `profile ${profileId} env ${key} must be a string`);
    }
    profileEnv[key] = value;
  }

  const extensionRoots = [];
  const disabledEntries = [];
  const seenIds = new Set();
  for (let i = 0; i < profile.extensions.length; i += 1) {
    const entry = profile.extensions[i];
    if (!isPlainObject(entry) || typeof entry.id !== "string" || entry.id.length === 0) {
      return fail("invalid_job", "/stage", `profile ${profileId} extensions/${i} requires id`);
    }
    if (seenIds.has(entry.id)) {
      return fail("invalid_job", "/stage", `profile ${profileId} duplicate extension id ${entry.id}`);
    }
    seenIds.add(entry.id);
    if (entry.id === STAGE_SUBMIT_EXTENSION_ID) {
      return fail("invalid_job", "/stage", "stage-submit is inherent and must not be listed in stage-profiles.json");
    }
    if (entry.enabled !== true) {
      disabledEntries.push({
        id: entry.id,
        enabled: false,
        root: typeof entry.root === "string" ? entry.root : null,
        note: typeof entry.note === "string" ? entry.note : null,
      });
      continue;
    }
    const root = resolveEnabledRoot(entry, env, home);
    if (!root.ok) return root;
    const channel = entry.channel === "auto-handoff-plan" ? "auto-handoff-plan" : "extension";
    extensionRoots.push({
      id: entry.id,
      root: root.value,
      channel,
      enabled: true,
    });
  }

  return {
    ok: true,
    value: {
      stage,
      profileId,
      extensionRoots,
      skills: skills.value,
      env: profileEnv,
      toolsExtra,
      disabledEntries,
      expectedExtensionIds: [STAGE_SUBMIT_EXTENSION_ID, ...extensionRoots.map((item) => item.id)],
    },
  };
}

export function assertExtensionRootsExist(resolved, exists = existsSync) {
  for (const entry of resolved.extensionRoots) {
    if (!exists(entry.root)) {
      return fail(
        "adapter_failed",
        "/adapter",
        `enabled extension ${entry.id} root not found: ${entry.root}`,
      );
    }
  }
  return { ok: true, value: resolved };
}

export function assertSkillPathsExist(resolved, exists = existsSync) {
  const skills = resolved.skills || { mode: "auto", paths: [] };
  if (skills.mode !== "explicit") return { ok: true, value: resolved };
  for (const path of skills.paths) {
    if (!exists(path)) {
      return fail("adapter_failed", "/adapter", `skill path not found: ${path}`);
    }
    if (!exists(join(path, "SKILL.md"))) {
      return fail("adapter_failed", "/adapter", `skill path missing SKILL.md: ${path}`);
    }
  }
  return { ok: true, value: resolved };
}

export function assertProfileResourcesExist(resolved, exists = existsSync) {
  const extensions = assertExtensionRootsExist(resolved, exists);
  if (!extensions.ok) return extensions;
  return assertSkillPathsExist(resolved, exists);
}

export function parseAttestationRecords(eventsText) {
  if (typeof eventsText !== "string" || eventsText.length === 0) return [];
  const records = [];
  for (const line of eventsText.split("\n")) {
    if (!line.includes("harnessAttestation")) continue;
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      continue;
    }
    if (event && typeof event === "object" && isPlainObject(event.harnessAttestation)) {
      records.push(event.harnessAttestation);
    }
  }
  return records;
}

export function verifyHarnessAttestation(eventsText, expectedIds) {
  const records = parseAttestationRecords(eventsText);
  if (records.length === 0) {
    return fail(
      "extension_manifest_mismatch",
      "/adapter",
      "missing harnessAttestation in Pi events.jsonl",
    );
  }
  const record = records[0];
  if (record.version !== ATTESTATION_VERSION) {
    return fail(
      "extension_manifest_mismatch",
      "/adapter",
      `attestation version ${record.version} !== ${ATTESTATION_VERSION}`,
      { expected: expectedIds, observed: record },
    );
  }
  const observed = Array.isArray(record.expected) ? record.expected : null;
  if (!observed || JSON.stringify(observed) !== JSON.stringify(expectedIds)) {
    return fail(
      "extension_manifest_mismatch",
      "/adapter",
      "attestation expected extension list does not match the stage profile",
      { expected: expectedIds, observed },
    );
  }
  return { ok: true, value: record };
}

export function verifyArgvConsistency(argv, profile) {
  // Skill flags are intentionally not asserted here. Attestation remains
  // extension-only: stage-submit cannot observe which Skills the CLI loaded.
  // Explicit Skill mounting is covered by argv golden tests (-ns plus the
  // exact --skill path set) and by parse-time existence/SKILL.md checks.
  const list = Array.isArray(argv) ? argv : [];
  const dashE = [];
  for (let i = 0; i < list.length; i += 1) {
    if (list[i] === "-e") dashE.push(list[i + 1]);
  }
  const autoHandoff = profile.extensionRoots.find((item) => item.id === "auto-handoff");
  if (autoHandoff) {
    if (!dashE.includes(autoHandoff.root)) {
      return fail(
        "extension_manifest_mismatch",
        "/adapter",
        "auto-handoff root missing from pi argv -e list",
        { expectedRoot: autoHandoff.root, dashE },
      );
    }
  } else if (list.some((item) => typeof item === "string" && /auto-handoff/i.test(item))) {
    return fail(
      "extension_manifest_mismatch",
      "/adapter",
      "auto-handoff traces present in pi argv for a profile that does not enable it",
      { argv: list },
    );
  }
  for (const ext of profile.extensionRoots) {
    if (ext.channel === "extension" && !dashE.includes(ext.root)) {
      return fail(
        "extension_manifest_mismatch",
        "/adapter",
        `enabled extension ${ext.id} root missing from pi argv -e list`,
        { expectedRoot: ext.root, dashE },
      );
    }
  }
  for (const disabled of profile.disabledEntries) {
    if (disabled.root && dashE.includes(disabled.root)) {
      return fail(
        "extension_manifest_mismatch",
        "/adapter",
        `disabled extension ${disabled.id} was mounted`,
        { root: disabled.root },
      );
    }
    if (list.some((item) => item === disabled.id || (typeof item === "string" && item.includes(disabled.id)))) {
      return fail(
        "extension_manifest_mismatch",
        "/adapter",
        `disabled extension ${disabled.id} left a trace in pi argv`,
        { argv: list },
      );
    }
  }
  return { ok: true };
}

export function expectedExtensionsEnvValue(profile) {
  return profile.expectedExtensionIds.join(",");
}

export function parseExpectedExtensionsEnv(raw) {
  return parseExpectedExtensions(raw);
}
