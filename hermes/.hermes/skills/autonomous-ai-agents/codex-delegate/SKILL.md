---
name: codex-delegate
description: Transport Codex runs for development-orchestrator.
license: MIT
compatibility: Requires the authenticated OpenAI Codex CLI, Node 18+, and git.
metadata:
  version: 0.5.2
  hermes:
    related_skills: [development-orchestrator]
---

# Codex Transport Adapter

Provide reliable Codex CLI transport for `development-orchestrator`: binary/authentication preflight, workspace pinning, sandbox mode, outer model and effort, structured artifacts, watchdogs, and exact-thread resume. This adapter is not a development workflow, planner, reviewer, acceptance authority, or landing policy.

## When to Use

Load only when `development-orchestrator` has selected Codex as the external parent agent.

Do not use this Skill to decide requirements, decide whether Origin grounding is needed, perform code review, define behavioral acceptance, or replace target-discovered Agent Skills.

## Preflight

Verify once:

```text
command -v codex
codex --version
codex login status
```

Multiple Codex installations are common; record the active binary and version. Classify the whole outer run by its requested deliverable before selecting the parent model. Unless the user explicitly requests another model or effort level:

- **Default:** use `gpt-5.6-sol` with `high` reasoning and pass both explicitly as `--model gpt-5.6-sol --effort high`.
- **Narrow lightweight exception:** use `gpt-5.6-terra` with `high` reasoning and pass `--model gpt-5.6-terra --effort high` only when the complete requested deliverable is either (a) an explicitly authorized local Git commit of already-prepared changes, with no implementation, planning, review, or behavior decision, or (b) read-only factual exploration or retrieval, with no recommendation, design, review, implementation, or file change.

If the task is mixed or ambiguous, if exploration feeds implementation, or if any load-bearing judgment is required, use the Sol default. These options set the outer Codex parent only, not its built-in subagents.

## Relay

Use the bundled helper:

```text
node <this-skill>/scripts/relay.mjs --brief <file> --cd <repo> [options]
```

Important options:

| Option | Purpose |
| --- | --- |
| `--read-only` | Shortcut for enforced read-only sandbox |
| `--sandbox read-only\|workspace-write\|danger-full-access` | Parent sandbox; local default is read-only |
| `--model <id>` | Outer Codex parent model |
| `--effort <level>` | Outer parent reasoning effort |
| `--session <threadId>` | Resume one exact Codex thread |
| `--resume-last` | Fallback only when no exact thread ID exists |
| `--clean-env` / `--keep-env <name>` | Optional inherited-environment filtering |
| `--skip-git-repo-check` | Explicit non-repository exception |
| `--timeout <dur>` | Optional Relay watchdog; off by default. Normal orchestration omits it; if an external hard bound is required, prefer a deliberately long guard such as `4h` over a task-duration estimate. |
| `--out-dir <dir>` | Stable artifact directory |

The brief is passed through stdin, not argv. The relay never commits.

## Development-Orchestrator Stages

### Optional Origin grounding

For product discussion only, start fresh with `--read-only`; follow-ups may resume the exact `threadId`. This thread is ephemeral and must never be passed to a Dispatcher worker or reused for Planning/Execution.

### Explicit write-plan

Start a fresh Planning Parent with `--sandbox workspace-write` and no Origin `--session`. Begin the brief with `$write-plan`, include the complete converged Card contract, and require the exact final Plan path plus top-level gate/artifact outcome. The target Skill owns its internal workflow and allowed planning writes.

### Explicit execute-plan

Start a separate fresh Execution Parent with `--sandbox workspace-write` and no Planning `--session`. Begin the brief with `$execute-plan` and include the exact accepted Plan path. Preserve the returned execution `threadId` for same-scope rework.

### Behavioral rework

Resume the exact execution thread with `--session <execution-id> --sandbox workspace-write` and the observed behavior-failure packet. Never replace a resumable execution thread with a fresh agent.

## Result Contract

The relay writes `result.json` with fields including:

- terminal status and exit information;
- `codexVersion`;
- `threadId`;
- requested model, effort, and sandbox;
- `finalMessage`;
- `touchedFiles`; and
- paths to brief, events, and final-message artifacts.

Completion means the child process exited and `result.json` exists. A progress display or final-message fragment is not completion.

On timeout, abort, or failure, preserve the working tree and artifacts for `development-orchestrator`; do not clean, retry, or start a replacement blindly.

## Boundary

- The target Codex parent owns repository investigation, planning, implementation, tests, internal review, and preparing the product artifact.
- The target-discovered entry Skill owns internal subagents and domain Skills.
- Hermes owns product discussion and real behavior acceptance under `development-orchestrator`.
- This adapter owns only transport mechanics.

Do not inspect code or rerun gates because this adapter says so. Do not commit unless the controlling workflow separately and explicitly authorizes a commit-only run of already-prepared changes. Never push, create a PR, release, deploy, publish, or change versions.

## Verification

A transport run is valid only when the intended repository, sandbox, outer model/effort, exact thread ID, terminal result status, and artifact paths are recorded for the controlling `development-orchestrator` workflow.

For detailed relay failure semantics, see [references/dispatch-and-poll.md](references/dispatch-and-poll.md).
