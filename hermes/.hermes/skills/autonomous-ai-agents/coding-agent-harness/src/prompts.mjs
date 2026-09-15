import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { STAGE_CONTRACTS } from "./contracts.mjs";

const PROMPTS_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "prompts");

const STAGE_TEMPLATES = Object.freeze({
  plan: "planner.md",
  plan_review: "plan-reviewer.md",
  implement: "implementer.md",
  direct_implement: "direct-implementer.md",
  execute_review: "execute-reviewer.md",
});

const PROFILE_TEMPLATES = Object.freeze({
  planner: "planner.md",
  "plan-reviewer": "plan-reviewer.md",
  implementer: "implementer.md",
  "execute-reviewer": "execute-reviewer.md",
});

function formatInputs(inputs) {
  return inputs
    .map((item) => `- ${item.kind}: ${item.path} (sha256 ${item.sha256})`)
    .join("\n");
}

export function compileBrief(job, extras = {}) {
  const templateName = STAGE_TEMPLATES[job.stage];
  if (!templateName) {
    throw new Error(`unknown stage ${job.stage}`);
  }
  const contract = STAGE_CONTRACTS[job.stage];
  const template = readFileSync(join(PROMPTS_DIR, templateName), "utf8");
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
  let brief = template;
  for (const [token, value] of Object.entries(replacements)) {
    brief = brief.split(token).join(value);
  }
  return brief;
}

export { PROMPTS_DIR, PROFILE_TEMPLATES, STAGE_TEMPLATES };
