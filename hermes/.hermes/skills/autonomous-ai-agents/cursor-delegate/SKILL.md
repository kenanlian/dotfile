---
name: cursor-delegate
description: "Use when delegating tasks to Cursor Agent CLI."
license: MIT
compatibility: Requires the authenticated Cursor `agent` CLI, Node 18+, and git.
metadata:
  version: 0.6.0
  hermes:
    related_skills: []
---

# Cursor Transport Adapter

Dispatch a brief to Cursor Agent CLI, capture artifacts, and resume an exact session. This adapter owns transport only; it does not prescribe development stages, role assignments, review gates, or landing policy.

## When to Use

- Commission a Cursor Agent CLI task or continue a known Cursor session.
- Inspect transport status, logs, and the child's final report.
- Do not use this adapter to decide requirements or substitute for task-specific instructions and repository rules.

## Preflight and Model Selection

Use `terminal` to run `command -v agent`, `agent --version`, `agent status`, and `agent models`. Record the active binary/version and confirm authentication. Check the requested model against the live catalog before dispatch.

Unless the user requests another model:

- **Lightweight/simple task:** pass `--model cursor-grok-4.6-high` for narrow, simple delegation, including factual retrieval and authorized commits of already-prepared changes.
- **Substantial work:** pass `--model claude-opus-5-thinking-high` for complex, structured, mixed, or ambiguous work and tasks involving planning, review, product judgment, architecture, persistence, or migration. Verify the live label and compare `resolvedModel` with the intended model/context allocation; do not rely on an old label to assume 1M context.

If discovery exposes broader coupling or consequential judgment, reclassify before expanding the task. These options configure the outer Cursor parent. Model routing is independent of permission mode.

## Permissions and Brief

Fresh and resumed runs default to **full access**: the relay passes `--force --sandbox disabled` plus `--trust`. Confirm the target workspace before dispatch.

- For read-only tasks, state “do not modify files or perform Git writes” in the brief and inspect the working-tree diff afterward. Do not automatically switch to plan mode based on the task type.
- Use `--read-only` (Cursor plan mode) or `--sandbox enabled` only when the user or task explicitly requires a CLI restriction.
- Full tool access is not authorization to expand scope. Put the deliverable, repository, allowed changes, validation expectations, and authorized Git/external actions in the brief. Do not add permission-deny rules as part of dispatch. Existing Cursor deny rules may still block commands; `--force` does not override them.
- The relay itself never commits. The child may commit, push, create a PR, or publish only when the task authorizes it; no special commit-only stage is required by this adapter.

## Dispatch and Resume

Use the installed skill directory reported by `skill_view`; invoke its helper through `terminal`:

```text
node <skill-dir>/scripts/relay.mjs --brief <brief-file> --cd <repo> --model claude-opus-5-thinking-high --out-dir <artifact-dir>
```

Choose an artifact directory outside the target working tree, under the Hermes scratch workspace or a task's durable artifact location. The brief goes through stdin, not argv. For long runs, use `terminal(background=true, notify=true)` and consume its completion notification rather than an estimated-duration timeout.

| Option | Purpose |
| --- | --- |
| `--force` | Enable writes and automatic command approval; already the default |
| `--sandbox enabled\|disabled` | Explicit sandbox selection; default is disabled |
| `--read-only` | Explicit opt-in to Cursor plan mode; removes `--force` |
| `--model <id>` | Outer Cursor model |
| `--session <sessionId>` | Resume one exact chat; send a delta brief with necessary new evidence |
| `--resume-last` | Fallback when the exact ID is unavailable; confirm the selected chat belongs to this task |
| `--add-dir <dir>` | Additional workspace root; inspect its changes separately |
| `--plugin-dir <dir>` | Repeatable absolute existing plugin directory; recorded as `pluginDirs` |
| `--timeout <dur>` | Optional watchdog, off by default; use only for a required hard bound, preferably a long guard such as `4h` |
| `--out-dir <dir>` | Run artifacts; use a unique directory per dispatch |
| `CURSOR_AGENT_BIN` | Test/CI-only binary override at version probe and dispatch |

Preserve the returned `sessionId` for follow-ups. Resume when continuing the same task; start fresh when context or scope calls for it. There is no stage-specific requirement to create or separate sessions.

## Result Contract and Failure Handling

The relay writes `result.json`: terminal status and exit information, `cursorAgentVersion`, `sessionId`, `resolvedModel`, reported `permissionMode`, requested sandbox/read-only/force flags, `pluginDirs`, `spawn: { argv, envKeys }`, `finalMessage`, `touchedFiles`, and artifact paths. Environment values are not persisted in `spawn`.

- Wait for the process to exit and read the result with `read_file`. A progress display is not completion.
- `completed` means transport completed, not that the requested deliverable passed acceptance. Check the report and relevant artifact/behavior evidence against the task.
- `touchedFiles` is the final `git status --porcelain` snapshot under `--cd`, not attribution of the child's edits. Capture the initial working-tree state before dispatch; committed changes require Git diff/history inspection too. Inspect `--add-dir` roots separately.
- On failure, timeout, or abort, preserve work and logs; inspect them before deciding whether to resume or retry. Do not clean or spawn a replacement blindly.

For exact fields and recovery semantics, read [references/dispatch-and-poll.md](references/dispatch-and-poll.md).

## Verification

Record the intended workspace, requested permissions, reported permission mode when available, outer requested/resolved model, terminal status, exact session ID when emitted, and artifact paths. If no session was created, record that fact rather than inventing an ID. Verify the requested deliverable separately using its task-specific criteria.
