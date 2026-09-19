import { test } from "node:test";
import assert from "node:assert/strict";
import { STAGE_CONTRACTS, STAGES, SUBMIT_TOOLS } from "../src/contracts.mjs";
import {
  compileBrief,
  compileCursorRecoveryBrief,
  CURSOR_STAGE_TEMPLATES,
  ENTRY_SKILL_TOKENS,
  STAGE_TEMPLATES,
} from "../src/prompts.mjs";

const PLACEHOLDER = /\{\{[^}]+\}\}/;
const SKILL_MD_PATH = /(?:^|[^\w])(?:\/|[A-Za-z]:).*SKILL\.md/m;

const PI_PLAN_GOLDEN_EXTRAS = {
  profile: {
    skills: {
      mode: "explicit",
      names: ["write-plan", "delegate-work"],
      inline: "write-plan",
      paths: ["/abs/skills/write-plan", "/abs/skills/delegate-work"],
    },
  },
};

const PI_PLAN_GOLDEN = `/skill:write-plan 
# Planner

You are the Planner for a single coding-agent Job. This is not a workflow controller.

- Profile: planner
- Permission: read-only. Explore with read/grep/find/ls/delegate_agent only.
- Parent and every delegated child must remain read-only. Do not write, edit, commit, push, tag, release, or deploy.
- Repository: /abs/repo
- Branch: main
- Expected HEAD: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
- Job: job_golden / task:plan:1 / task task_golden / stage plan / attempt 1
- Model: zai-coding-cn/glm-5.3 thinking=high
- This run mounts Skills (read the SKILL.md at each path to follow its process):
- write-plan: /abs/skills/write-plan/SKILL.md
- delegate-work: /abs/skills/delegate-work/SKILL.md
The submit tool schema remains the only report channel (Skills govern process; the schema governs output).

Inputs (read these files; hashes are already verified by the host):

- requirement: /abs/requirement.md (sha256 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)

Your only report channel is the terminating tool \`submit_plan\` with schema plan.v1.
Do not put the plan in the final message. Do not serialize YAML. Do not wrap JSON in Markdown fences as the report.
Call \`submit_plan\` exactly once with a complete, schema-valid payload, then stop. An error result from the submit tool fails the run; a later corrected call is not accepted.

Payload types (objects, never flattened id strings):
- schema: "plan.v1"
- outcome: "completed" or "blocked"
- title, goal, architecture: strings
- techStack: string array
- requirements: array of {id, text}
- contracts: array of {id, requirementIds, text} — not ["C1"]
- workPackages: array of {id, title, objective, dependsOn, contractIds, fileChanges, steps, verificationIds}
  fileChanges items are {action: create|modify|delete, path: repo-relative}
- verification: array of {id, kind: focused|integration|smoke, cwd: "." or repo-relative, argv, expected, contractIds}
- risks: array of {risk, mitigation}
- blockingIssues: string array; empty only when outcome is completed
`;

function sampleJob(stage, adapter = "cursor") {
  const contract = STAGE_CONTRACTS[stage];
  const inputs = stage === "plan"
    ? [{ kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) }]
    : stage === "plan_review"
      ? [
        { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
        { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
      ]
      : stage === "implement"
        ? [{ kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) }]
        : stage === "direct_implement"
          ? [{ kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) }]
          : [
            { kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) },
            { kind: "plan", path: "/abs/plan.json", sha256: "c".repeat(64) },
            { kind: "implementation", path: "/abs/impl.json", sha256: "d".repeat(64) },
          ];
  return {
    jobId: `job_${stage}`,
    idempotencyKey: `task:${stage}:1`,
    taskId: "task_1",
    stage,
    attempt: 1,
    workspace: {
      repoRoot: "/abs/repo",
      branch: "main",
      expectedHead: "a".repeat(40),
    },
    agent: {
      adapter,
      profile: contract.profile,
      model: adapter === "cursor" ? "claude-opus-5-thinking-high" : "zai-coding-cn/glm-5.3",
      thinking: "high",
    },
    permissions: { mode: contract.permission },
    inputs,
  };
}

function goldenPiPlanJob() {
  return {
    jobId: "job_golden",
    idempotencyKey: "task:plan:1",
    taskId: "task_golden",
    stage: "plan",
    attempt: 1,
    workspace: {
      repoRoot: "/abs/repo",
      branch: "main",
      expectedHead: "a".repeat(40),
    },
    agent: {
      adapter: "pi",
      profile: "planner",
      model: "zai-coding-cn/glm-5.3",
      thinking: "high",
    },
    permissions: { mode: "read-only" },
    inputs: [{ kind: "requirement", path: "/abs/requirement.md", sha256: "b".repeat(64) }],
  };
}

function extrasFor(stage) {
  if (stage !== "execute_review") return {};
  return {
    workspaceEvidencePath: "/out/derived/workspace-evidence.json",
    candidatePatchPath: "/out/derived/candidate.patch",
  };
}

