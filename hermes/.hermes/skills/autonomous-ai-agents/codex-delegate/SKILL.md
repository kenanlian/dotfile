---
name: codex-delegate
description: "Use when delegating tasks to Codex CLI."
license: MIT
compatibility: Requires the authenticated OpenAI Codex CLI, Node 18+, and git.
metadata:
  version: 0.6.0
  hermes:
    related_skills: []
---

# Codex Transport Adapter

Dispatch a brief to Codex CLI, capture artifacts, and resume an exact thread. This adapter owns transport only; it does not prescribe development stages, role assignments, review gates, or landing policy.

## When to Use

- Commission a Codex CLI task or continue a known Codex thread.
- Inspect transport status, logs, and the child's final report.
- Do not use this adapter to decide requirements or substitute for task-specific instructions and repository rules.

## Preflight and Model Selection

Use `terminal` to run `command -v codex`, `codex --version`, and `codex login status`. Record the active binary and version; multiple installations can shadow each other. Do not dispatch until authentication is available.

Classify the whole deliverable. Unless the user requests another model or effort:

- **Default:** pass `--model gpt-5.6-sol --effort high`.
- **Narrow lightweight exception:** pass `--model gpt-5.6-terra --effort high` only for an authorized local Git commit of already-prepared changes, or read-only factual retrieval. Neither exception includes implementation, planning, review, design, recommendations, or behavioral judgment.

Use Sol for mixed or ambiguous work and exploration that feeds implementation. These options configure the outer Codex parent, not its built-in subagents. Model routing is independent of permission mode.

## Permissions and Brief

Fresh and resumed runs default to **full access**: the relay uses Codex's `--dangerously-bypass-approvals-and-sandbox` and records `sandbox: "danger-full-access"`.

- For read-only tasks, state “do not modify files or perform Git writes” in the brief and inspect the working-tree diff afterward. Do not automatically add a read-only sandbox based on the task type.
- Use `--read-only` or `--sandbox workspace-write` only when the user or task explicitly requires a CLI restriction.
- Full tool access is not authorization to expand scope. Put the deliverable, repository, allowed changes, validation expectations, and authorized Git/external actions in the brief. Do not add permission-deny rules as part of dispatch.
- The relay itself never commits. The child may commit, push, create a PR, or publish only when the task authorizes it; no special commit-only stage is required by this adapter.

## Dispatch and Resume

Use the installed skill directory reported by `skill_view`; invoke its helper through `terminal`:

```text
node <skill-dir>/scripts/relay.mjs --brief <brief-file> --cd <repo> --model gpt-5.6-sol --effort high --out-dir <artifact-dir>
```

Choose an artifact directory outside the target working tree, under the Hermes scratch workspace or a task's durable artifact location. The brief goes through stdin, not argv. For long runs, use `terminal(background=true, notify=true)` and consume its completion notification rather than an estimated-duration timeout.

| Option | Purpose |
| --- | --- |
| `--sandbox read-only\|workspace-write\|danger-full-access` | Explicit permission mode; default is full access |
| `--read-only` | Explicit shortcut for the read-only sandbox |
| `--model <id>` / `--effort <level>` | Outer model and reasoning effort |
| `--session <threadId>` | Resume one exact thread; send a delta brief with necessary new evidence |
| `--resume-last` | Fallback when the exact ID is unavailable; confirm the selected thread belongs to this task |
| `--clean-env` / `--keep-env <name>` | Optional inherited-environment filtering; not a file-access security boundary |
| `--skip-git-repo-check` | Explicit exception for non-repository tasks |
| `--timeout <dur>` | Optional watchdog, off by default; use only for a required hard bound, preferably a long guard such as `4h` |
| `--out-dir <dir>` | Run artifacts; use a unique directory per dispatch |

Preserve the returned `threadId` for follow-ups. Resume when continuing the same task; start fresh when context or scope calls for it. There is no stage-specific requirement to create or separate threads.

## Result Contract and Failure Handling

The relay writes `result.json`: terminal status, exit information, `codexVersion`, `threadId`, requested model/effort, selected sandbox, `finalMessage`, `touchedFiles`, and artifact paths.

- Wait for the process to exit and read the result with `read_file`. A progress display is not completion.
- `completed` means transport completed, not that the requested deliverable passed acceptance. Check the report and relevant artifact/behavior evidence against the task.
- `touchedFiles` is the final `git status --porcelain` snapshot, not attribution of the child's edits. Capture the initial working-tree state before dispatch; committed changes require Git diff/history inspection too.
- On failure, timeout, or abort, preserve work and logs; inspect them before deciding whether to resume or retry. Do not clean or spawn a replacement blindly.

For exact fields and recovery semantics, read [references/dispatch-and-poll.md](references/dispatch-and-poll.md).

## Verification

Record the intended workspace, selected permissions, outer model/effort, terminal status, exact thread ID when emitted, and artifact paths. If no thread was created, record that fact rather than inventing an ID. Verify the requested deliverable separately using its task-specific criteria.
