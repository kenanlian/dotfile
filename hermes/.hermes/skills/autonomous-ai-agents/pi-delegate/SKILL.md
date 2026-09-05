---
name: pi-delegate
description: Transport Pi runs for development-orchestrator.
license: MIT
compatibility: Requires the `pi` CLI (~/.local/bin/pi) 0.84.4+, Node 18+, and git.
metadata:
  version: 0.1.0
  hermes:
    related_skills: [development-orchestrator, pi-coding-agent]
---

# Pi Transport Adapter

Provide reliable Pi CLI transport for `development-orchestrator`: preflight, exact-cwd dispatch, read-only/write tool gating, explicit model and thinking, exact-session resume, structured artifacts, watchdog, and a truthful `delegate-relay.result.v1` result. This adapter is not a development workflow, planner, reviewer, acceptance authority, or landing policy.

## When to Use

Load only when `development-orchestrator` has selected Pi as the external parent agent.

Do not use this Skill to decide requirements, skip the pre-plan discussion, perform code review, define behavioral acceptance, or replace target-discovered Agent Skills.

## Preflight

Verify once:

```text
command -v pi
pi --version
pi --list-models <search>
```

Classify the whole outer run by its requested deliverable before selecting the model. Unless the user explicitly requests another model:

- **Default for substantial work** (structured planning, review, architecture, persistence, migration, load-bearing decisions): `zai-coding-cn/glm-5.3` with `--thinking high`.
- **Lightweight tier** (narrow read-only factual tasks, commit-only runs): `zai-coding-cn/glm-5.3-flash` or `opencode-go/deepseek-v4-flash` with `--thinking off` or `minimal`.

Models are provider-prefixed (`provider/model`), optionally with a `:thinking` suffix (`pi --model zai-coding-cn/glm-5.3:high`). If the brief's task scoping proves wrong mid-run, stop expansion and reclassify before continuing.

Confirm the intended repository and trust it before passing `--cd`. Pi has no permission wall; `--read-only` is enforced by the tool allowlist below, nothing else.

## Relay

Use the bundled helper:

```text
node <this-skill>/scripts/relay.mjs --brief <file> --cd <repo> [options]
```

| Option | Purpose |
| --- | --- |
| `--brief <file>` | Brief path. Omit to read the brief from stdin. |
| `--cd <dir>` | Exact working root and child cwd (default: relay cwd). |
| `--read-only` | Tool allowlist `read,grep,find,ls,delegate_agent`. Default for fresh runs. |
| `--write` | Tool allowlist `read,grep,find,ls,bash,edit,write,delegate_agent`. |
| `--model <id>` | Explicit `provider/model[:thinking]` id. |
| `--thinking <level>` | `off\|minimal\|low\|medium\|high\|xhigh\|max`. Default `high`. |
| `--session <id>` | Resume one exact Pi session (`--session-id`), create-if-missing. |
| `--timeout <dur>` | Optional relay watchdog; default off. Prefer a long guard (`4h`) over a task estimate. |
| `--out-dir <dir>` | Artifact directory (default: fresh dir under the system temp dir). |
| `-h`, `--help` | Relay header help. |

The brief is passed via a temp file consumed by Pi's final argv position, never as an inline stdin pipe mid-argv; the relay never commits.

Extension loading is deterministic: `--no-extensions` plus explicit `-e <delegate-agent-root>` so the `delegate_agent` tool exists and nothing implicit loads. Global Skills discovery stays enabled — Skills come from the single global root `~/Secret-Projects/agent_skills/skills` via the dotfile-managed `~/.pi/agent/skills` symlink; the relay never copies or mirrors Skills.

## Development-Orchestrator Stages

### Ordinary pre-plan discussion

Start fresh with `--read-only`. Preserve the returned `sessionId`. Every follow-up uses `--session <id> --read-only` and contains only the new discussion turn.

### Explicit write-plan

Resume the established discussion session with `--session <id> --write`. The prompt explicitly invokes `write-plan`. The target Skill, not this adapter, restricts the allowed planning write.

### Explicit execute-plan

Start a fresh run with `--write` and an explicit `execute-plan` prompt containing the exact plan path. Preserve the new execution `sessionId` separately from the discussion session.

### Behavioral rework

Resume the exact execution session with `--session <execution-id> --write` and the observed failure packet. Never replace a resumable execution session with a fresh agent.

## Result Contract

The relay writes `result.json` (`delegate-relay.result.v1`):

- `schema`, `tool: "pi"`, `status` (`completed` | `failed` | `timeout` | `aborted` | `pi_unavailable`), `exitCode`, `signal`.
- `piVersion`, `sessionId`, `cwd`, `mode` (`read-only` | `write`), `requestedModel`, `resolvedModel`, `thinking`, `resumed`.
- `startedAt`, `finishedAt`, `finalMessage`, `touchedFiles` (git porcelain snapshot under `--cd`), `usage` (last message usage when present).
- `briefPath`, `finalPath`, `eventsPath`, `stderrPath`, and `error`/`stderrTail` on failure.

`completed` requires: child process exit, exit code 0, Pi `agent_settled` observed in the event stream, a valid session id, and the atomically written result. Anything else is `failed`/`timeout`/`aborted` with artifacts and the working tree preserved. On failure the relay exits non-zero and never cleans artifacts.

Completion means the Pi process exited and `result.json` exists. A progress display or final-message fragment is not completion.

## Boundary

- The target Pi parent owns repository investigation, planning, implementation, tests, internal review, and preparing the product artifact.
- The target-discovered entry Skill (e.g. `write-plan`) owns internal subagents and domain Skills.
- Hermes owns product discussion and real behavior acceptance under `development-orchestrator`.
- This adapter owns only transport mechanics.

Do not inspect code or rerun gates because this adapter says so. The relay never commits, pushes, creates PRs, releases, deploys, publishes, or changes versions.

## Verification

A transport run is valid only when the intended repository, mode, model, thinking, exact session id, terminal result status, and artifact paths are recorded for the controlling `development-orchestrator` workflow.

For detailed relay failure semantics, see [references/dispatch-and-poll.md](references/dispatch-and-poll.md).