test("ENTRY_SKILL_TOKENS and CURSOR_STAGE_TEMPLATES match the C4 mapping", () => {
  assert.deepEqual({ ...ENTRY_SKILL_TOKENS }, {
    plan: "/write-plan",
    plan_review: "/review-plan",
    implement: "/execute-plan",
    execute_review: "/review-execute-candidate",
    direct_implement: null,
  });
  assert.deepEqual({ ...CURSOR_STAGE_TEMPLATES }, { ...STAGE_TEMPLATES });
});

test("compileBrief cursor: per-stage entry token, substitution, and C4 wording", () => {
  for (const stage of STAGES) {
    const brief = compileBrief(sampleJob(stage, "cursor"), extrasFor(stage));
    const firstLine = brief.split("\n", 1)[0];
    const token = ENTRY_SKILL_TOKENS[stage];
    if (token) {
      assert.equal(firstLine, `${token} `, stage);
    } else {
      assert.equal(stage, "direct_implement");
      assert.ok(!firstLine.startsWith("/"), stage);
      assert.notEqual(firstLine, "/write-plan ");
    }
    assert.doesNotMatch(brief, /\/skill:/, stage);
    assert.doesNotMatch(brief, SKILL_MD_PATH, stage);
    assert.doesNotMatch(brief, /This run mounts Skills/, stage);
    assert.match(brief, new RegExp(SUBMIT_TOOLS[stage]), stage);
    assert.match(brief, /only report channel/, stage);
    assert.match(brief, /exactly once/, stage);
    assert.match(brief, /final action/, stage);
    assert.match(brief, /native global\/project Skill discovery/, stage);
    assert.match(brief, /no explicit Skill list is mounted/, stage);
    assert.match(brief, /Cursor-native Subagents/, stage);
    assert.doesNotMatch(brief, PLACEHOLDER, stage);
    assert.doesNotMatch(brief, /delegate_agent/, stage);
    if (stage === "direct_implement") {
      assert.doesNotMatch(brief, /auto[- ]handoff/i, stage);
    }
    if (stage === "plan") {
      assert.match(brief, /Harness persists the Plan Artifact/, stage);
      assert.match(brief, /never writes plan files/, stage);
    }
    if (stage === "plan" || stage === "plan_review" || stage === "execute_review") {
      assert.match(brief, /Do not write/, stage);
    }
    if (stage === "execute_review") {
      assert.match(brief, /workspace-evidence\.json/, stage);
      assert.match(brief, /candidate\.patch/, stage);
    }
  }
});

test("compileCursorRecoveryBrief renders output-only recovery with stage submit tool", () => {
  for (const stage of STAGES) {
    const submitBinding = {
      jobSha256: "c".repeat(64),
      runNonce: "00000000-0000-4000-8000-000000000000",
      phase: "output-recovery",
    };
    const brief = compileCursorRecoveryBrief(sampleJob(stage, "cursor"), {
      submitBinding,
      submitConfigPath: "/abs/out/adapter/output-recovery/submit-bridge/config.json",
    });
    const contract = STAGE_CONTRACTS[stage];
    assert.match(brief, new RegExp(contract.submitTool), stage);
    assert.match(brief, new RegExp(contract.outputSchema), stage);
    assert.match(brief, /job_/);
    assert.match(brief, /\/abs\/repo/);
    assert.match(brief, /no further analysis/, stage);
    assert.match(brief, /Do not write/, stage);
    assert.match(brief, /only report channel/, stage);
    assert.match(brief, /output-recovery/, stage);
    assert.match(brief, new RegExp(submitBinding.jobSha256), stage);
    assert.match(brief, new RegExp(submitBinding.runNonce), stage);
    assert.match(brief, /\/abs\/out\/adapter\/output-recovery\/submit-bridge\/config\.json/, stage);
    assert.match(brief, /Do not reuse any primary-phase runNonce/, stage);
    assert.doesNotMatch(brief, PLACEHOLDER, stage);
    assert.doesNotMatch(brief, /\/skill:/, stage);
    assert.doesNotMatch(brief, SKILL_MD_PATH, stage);
    const firstLine = brief.split("\n", 1)[0];
    const token = ENTRY_SKILL_TOKENS[stage];
    if (token) assert.notEqual(firstLine, `${token} `, stage);
  }
});

test("Pi compileBrief output is byte-identical for adapter:pi (plan golden)", () => {
  const actual = compileBrief(goldenPiPlanJob(), PI_PLAN_GOLDEN_EXTRAS);
  assert.equal(actual, PI_PLAN_GOLDEN);
  assert.equal(actual.split("\n", 1)[0], "/skill:write-plan ");
  assert.match(actual, /This run mounts Skills \(read the SKILL\.md at each path/);
  assert.match(actual, /- write-plan: \/abs\/skills\/write-plan\/SKILL\.md/);
});
