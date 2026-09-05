---
name: cursor-delegate
description: Transport Cursor runs for development-orchestrator.
license: MIT
compatibility: Requires the authenticated Cursor `agent` CLI, Node 18+, and git.
metadata:
  version: 0.5.3
  hermes:
    related_skills: [development-orchestrator]
---

# Cursor Transport Adapter

Provide reliable Cursor Agent CLI transport for `development-orchestrator`: authentication preflight, workspace pinning, permission mode, model selection, structured artifacts, watchdogs, and exact-session resume. This adapter is not a development workflow, planner, reviewer, acceptance authority, or landing policy.

## When to Use

Load only when `development-orchestrator` has selected Cursor as the external parent agent.

Do not use this Skill to decide requirements, skip the pre-plan discussion, perform code review, define behavioral acceptance, or replace target-discovered Agent Skills.

## Preflight

Verify once:

```text
agent --version
agent status
agent models
```

Classify the whole outer run by its requested deliverable before selecting the parent model. Unless the user explicitly requests another model:

- **Lightweight/simple task:** when `development-orchestrator` selects its lightweight direct-delegation path, use Cursor Grok 4.6 High explicitly with `--model cursor-grok-4.6-high`. This also covers narrow commit-only and read-only factual tasks. Confirm `cursor-grok-4.6-high` still appears in live `agent models` and record `resolvedModel`.
- **Default for substantial work:** use Claude Opus 5 with high effort for structured, complex, mixed, or ambiguous tasks and any run involving planning, review, product judgment, architecture, persistence, migration, or other load-bearing decisions. Pass the live supported slug explicitly as `--model claude-opus-5-thinking-high`. As of Cursor CLI `2026.08.25-3e8eec8`, `agent models` labels this slug `Claude Opus 5 1M Thinking`; model labels and allocations can change, so verify the live label before dispatch and require `resolvedModel` to confirm the intended 1M allocation rather than a silent 300K fallback.

If lightweight repository discovery reveals broader coupling or consequential judgment, stop expansion and reclassify the task before continuing with the Opus default. Confirm the selected ID appears in live `agent models` before dispatch.

Confirm the intended repository and trust it before passing `--cd`. The relay always supplies Cursor workspace trust for headless operation.

## Relay

Use the bundled helper:

```text
node <this-skill>/scripts/relay.mjs --brief <file> --cd <repo> [options]
```

Important options:

| Option | Purpose |
| --- | --- |
| `--read-only` | Cursor plan mode; default for fresh runs |
| `--force` | Explicitly allow edits and commands |
| `--model <id>` | Outer Cursor parent model |
| `--session <id>` | Resume one exact Cursor chat |
| `--resume-last` | Fallback only when no exact ID exists |
| `--sandbox enabled\|disabled` | Explicit sandbox override |
| `--add-dir <dir>` | Additional workspace root |
| `--timeout <dur>` | Optional Relay watchdog; default off. Use only when the user asks for a hard bound or the environment requires one; prefer a very long guard such as `4h` over a short task estimate. |
| `--out-dir <dir>` | Stable artifact directory |

The brief is passed through stdin, not argv. The relay never commits.

## Development-Orchestrator Stages

### Ordinary pre-plan discussion

Start fresh with `--read-only`. Preserve the returned `sessionId`. Every follow-up uses `--session <id> --read-only` and contains only the new discussion turn. Do not invoke an entry Skill unless `development-orchestrator` explicitly reaches that phase.

### Explicit write-plan

Resume the established discussion session with `--session <id> --force`. The prompt explicitly invokes `/write-plan`. The target Skill, not this adapter, restricts the allowed planning write.

### Explicit execute-plan

Start a fresh run with `--force` and an explicit `/execute-plan` prompt containing the exact plan path. Preserve the new execution `sessionId` separately from the discussion/planning session.

### Behavioral rework

Resume the exact execution session with `--session <execution-id> --force` and the observed behavior-failure packet. Never replace a resumable execution session with a fresh agent.

## Result Contract

The relay writes `result.json` with fields including:

- terminal status and exit information;
- `cursorAgentVersion`;
- `sessionId`;
- `resolvedModel`;
- permission and requested sandbox data;
- `finalMessage`;
- `touchedFiles`; and
- paths to brief, final text, events, and stderr artifacts.

Completion means the child process exited and `result.json` exists. A progress display or final-message fragment is not completion.

On timeout, abort, or failure, preserve the working tree and artifacts for `development-orchestrator`; do not clean, retry, or start a replacement blindly.

## Boundary

- The target Cursor parent owns repository investigation, planning, implementation, tests, internal review, and preparing the product artifact.
- The target-discovered entry Skill owns internal subagents and domain Skills.
- Hermes owns product discussion and real behavior acceptance under `development-orchestrator`.
- This adapter owns only transport mechanics.

Do not inspect code or rerun gates because this adapter says so. Do not commit unless the controlling workflow separately and explicitly authorizes a commit-only run of already-prepared changes. Never push, create a PR, release, deploy, publish, or change versions.

## Verification

A transport run is valid only when the intended repository, permission mode, outer model, exact session ID, terminal result status, and artifact paths are recorded for the controlling `development-orchestrator` workflow.

For detailed relay failure semantics, see [references/dispatch-and-poll.md](references/dispatch-and-poll.md).
