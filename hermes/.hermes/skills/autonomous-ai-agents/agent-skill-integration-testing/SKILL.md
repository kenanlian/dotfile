---
name: agent-skill-integration-testing
description: Use when smoke-testing explicit Agent Skill invocation.
version: 0.1.0
license: MIT
metadata:
  hermes:
    tags: [agent-skills, smoke-testing, cursor, codex, delegation]
---

# Agent Skill Integration Testing

Verify that an external agent harness can discover and explicitly invoke an Agent Skill without allowing the Skill's real workflow to run. Treat this as an integration test of discovery, invocation syntax, transport, and evidence capture—not as a development task.

## When to Use

Use this skill when asked to confirm that Cursor, Codex, or another delegated agent can:

- discover a named `SKILL.md` through the harness-supported skill root;
- recognize the harness's explicit invocation syntax;
- load the intended Skill rather than merely repeat a requested success string; and
- return immediately without planning, implementation, commands, tests, or project writes.

Do not use this workflow to evaluate the quality of a Skill's real output. A real workflow test needs a representative fixture and separate acceptance criteria.

## Test Contract

Before dispatch, define all of these explicitly:

1. **Target harness** and exact CLI transport.
2. **Target Skill name** and expected source `SKILL.md`.
3. **Invocation syntax** used by that harness.
4. **Stop boundary:** loading is allowed; the Skill's substantive workflow is forbidden.
5. **Success token:** for example, `SMOKE_OK <skill-name>`.
6. **Failure token:** for example, `SMOKE_FAIL <skill-name>` plus one short reason.
7. **Evidence source** that can distinguish real loading from parroting.
8. **Zero-write invariant** for the isolated working tree.

A final success token alone is never sufficient evidence.

## Isolation Setup

1. Create a disposable temporary Git repository; never point an invocation-only smoke test at a real project.
2. Expose the Skill collection through each harness's supported discovery root. Prefer symlinks so the test exercises the live Skill source rather than a copied snapshot.
3. Put relay artifacts outside the temporary worktree.
4. Establish a clean Git baseline before dispatch. A small initialization commit inside the disposable repository is acceptable; otherwise record and compare the exact pre-run status.
5. Run invocation-only tests in read-only mode even when the real Skill normally requires write access.

For Cursor and Codex discovery paths, prompt shapes, and evidence locations, read [references/cursor-codex-explicit-invocation.md](references/cursor-codex-explicit-invocation.md).

## Prompt Shape

Start the brief with the harness-native explicit invocation token, then state the smoke-test contract. Keep it intentionally taskless.

Require the external agent to:

- invoke and load exactly the named Skill;
- stop as soon as loading is confirmed;
- avoid repository inspection beyond reading the Skill source when the harness requires it;
- avoid questions, planning, implementation, commands, tests, and all file changes;
- avoid invoking dependency Skills; and
- return only the success token, or the failure token with one short reason.

Do not provide a fake product requirement, dummy plan, or placeholder implementation. Those convert an invocation test into a partial workflow run and make zero-side-effect verification ambiguous.

## Dispatch

- Use the established transport adapter for the harness.
- Pass the configured outer model explicitly rather than relying on an `auto` default.
- Use a bounded watchdog appropriate for a short smoke test.
- Give every independent harness/Skill pair its own fresh session and artifact directory.
- Independent smoke tests may run in parallel when their working state and artifacts do not collide.
- Preserve the returned session or thread ID so detailed runtime records can be located.

## Verification

A test passes only when all of the following are true:

1. The relay reports terminal completion with exit code zero.
2. The final response contains the expected success token.
3. Harness-specific evidence proves the intended Skill content was attached or read.
4. The evidence resolves to the expected Skill name and source path.
5. The relay reports no touched files.
6. A direct Git status check confirms the temporary worktree remains clean.
7. No substantive workflow action, dependency Skill, command, test, or plan artifact occurred.

Report failures honestly. If discovery succeeded but the agent began the real workflow, invocation passed but the stop-boundary test failed.

## Evidence Rules

### Cursor-style runtimes

Prefer structured event evidence showing a read/tool call for the exact expected `SKILL.md`. Confirm both the requested path and a successful tool result. Agent prose such as “loaded successfully” is supporting evidence only.

### Codex-style runtimes

Relay `events.jsonl` may contain only the final agent message. Use the returned thread ID to inspect the corresponding persisted rollout and confirm that the explicit `$skill-name` message was followed by an injected `<skill>` block naming the expected Skill and source path.

### Other runtimes

Identify the runtime's equivalent attachment, expansion, or tool-call evidence before declaring success. If the runtime exposes no such evidence, report the result as unproven rather than upgrading a self-report into verification.

## Pitfalls

- **Trusting `SMOKE_OK`:** models can echo the requested token without loading anything.
- **Testing in a real repository:** even a well-bounded prompt can trigger Skill instructions with side effects.
- **Using write mode for convenience:** invocation does not require the permissions of the real workflow.
- **Putting artifacts in the worktree:** relay output then contaminates the zero-write assertion.
- **Confusing discovery with execution:** loading `execute-plan` does not require supplying or running a plan.
- **Inspecting only relay events for Codex:** the Skill attachment can exist only in the persisted rollout.
- **Hard-coding current CLI versions:** rerun live preflight; version observations are provenance, not durable requirements.

## Reporting

Summarize results as one row per harness/Skill pair with:

- explicit invocation syntax;
- pass/fail;
- evidence type and resolved Skill path;
- read-only or permission mode;
- terminal status;
- touched-file count and Git cleanliness; and
- a clear statement that no real task was executed.

Keep session IDs and artifact paths available for audit, but do not mistake their existence for proof of successful invocation.
