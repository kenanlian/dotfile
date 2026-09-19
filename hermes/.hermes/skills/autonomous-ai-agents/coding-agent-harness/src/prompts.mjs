import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { STAGE_CONTRACTS } from "./contracts.mjs";
import { resolveStageProfile } from "./stage-profiles.mjs";

const PROMPTS_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "prompts");
const CURSOR_PROMPTS_DIR = join(PROMPTS_DIR, "cursor");

const STAGE_TEMPLATES = Object.freeze({
  plan: "planner.md",
  plan_review: "plan-reviewer.md",
  implement: "implementer.md",
  direct_implement: "direct-implementer.md",
  execute_review: "execute-reviewer.md",
});

export const CURSOR_STAGE_TEMPLATES = Object.freeze({
  plan: "planner.md",
  plan_review: "plan-reviewer.md",
  implement: "implementer.md",
  direct_implement: "direct-implementer.md",
  execute_review: "execute-reviewer.md",
});

export const ENTRY_SKILL_TOKENS = Object.freeze({
  plan: "/write-plan",
  plan_review: "/review-plan",
  implement: "/execute-plan",
  execute_review: "/review-execute-candidate",
  direct_implement: null,
});

const PROFILE_TEMPLATES = Object.freeze({
  planner: "planner.md",
  "plan-reviewer": "plan-reviewer.md",
  implementer: "implementer.md",
  "execute-reviewer": "execute-reviewer.md",
});

// Mirrored from pi-delegate relay.mjs validateSkillPrefix. Pi splits the
// skill name at indexOf(" "); a first line of `/skill:<name>` plus newline
// (no same-line trailing space) captures the rest of the brief as the name.
export const SKILL_PREFIX_LINE = /^\/skill:[a-z0-9][a-z0-9-]* \r?$/;

function formatInputs(inputs) {
  return inputs
    .map((item) => `- ${item.kind}: ${item.path} (sha256 ${item.sha256})`)
    .join("\n");
}

// Render name + absolute SKILL.md path for every mounted Skill. Hidden
// Skills (disable-model-invocation) never enter <available_skills>, so the
// prompt is the ONLY place the model learns their location — a bare name
// degrades to path-guessing scans. Point at the SKILL.md file directly so a
// single `read` follows the Skill.
export function formatMountedSkillsLine(names, mode = "explicit", paths = []) {
  if (mode === "auto") {
    return "This run uses Pi default Skill discovery (no explicit Skill list). Follow any Skills that apply. The submit tool schema remains the only report channel.";
  }
  const list = Array.isArray(names) && names.length > 0
    ? names
        .map((name, i) => {
          const path = paths[i];
          return path ? `- ${name}: ${join(path, "SKILL.md")}` : `- ${name}`;
        })
        .join("\n")
    : "- (none)";
  return `This run mounts Skills (read the SKILL.md at each path to follow its process):\n${list}\nThe submit tool schema remains the only report channel (Skills govern process; the schema governs output).`;
}

export function formatSkillInlinePrefix(name) {
  if (typeof name !== "string" || name.length === 0) return "";
  const line = `/skill:${name} `;
  if (!SKILL_PREFIX_LINE.test(line)) {
    throw new Error(`skills.inline ${name} does not match relay /skill: first-line shape`);
  }
  return `${line}\n`;
}

function loadSkillsForBrief(job, extras) {
  if (extras.profile && extras.profile.skills) return extras.profile.skills;
  const resolved = resolveStageProfile(job.stage, { env: extras.env || process.env });
  if (!resolved.ok) return { mode: "auto", names: [], inline: null };
  return resolved.value.skills;
}

function applyPlaceholders(template, replacements) {
  let brief = template;
  for (const [token, value] of Object.entries(replacements)) {
    brief = brief.split(token).join(value);
  }
  return brief;
}

