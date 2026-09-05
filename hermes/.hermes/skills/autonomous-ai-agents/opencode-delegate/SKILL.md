---
name: opencode-delegate
description: Transport OpenCode runs for development-orchestrator.
version: 0.1.1
author: 柯楠, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [development, opencode, transport, delegation]
    related_skills: [development-orchestrator, opencode]
---

# OpenCode Transport Adapter

Provide OpenCode CLI transport for `development-orchestrator`: preflight, workspace and permission pinning, outer model selection, artifact capture, watchdogs, and exact-session resume. It does not decide requirements, workflow, review, acceptance, or landing.

## When to Use

Load only after `development-orchestrator` selects OpenCode. Use the general `opencode` Skill for direct TUI use, PR review, statistics, or ordinary one-shot tasks outside this workflow.

## Preflight and Model Policy

Verify with `terminal`:

```text
command -v opencode
opencode --version
opencode auth list
opencode models
opencode agent list
```

Use exact IDs from `opencode models`; never invent or normalize one. Unless the user overrides the current task:

- **Substantial/structured:** `zhipuai-coding-plan/glm-5.3 --variant high` for planning, review, design, implementation, architecture, persistence, migration, or other consequential judgment.
- **Lightweight:** `opencode-go/deepseek-v4-pro --variant high` only for the orchestrator's narrow simple path, commit-only work, or factual read-only retrieval with no recommendation/design/review/file change.

GLM supports `low|high|max`; DeepSeek supports `high|max`. Pass model and variant explicitly, confirm availability immediately before dispatch, and require `result.json` to report the same resolved outer model. If lightweight work exposes broad coupling or consequential judgment, stop and reclassify before using GLM.

Confirm the repository before `--cd` and verify its `.agents/skills` discovery path. The Relay model selects only the outer OpenCode parent; internal subagent models belong to target-discovered Skills.

## Relay

```text
node <this-skill>/scripts/relay.mjs --brief <file> --cd <repo> [options]
```

| Option | Meaning |
|---|---|
| `--read-only` | Default `plan` Agent with process-level deny rules for edits, shell, and external-directory writes. |
| `--write` | Writable `build` Agent plus auto-approval for requests not already denied. |
| `--model <provider/model>` | Exact outer parent model. |
| `--variant <level>` | Explicit provider-supported reasoning level. |
| `--agent <name>` | Override `plan`/`build`. |
| `--session <id>` | Resume one exact session. |
| `--resume-last` | Fallback only; “last” is global to project context. |
| `--timeout <dur>` | Optional watchdog, off by default; prefer none or a long guard such as `4h`. |
| `--out-dir <dir>` | Stable artifact directory. |

The brief travels through stdin, never argv. The Relay runs `opencode run --format json` without `--pure`, so curated plugins load; new plugins require Relay-impact review. The Relay never commits.

`--write` uses OpenCode `--auto`, which may approve any request not denied by configuration. Use only for a trusted repository and an authorized writable phase; it is not an OS sandbox.

## Stage Mapping

- **Discussion:** start `--read-only`, preserve `sessionId`, and resume every turn with `--session <id> --read-only`. Do not invoke an entry Skill yet.
- **`write-plan`:** resume that exact session with `--write` and invoke the discovered `write-plan` Skill; the target Skill restricts intended writes.
- **`execute-plan`:** start a fresh `--write` session with the accepted plan path and invoke the discovered `execute-plan` Skill. Preserve its separate execution `sessionId`.
- **Rework:** resume the exact execution session with `--session <execution-id> --write` and the observed failure/missing-contract packet.

## Result Contract

`result.json` records terminal status/exit, OpenCode version, exact `sessionId`, requested/resolved model/variant/Agent, permission mode, available usage, `finalMessage`, `touchedFiles`, and paths to brief/events/final/stderr/session artifacts.

Completion requires child-process exit and a valid `result.json`; a streamed text fragment or idle-looking event is not terminal. On timeout, abort, or failure, preserve the working tree and artifacts for the orchestrator—do not clean, retry, or replace the session blindly.

## Boundaries

The OpenCode parent owns engineering; target-discovered Skills own internal subagents and domain procedures; Hermes owns product decisions and real UI acceptance; this adapter owns transport only.

Never use this adapter as a reason to inspect code or rerun gates. Never push, open a PR, release, deploy, publish, change versions, or ask OpenCode to commit. Workflow and brief remain authoritative because the Relay cannot technically prohibit every shell spelling of an external action.

## Verification

A run is valid only when repository, permission mode, requested/resolved model, exact session, terminal result, and artifact paths are recorded.

```text
node <this-skill>/scripts/relay.mjs --brief smoke.txt --cd <trusted-repo> --read-only --model <provider/model> --out-dir <artifact-dir>
```

Smoke success requires exit `0`, `status: completed`, non-empty `sessionId`, expected final text, and unchanged Git state. Resume the exact session once to verify continuity. See `references/dispatch-and-poll.md` for failure semantics.
