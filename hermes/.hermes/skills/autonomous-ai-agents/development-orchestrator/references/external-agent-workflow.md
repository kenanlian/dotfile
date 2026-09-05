# External Agent Workflow

The main Skill owns lifecycle, board routing, UI classification, and authority. This reference owns coding-agent transport stages, permission modes, prompt shapes, and exact-session mechanics.

Default transport is OpenCode. Use Cursor, Codex, or Pi only when the user explicitly selected that tool for the current task.

## Skill source and discovery

Personal source:

```text
~/Secret-Projects/agent_skills/skills
```

Preferred project discovery:

```text
<repo>/.agents/skills -> ~/Secret-Projects/agent_skills/skills
```

Pi uses the same single global root through its user-level discovery: `~/.pi/agent/skills -> ~/Secret-Projects/agent_skills/skills` (dotfile-managed symlink). There is exactly one Skill tree; never copy or mirror Skills per project or per Agent.

Verify discovery in every target repository. Do not assume setup in one project applies elsewhere. The active collection has no brainstorming Skill; never reference or invoke one.

## Direct simple-task implementation

Start one ordinary writable coding-agent parent. Do not invoke `write-plan` or `execute-plan`.

Prompt shape:

```text
Implement this bounded task in the current repository.

Goal and observable result:
- <goal>

Included scope:
- <scope>

Non-goals:
- <non-goals>

UI classification:
- <UI acceptance required | no UI acceptance>

Inspect the repository before editing. Preserve unrelated work. Implement the task,
run focused verification plus any relevant integration/end-to-end checks, and report
exact commands, observed results, changed-file scope, and residual limitations.
Do not commit, push, open a PR, release, deploy, publish, change versions, or perform
external side effects.
```

If investigation exposes architecture, persistence, migration, compatibility, security, release, broad coupling, or an unresolved product decision, stop expansion and return the evidence so Watson can reclassify the existing card as structured.

## Structured stage 1: repository-grounded discussion

No entry Skill is invoked. Keep this stage read-only and preserve the exact outer session.

Use the matching transport in read-only or planning mode:

- Cursor: plan/read-only mode; resume the exact chat.
- Codex: `read-only`; resume the exact `threadId`.
- OpenCode: `--read-only`; resume the exact `sessionId`. The adapter selects the plan Agent and denies edits, shell writes, and external-directory writes.
- Pi: `--read-only` (tool allowlist `read,grep,find,ls,delegate_agent`); fresh `--session-id` first, resume the exact session for follow-ups.

Prompt shape:

```text
We are evaluating a product requirement. Do not modify files, write a formal plan,
or invoke write-plan, execute-plan, or delegate-work yet.

Product goal and workflow:
- <goal and user flow>

Expected behavior:
- <observable behavior>

Non-goals:
- <excluded behavior>

UI classification under consideration:
- <known UI scope or unknown>

Inspect the live repository and return:
1. Your understanding of the request.
2. Current relevant behavior and ownership boundaries.
3. Feasible implementation directions and product impact.
4. Conflicts with existing architecture or contracts.
5. Product decisions still needed.
6. Important failure, empty, repeated, restart, and persistence cases.
```

Continue ordinary repository-grounded discussion until product intent and implementation reality converge. There is no separate brainstorming stage or Skill.

## Structured stage 2: `write-plan`

Resume the established discussion parent and grant only the writes required for the plan and its audit artifacts.

### Cursor

```text
/write-plan

Based on our settled product and repository discussion, write the self-contained
execution plan. Preserve these confirmed behaviors and non-goals:
- <settled requirements>

Verification and UI-acceptance contract:
- <coding-agent verification requirements>
- <UI scenarios Watson must later exercise, or explicitly no UI acceptance>

Run the write-plan Skill's complete internal review-plan lifecycle. Own reviewer
dispatch, adjudication, plan revisions, persisted artifacts, and the round limit.
Return only after the internal gate is closed or a user decision is required.
Do not implement or commit.
```

### Codex

Use the same shape with `$write-plan`.

### OpenCode

Resume the exact discussion `sessionId` with `--write` and replace the first line with:

```text
Use the discovered write-plan Skill.
```

### Pi

Resume the exact discussion session with `--write` (tool allowlist `read,grep,find,ls,bash,edit,write,delegate_agent`) and use the same shape as Cursor, replacing the first line with:

```text
Use the write-plan Skill (discovered from the global Skill root).
```

Do not explicitly invoke `delegate-work`, `review-plan`, planning reviewers, or domain Skills from Watson. The discovered `write-plan` workflow owns its internal delegation and review.

A successful top-level result must identify the exact final plan, internal gate outcome, audit-artifact directory, and any residual limitation or user decision. Read back the declared plan path before advancing.

## Structured stage 3: `execute-plan`

Start a fresh writable parent and supply the exact accepted plan path.

### Cursor

```text
/execute-plan

Plan file: .dev/plan/<slug>-plan.md
Execute the saved plan through completion. Preserve unrelated user work. Do not
commit, push, open a PR, release, deploy, publish, change versions, or perform
unauthorized external effects. Own implementation, final verification, and the
execute-plan Skill's internally selected review-patch and/or
review-plan-conformance lifecycle, including adjudication and in-scope fixes.

UI classification:
- <UI acceptance required: prepare exact build/install/reload steps and a real
  renderer-ready artifact | no UI acceptance: return a fully verified engineering
  handoff>

Report exact verification commands and observed results, internal review gates,
changed-file scope, artifact paths, and residual limitations.
```

### Codex

Use the same shape with `$execute-plan`.

### OpenCode

Start a fresh `--write` session and replace the first line with:

```text
Use the discovered execute-plan Skill.
```

### Pi

Start a fresh `--write` session (new `--session-id`) with the same shape as Cursor, replacing the first line with:

```text
Use the execute-plan Skill (discovered from the global Skill root).
```

The outer prompt must not recreate the plan DAG, `delegate-work` contract, model table, review-round protocol, reviewer prompts, or domain-Skill routing. Watson commissions one complete `execute-plan` operation; the execution parent owns its internal reviews.

## UI behavioral rework

For a failed UI acceptance scenario, resume the exact execution parent (Cursor: exact chat; Codex: exact `threadId`; OpenCode: exact `sessionId`; Pi: exact `--session` with `--write`):

```text
UI behavior acceptance failed.

Environment/build:
- <application version, build identity, configuration>

Reproduction:
1. <user step>
2. <user step>

Expected:
- <visible behavior>

Observed:
- <visible behavior>

Evidence:
- <screenshot/DOM/visible state or None>

Continue the existing implementation, repair this behavior, repeat the applicable
engineering verification and internal review path, and prepare a new renderer-ready
artifact. Do not commit.
```

For an incomplete non-UI handoff, resume the exact implementation parent with only the missing contract or artifact. Do not independently diagnose the code or repeat behavior testing in Watson.

## Transport adapters

Load `cursor-delegate`, `codex-delegate`, `opencode-delegate`, or `pi-delegate` only for:

- CLI/authentication preflight;
- workspace and permission flags;
- structured event capture;
- timeout/process management;
- exact-session resume; and
- result artifact paths.

The adapter never decides requirements, workflow class, UI acceptance, internal review policy, or landing authority.

## Model layers

The Relay model selects the outer coding-agent parent. Built-in subagent models belong to the discovered workflow. When the user specifies a model, label it as outer parent, inner subagent, or both; surface conflicts instead of silently overriding the target Skill.