function compileCursorBrief(job, extras = {}) {
  const templateName = CURSOR_STAGE_TEMPLATES[job.stage];
  if (!templateName) {
    throw new Error(`unknown stage ${job.stage}`);
  }
  const contract = STAGE_CONTRACTS[job.stage];
  const template = readFileSync(join(CURSOR_PROMPTS_DIR, templateName), "utf8");
  const replacements = {
    "{{jobId}}": job.jobId,
    "{{idempotencyKey}}": job.idempotencyKey,
    "{{taskId}}": job.taskId,
    "{{stage}}": job.stage,
    "{{attempt}}": String(job.attempt),
    "{{repoRoot}}": job.workspace.repoRoot,
    "{{branch}}": job.workspace.branch,
    "{{expectedHead}}": job.workspace.expectedHead,
    "{{profile}}": job.agent.profile,
    "{{model}}": job.agent.model,
    "{{thinking}}": job.agent.thinking,
    "{{mode}}": job.permissions.mode,
    "{{submitTool}}": contract.submitTool,
    "{{outputSchema}}": contract.outputSchema,
    "{{inputs}}": formatInputs(job.inputs),
    "{{workspaceEvidencePath}}": extras.workspaceEvidencePath ?? "",
    "{{candidatePatchPath}}": extras.candidatePatchPath ?? "",
  };
  const brief = applyPlaceholders(template, replacements);
  const token = ENTRY_SKILL_TOKENS[job.stage];
  return token ? `${token} \n${brief}` : brief;
}

export function compileCursorRecoveryBrief(job, extras = {}) {
  const contract = STAGE_CONTRACTS[job.stage];
  if (!contract) {
    throw new Error(`unknown stage ${job.stage}`);
  }
  const submitBinding = extras.submitBinding || {};
  const template = readFileSync(join(CURSOR_PROMPTS_DIR, "output-recovery.md"), "utf8");
  return applyPlaceholders(template, {
    "{{jobId}}": job.jobId,
    "{{idempotencyKey}}": job.idempotencyKey,
    "{{taskId}}": job.taskId,
    "{{stage}}": job.stage,
    "{{attempt}}": String(job.attempt),
    "{{repoRoot}}": job.workspace.repoRoot,
    "{{submitTool}}": contract.submitTool,
    "{{outputSchema}}": contract.outputSchema,
    "{{phase}}": submitBinding.phase || "output-recovery",
    "{{jobSha256}}": submitBinding.jobSha256 || "",
    "{{runNonce}}": submitBinding.runNonce || "",
    "{{submitConfigPath}}": extras.submitConfigPath || "",
  });
}

export function compileBrief(job, extras = {}) {
  if (job.agent.adapter === "cursor") {
    return compileCursorBrief(job, extras);
  }
  const templateName = STAGE_TEMPLATES[job.stage];
  if (!templateName) {
    throw new Error(`unknown stage ${job.stage}`);
  }
  const contract = STAGE_CONTRACTS[job.stage];
  const template = readFileSync(join(PROMPTS_DIR, templateName), "utf8");
  const skills = loadSkillsForBrief(job, extras);
  const names = Array.isArray(extras.mountedSkills) ? extras.mountedSkills : skills.names;
  const skillPaths = Array.isArray(extras.mountedSkills) ? [] : skills.paths || [];
  const mode = extras.skillsMode || skills.mode;
  const inline = extras.inlineSkill !== undefined ? extras.inlineSkill : skills.inline;
  const replacements = {
    "{{jobId}}": job.jobId,
    "{{idempotencyKey}}": job.idempotencyKey,
    "{{taskId}}": job.taskId,
    "{{stage}}": job.stage,
    "{{attempt}}": String(job.attempt),
    "{{repoRoot}}": job.workspace.repoRoot,
    "{{branch}}": job.workspace.branch,
    "{{expectedHead}}": job.workspace.expectedHead,
    "{{profile}}": job.agent.profile,
    "{{model}}": job.agent.model,
    "{{thinking}}": job.agent.thinking,
    "{{mode}}": job.permissions.mode,
    "{{submitTool}}": contract.submitTool,
    "{{outputSchema}}": contract.outputSchema,
    "{{inputs}}": formatInputs(job.inputs),
    "{{workspaceEvidencePath}}": extras.workspaceEvidencePath ?? "",
    "{{candidatePatchPath}}": extras.candidatePatchPath ?? "",
    "{{mountedSkills}}": formatMountedSkillsLine(names, mode, skillPaths),
  };
  let brief = template;
  for (const [token, value] of Object.entries(replacements)) {
    brief = brief.split(token).join(value);
  }
  const prefix = formatSkillInlinePrefix(inline);
  return prefix ? `${prefix}${brief}` : brief;
}

export { PROMPTS_DIR, PROFILE_TEMPLATES, STAGE_TEMPLATES };
