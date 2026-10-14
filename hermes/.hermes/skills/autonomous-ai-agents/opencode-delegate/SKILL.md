---
name: opencode-delegate
description: "Transport OpenCode CLI runs via relay.mjs: preflight, dispatch, exact-session resume, result contract. Full-permission policy."
version: 0.2.0
author: "柯楠, Hermes Agent"
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [development, opencode, transport, delegation]
    related_skills: [opencode]
---

# OpenCode Transport Adapter

Provide reliable OpenCode CLI transport: binary preflight, workspace pinning, structured artifacts, watchdogs, and exact-session resume. Verified against OpenCode v2.0.29. This adapter is not a development workflow, planner, reviewer, acceptance authority, or landing policy.

## When to Use

Load when commissioning an OpenCode CLI run that needs the result contract (thread persistence across context compression, rework resume, cross-session artifacts). For a quick one-shot question, direct `opencode run` in the `opencode` Skill is cheaper.

## Permission Policy (deliberate design choice)

The relay always passes `--auto` with **no deny rules** — every run has full permissions, including read-only tasks. Read-only-ness is expressed in the brief ("do not modify files") and relies on model instruction-following. The post-hoc check is `touchedFiles` + git diff review, not a sandbox. Do not reintroduce permission denies here without an explicit user decision; if a task cannot tolerate a stray write, do not dispatch it through this adapter.

## Preflight

Verify once:

```text
command -v opencode
opencode --version
opencode auth list
opencode models
```

v2 facts that bite:

- A bare `opencode run` without `--model` resolves to the opencode-go default, which **403s without an active Go subscription**. Always pass `--model` explicitly with a provider you have auth for (`opencode auth list`).
- `--variant` as a standalone flag is gone. Variant is inline: `--model provider/model#variant`.
- `opencode export <id>` is gone; it is `opencode session export <id>` now.
- Model selection policy (unless the user overrides): default `zhipuai-coding-plan/glm-5.3`; high-stakes or reasoning-heavy runs add `#high`. Use exact IDs from live `opencode models` output only.

## Relay

```text
node <this-skill>/scripts/relay.mjs --brief <file> --cd <repo> [options]
```

| Option | Purpose |
| --- | --- |
| `--brief <file>` | Brief path; omit to read stdin. Brief travels via stdin, never argv. |
| `--cd <dir>` | Working root and child cwd. |
| `--model <id>` | Outer model, `provider/model` or `provider/model#variant`. |
| `--variant <level>` | Convenience: composed onto `--model` as `#variant` (requires `--model`). |
| `--agent <name>` | Primary agent (default `build`). |
| `--session <id>` | Resume one exact OpenCode session (the `sessionId` from a prior result). |
| `--resume-last` | Fallback only when no exact session ID exists. |
| `--timeout <dur>` | Optional watchdog, off by default; prefer none or a long guard such as `4h`. |
| `--out-dir <dir>` | Stable artifact directory (default: system temp, outside the repo). |

The relay never commits.

## Result Contract

`result.json` (schema `delegate-relay.result.v1`) records terminal status (`completed` / `failed` / `timeout` / `aborted` / `unavailable`), exitCode, `opencodeVersion`, exact `sessionId` (the resume key), requested/resolved model/variant/agent, `finalMessage`, `usage`, `touchedFiles` (git porcelain under `--cd`), and paths to brief/events/final/stderr/session-export artifacts. `session.json` is the parsed `opencode session export` output; `resolvedModel`/`resolvedAgent`/`usage` are extracted from it (v2 shape: assistant messages carry `type: 'assistant'`, `content: [{type:'text',text}]`, `model: {id, providerID, variant}` directly).

Completion means the child process exited and `result.json` exists. A streamed text fragment is not completion. On timeout, abort, or failure, preserve the working tree and artifacts for the commissioning session; do not clean, retry, or start a replacement blindly.

`completed` does not mean "no question": if the child asks a clarifying question, it lands in `finalMessage` as plain text with status `completed` and exit 0 — machine-indistinguishable from a finished deliverable. Decide from the brief whether the answer is already known (answer it via resume); otherwise escalate to the user before resuming.

## Boundaries

- The OpenCode parent owns repository investigation, planning, implementation, tests, and preparing the product artifact.
- Hermes owns product decisions and real behavior acceptance.
- This adapter owns transport mechanics only. Do not inspect code or rerun gates because this adapter says so; never push, create a PR, release, deploy, or publish — commit only when the controlling workflow explicitly authorizes it.

## Verification

A transport run is valid only when repository, requested model, exact session ID, terminal result status, and artifact paths are recorded. Smoke pattern: fresh run expecting an exact reply token → require `status: completed`, exact `finalMessage`, non-empty `sessionId`, matching `resolvedModel`; then resume the exact session and require it to recall the prior token. See `references/dispatch-and-poll.md` for failure semantics.
