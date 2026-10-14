---
name: opencode-delegate
description: "Use when delegating tasks to OpenCode CLI."
version: 0.3.0
author: "柯楠, Hermes Agent"
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [development, opencode, transport, delegation]
    related_skills: [opencode]
---

# OpenCode Transport Adapter

Dispatch a brief to OpenCode CLI, capture structured artifacts, export the session, and resume its exact ID. This adapter owns transport only; it does not prescribe development stages, role assignments, review gates, landing policy, or custom backend routing.

## When to Use

- Commission an OpenCode CLI task needing persistent session IDs, logs, or structured results.
- Continue a known OpenCode session or inspect a failed run.
- For a quick one-shot task, direct `opencode run` from the `opencode` Skill is sufficient.

## Preflight and Model Selection

Use `terminal` to run `command -v opencode`, `opencode --version`, `opencode auth list`, and `opencode models`. Record the active binary/version and check authentication and the requested model against the live catalog.

Unless the user overrides, pass `--model zhipuai-coding-plan/glm-5.3`; add `#high` for reasoning-heavy or high-stakes tasks. Use exact supported identifiers, not guessed alternatives.

Verified CLI facts on v2.0.29:

- Bare `opencode run` resolves to the Go-provider default, which requires its subscription. Always pass the selected model explicitly.
- CLI variant is inline: `--model provider/model#variant`. The relay's convenience `--variant` composes that token; the CLI has no standalone variant flag.
- Session export is `opencode session export <id>`, not `opencode export`.

## Permissions and Brief

The relay passes `--auto` on both fresh and resumed runs and adds no permission-deny rules. For ordinary read-only tasks, state “do not modify files or perform Git writes” in the brief and check baseline/diff afterward. Existing OpenCode or project rules can still deny actions; `--auto` does not override them.

Full tool access is not authorization to expand scope. Include the workspace, deliverable, allowed changes, verification expectations, and authorized Git/external actions in the brief. The relay itself never commits; the child may commit, push, open a PR, or publish only when the task authorizes it. This adapter requires no special commit-only stage or custom reviewer/worker roles.

## Dispatch and Resume

Use the installed skill path reported by `skill_view`; invoke the helper through `terminal`:

```text
node <skill-dir>/scripts/relay.mjs --brief <brief-file> --cd <repo> --model zhipuai-coding-plan/glm-5.3 --out-dir <artifact-dir>
```

Briefs travel through stdin, never argv. Use a unique artifact directory outside the target working tree, under the Hermes scratch workspace or a durable task location. For long runs, use `terminal(background=true, notify=true)` and consume the completion notification rather than guessing a short timeout.

| Option | Purpose |
| --- | --- |
| `--brief <file>` | Brief file; omit to read stdin |
| `--cd <dir>` | Child working root |
| `--model <id>` | Outer model, `provider/model` or `provider/model#variant` |
| `--variant <level>` | Compose onto `--model`; do not also supply an inline variant |
| `--agent <name>` | Ordinary OpenCode primary-agent selection; default is built-in `build` |
| `--session <sessionId>` | Continue one exact OpenCode session |
| `--resume-last` | Fallback when the exact ID is unavailable; confirm the returned session belongs to this task |
| `--timeout <dur>` | Optional watchdog, off by default; only use a required hard bound, preferably a long guard such as `4h` |
| `--out-dir <dir>` | Unique run-artifact directory |

Resume for a same-task follow-up, with a delta brief and necessary new evidence. Start fresh when context or scope calls for it; this adapter does not require stage-specific session separation. OpenCode's built-in subagent capabilities remain available without the retired custom backend router or role definitions.

## Result Contract and Failure Handling

`result.json`, schema `delegate-relay.result.v1`, records terminal status and exit information, `opencodeVersion`, exact `sessionId`, requested/resolved model/variant/agent, `finalMessage`, `usage`, `touchedFiles`, and paths to brief/events/final/stderr/session-export artifacts. `session.json` is the parsed CLI session export; model/agent/usage metadata are extracted from it.

- Wait for process exit and read the result with `read_file`. A streamed fragment is not completion.
- `completed` confirms transport, not deliverable correctness. Check the report and relevant artifact/behavior evidence against the task.
- A clarifying question can also return `completed` with exit 0. Answer via exact-session resume when the answer is known; otherwise ask the user.
- `touchedFiles` is the final `git status --porcelain` snapshot under `--cd`, not attribution of child edits. Capture a baseline; inspect Git diff/history for committed changes too.
- On failure, timeout, or abort, preserve work and logs and inspect them before choosing resume/retry. Do not clean or start a replacement blindly.

See [references/dispatch-and-poll.md](references/dispatch-and-poll.md) for exact result and recovery semantics.

## Verification

Record the intended workspace, requested permissions, outer requested/resolved model, terminal status, exact session ID when emitted, and artifact paths. If no session was created, record that fact. Verify the requested deliverable separately using task-specific criteria; the transport adapter does not assign who plans, reviews, accepts, or lands it.
