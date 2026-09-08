---
name: pi-delegate
description: Transport Pi runs for development-orchestrator.
license: MIT
compatibility: Requires the `pi` CLI (~/.local/bin/pi) 0.84.4+, Node 18+, and git.
metadata:
  version: 0.3.1
  hermes:
    related_skills: [development-orchestrator, pi-coding-agent]
---

# Pi Transport Adapter

Provide reliable Pi CLI transport for `development-orchestrator`: preflight, exact-cwd dispatch, read-only/write tool gating, explicit model and thinking, exact-session resume, structured artifacts, watchdog, and a truthful `delegate-relay.result.v1` result. This adapter is not a development workflow, planner, reviewer, acceptance authority, or landing policy.

## When to Use

Load only when `development-orchestrator` has selected Pi as the external parent agent.

Do not use this Skill to decide requirements, decide whether Origin grounding is needed, perform code review, define behavioral acceptance, or replace target-discovered Agent Skills.

## Preflight

Verify once:

```text
command -v pi
pi --version
pi --list-models <search>
```

Classify the whole outer run by its requested deliverable before selecting the model. Unless the user explicitly requests another model, each tier has a primary and a fallback (the fallback exists because the primary's quota can be exhausted):

- **Default for substantial work** (structured planning, review, architecture, persistence, migration, load-bearing decisions): primary `kimi-coding/k3`, fallback `zai-coding-cn/glm-5.3`; both with `--thinking high`.
- **Lightweight tier** (narrow read-only factual tasks, commit-only runs): primary `opencode-go/deepseek-v4-pro`, fallback `zai-coding-cn/glm-5.3`; both with `--thinking high`.

Models are provider-prefixed (`provider/model`), optionally with a `:thinking` suffix (`pi --model zai-coding-cn/glm-5.3:high`). If the brief's task scoping proves wrong mid-run, stop expansion and reclassify before continuing.

Switch to the fallback only when the primary actually fails from quota exhaustion or provider unavailability: re-dispatch once with the fallback `--model` (and same `--thinking`), resuming the exact recorded `--session` when the failed run had one. Record the switch — `result.json`'s `resolvedModel` reflects what actually ran.

Confirm the intended repository and trust it before passing `--cd`. Pi has no permission wall. `--read-only` removes top-level shell/edit/write tools, but `delegate_agent` remains available and can request a write child; review briefs must forbid the parent and every child from writing. This is an instruction boundary, not an OS sandbox.

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
| `--session <id>` | Resume one existing exact Pi session via Pi `--session`; fail if missing or mismatched. |
| `--timeout <dur>` | Optional relay watchdog; default off. Prefer a long guard (`4h`) over a task estimate. |
| `--out-dir <dir>` | Artifact directory (default: fresh dir under the system temp dir). |
| `--auto-handoff-plan <file>` | Enable top-level Auto Handoff: one additional `-e` plus child-process `PI_AUTO_HANDOFF_PLAN_FILE` (the exact validated plan path) and `PI_AUTO_HANDOFF_HANDOFF_DIR` (`<actual out dir>/auto-handoff`). `<file>` must be an absolute readable non-empty regular file. Absence disables atomically. |
| `-h`, `--help` | Relay header help. |

The brief is passed via a temp file consumed by Pi's final argv position, never as an inline stdin pipe mid-argv; the relay never commits.

Extension loading is deterministic: `--no-extensions` plus explicit `-e <delegate-agent-root>` so the `delegate_agent` tool exists and nothing implicit loads. When `--auto-handoff-plan` is present, the relay loads one additional `-e` for the auto-handoff extension root (discovery: `PI_AUTO_HANDOFF_ROOT`, then `~/Secret-Projects/pi-auto-handoff`; `PI_AUTO_HANDOFF_ROOT` is a relay-internal discovery override, not a workflow-facing parameter) and injects child-process-scoped `PI_AUTO_HANDOFF_PLAN_FILE` and `PI_AUTO_HANDOFF_HANDOFF_DIR`; it never mutates the relay's own environment. Delegated children keep `--no-extensions` and never receive the auto-handoff extension. Global Skills discovery stays enabled — Skills come from the single global root `~/Secret-Projects/agent_skills/skills` via the dotfile-managed `~/.pi/agent/skills` symlink; the relay never copies or mirrors Skills.

## Development-Orchestrator Stages

Execute-plan implement relays and every same-session execute-plan rework relay pass `--auto-handoff-plan <absolute accepted plan path>` (the same path the guard validated as `--plan-artifact`). Origin grounding, write-plan, direct, and all review relays never pass it; delegated children never receive Auto Handoff.

### Optional Origin grounding

For product discussion only, start fresh with `--read-only`; follow-ups may resume the exact `sessionId`. This Session is ephemeral and must never be passed to a Dispatcher worker or reused for Planning/Execution. Origin grounding relays never pass `--auto-handoff-plan`.

### Explicit write-plan

Start a fresh Planning Parent with `--write` and no Origin `--session`. Begin the brief with `Use the write-plan Skill (discovered from the global Skill root).`, include the complete converged Card contract, declare that the outer native Card review owns final plan review, and require the exact final Plan path/SHA plus top-level outcome. The target Skill skips its duplicate internal final-review cycle but owns planning internals and allowed planning writes. Write-plan relays never pass `--auto-handoff-plan`.

### Explicit execute-plan

Start a separate fresh Execution Parent with `--write`, `--auto-handoff-plan <absolute accepted plan path>` (the same path the guard validated as `--plan-artifact`), and no Planning `--session`. Begin the brief with `Use the execute-plan Skill (discovered from the global Skill root).`, include the exact accepted Plan path/SHA, and declare that the outer native Card review owns final patch/conformance review. Preserve the returned execution `sessionId` for same-scope rework.

### Card review

Start every review relay fresh with `--read-only`; never pass a planning/execution `--session`. Begin with the required `review-plan`, `review-patch`, or `review-plan-conformance` Skill directive and exact Plan/commit-range inputs. Explicitly forbid the reviewer and every delegated child from writing or invoking write-access children. Give each relay a unique out dir/result path, wait for process exit, and validate the terminal result directly; the write-mode external guard is not reused by Review Workers. Review relays never pass `--auto-handoff-plan`.

### Behavioral rework

Resume the exact recorded Pi `sessionId` with `--session <session-id> --write` and the observed failure packet. Execute-plan rework re-passes `--auto-handoff-plan` with the same accepted plan path (the same path the guard validated as `--plan-artifact`). Write-plan rework does not re-pass the option. The relay fails when that Session is absent or the observed ID differs; never replace it silently.

## Result Contract

The relay writes `result.json` (`delegate-relay.result.v1`):

- `schema`, `tool: "pi"`, `status` (`completed` | `failed` | `timeout` | `aborted` | `unavailable`), optional tool-specific `sourceStatus` (for example `pi_unavailable`), `exitCode`, `signal`.
- `piVersion`, `sessionId`, `cwd`, `mode` (`read-only` | `write`), `requestedModel`, `resolvedModel`, `thinking`, `resumed`.
- `startedAt`, `finishedAt`, `finalMessage`, `touchedFiles` (git porcelain snapshot under `--cd`), `usage` (last message usage when present).
- `briefPath`, `finalPath`, `eventsPath`, `stderrPath`, and `error`/`stderrTail` on failure.
- `autoHandoff` — `{ enabled, planFile, handoffDir, extensionRoot }` on every terminal path. Enabled: `{ enabled: true, planFile: "<abs>", handoffDir: "<abs>/auto-handoff", extensionRoot: "<root or null>" }`. Disabled: `{ enabled: false, planFile: null, handoffDir: null, extensionRoot: null }`.

`completed` requires: child process exit, exit code 0, Pi `agent_settled` observed in the event stream, a valid session id, and the atomically written result. Anything else is `failed`/`timeout`/`aborted` with artifacts and the working tree preserved. On failure the relay exits non-zero and never cleans artifacts.

Completion means the Pi process exited and `result.json` exists. A progress display or final-message fragment is not completion.

## Boundary

- The target Pi parent owns repository investigation, planning/implementation, tests, internal delegation, and preparing the product artifact. When the commissioning brief declares an outer native Card review, `write-plan`/`execute-plan` skip only their duplicate internal final-review cycles.
- The target-discovered entry Skill (e.g. `write-plan`) owns internal subagents and domain Skills.
- Hermes owns product discussion and real behavior acceptance under `development-orchestrator`.
- This adapter owns only transport mechanics.

Do not inspect code or rerun gates because this adapter says so. The relay never commits, pushes, creates PRs, releases, deploys, publishes, or changes versions.

## Verification

A transport run is valid only when the intended repository, mode, model, thinking, exact session id, terminal result status, and artifact paths are recorded for the controlling `development-orchestrator` workflow.

For detailed relay failure semantics, see [references/dispatch-and-poll.md](references/dispatch-and-poll.md).
