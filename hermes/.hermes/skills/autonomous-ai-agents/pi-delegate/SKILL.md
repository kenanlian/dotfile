---
name: pi-delegate
description: Transport Pi CLI runs: preflight, dispatch, exact-session resume, structured result contract.
license: MIT
compatibility: Requires the `pi` CLI (~/.local/bin/pi) 0.84.4+, Node 18+, and git.
metadata:
  version: 0.5.0
  hermes:
    related_skills: [pi-coding-agent]
---

# Pi Transport Adapter

Provide reliable Pi CLI transport: preflight, exact-cwd dispatch, read-only/write tool gating, explicit model and thinking, exact-session resume, structured artifacts, watchdog, and a truthful `delegate-relay.result.v1` result. This adapter is not a development workflow, planner, reviewer, acceptance authority, or landing policy.

## When to Use

Load when commissioning any Pi CLI run — a delegated relay or a one-off current-session run. This Skill provides transport only.

Do not use this Skill to decide requirements, decide whether grounding is needed, perform code review, define behavioral acceptance, or replace target-discovered Agent Skills.

## Preflight

Verify once:

```text
command -v pi
pi --version
pi --list-models <search>
```

An explicit model from the commissioner always wins. Otherwise, unless the user explicitly requests another model:

- **Write-mode implement relays** and their same-session rework: primary `kimi-coding/k3`, fallback `zai-coding-cn/glm-5.3`.
- **Read-only review and grounding relays**: `zai-coding-cn/glm-5.3`, no fallback.

All tiers run `--thinking high`. Models are provider-prefixed (`provider/model`), optionally with a `:thinking` suffix (`pi --model zai-coding-cn/glm-5.3:high`). If the brief's task scoping proves wrong mid-run, stop expansion and reclassify before continuing.

Switch to the fallback only when the primary actually fails from quota exhaustion or provider unavailability: re-dispatch once with the fallback `--model` (and same `--thinking`), resuming the exact recorded `--session` when the failed run had one. Record the switch — `result.json`'s `resolvedModel` reflects what actually ran. glm-5.3 relays have no fallback: quota exhaustion or provider unavailability there is a terminal relay failure the commissioning Worker blocks on (typed `transient`/`capability`), never a silent model substitution.

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
| `--review-output plan\|execute` | Review relays only (never with `--write`). Loads the review-submit extension via `-e`, adds exactly the stage submit tool (`submit_plan_review` or `submit_execute_review`) to the read-only allowlist, and captures exactly one successful expected-tool result into `structuredOutput`. Mutually exclusive with `--structured-output-*`. |
| `--review-output-recovery` | Single output-only recovery turn. Requires `--session` and `--review-output`. Child allowlist is only the stage submit tool; an output-only instruction is appended. |
| `--structured-output-tool <name>` | Trusted/Harness transport surface. Capture exactly one successful result from this submit tool. Must be paired with `--structured-output-extension`. Allowed with `--write`. Mutually exclusive with `--review-output`. |
| `--structured-output-extension <dir>` | Absolute extension root containing `index.ts` or `index.js`. Must be paired with `--structured-output-tool`. |
| `--structured-output-recovery` | Single output-only recovery turn. Requires `--session` plus the generic tool/extension pair. Child allowlist is only that submit tool. |
| `-h`, `--help` | Relay header help. |

The brief is passed to Pi on the child's stdin (no positional argument; pi consumes piped stdin as the initial prompt), never in argv; a first line of `/skill:<name> ` (name, then a space on the same line) is expanded by Pi into the full Skill even when that Skill is hidden by `disable-model-invocation: true` — always address commissioning Skills this way instead of prose-only references. The relay validates the `/skill:` first line shape and fails fast on a malformed one; the relay never commits.

Extension loading is deterministic: `--no-extensions` plus explicit `-e <delegate-agent-root>` so the `delegate_agent` tool exists and nothing implicit loads. When `--auto-handoff-plan` is present, the relay loads one additional `-e` for the auto-handoff extension root (discovery: `PI_AUTO_HANDOFF_ROOT`, then `~/Secret-Projects/pi-auto-handoff`; `PI_AUTO_HANDOFF_ROOT` is a relay-internal discovery override, not a workflow-facing parameter) and injects child-process-scoped `PI_AUTO_HANDOFF_PLAN_FILE` and `PI_AUTO_HANDOFF_HANDOFF_DIR`; it never mutates the relay's own environment. When `--review-output` is present, the relay loads one additional `-e` for the review-submit extension root (bundled at `extensions/review-submit/`; override `PI_REVIEW_SUBMIT_ROOT`) and enables exactly the stage submit tool. When `--structured-output-tool` and `--structured-output-extension` are present, the relay loads that absolute extension root via `-e` and enables exactly that submit tool (including in `--write` mode). The two flag families are mutually exclusive. Delegated children keep `--no-extensions` and never receive the auto-handoff, review-submit, or generic structured-output extension. Global Skills discovery stays enabled — Skills come from the single global root `~/Secret-Projects/agent_skills/skills` via the dotfile-managed `~/.pi/agent/skills` symlink; the relay never copies or mirrors Skills.

## Common run patterns

### Read-only grounding run

Start fresh with `--read-only`; follow-ups may resume the exact `sessionId`. Never pass `--auto-handoff-plan` to a read-only run.

### Write-mode implement run

Start a fresh parent with `--write` under the implement model (primary `kimi-coding/k3`, fallback `zai-coding-cn/glm-5.3`). Begin the brief with the first line `/skill:<entry-skill> ` (trailing space, then the task body), include the complete task contract, and require the exact deliverable plus top-level outcome. Preserve the returned `sessionId` for same-scope rework.

### Read-only review run with structured output

Start every review relay fresh with `--read-only --review-output plan|execute` under `zai-coding-cn/glm-5.3` (no fallback); never pass an implement `--session`. Begin with the first line `/skill:<review-skill> ` (trailing space) plus exact review inputs, and explicitly forbid the reviewer and every delegated child from writing or invoking write-access children. Give each relay a unique run-scoped out dir/result path, wait for process exit, and consume `structuredOutput` (tool + payload); `finalMessage` is diagnostic only and is not parsed. If a terminal review result lacks a valid `structuredOutput`, re-issue one `--review-output-recovery --session <id>` turn. Review relays never pass `--auto-handoff-plan`.

### Session resume for rework

Resume the exact recorded Pi `sessionId` with `--session <session-id> --write` plus the observed failure packet and the implement model of its relay family. The relay fails when that Session is absent or the observed ID differs; never replace it silently.

## Result Contract

The relay writes `result.json` (`delegate-relay.result.v1`):

- `schema`, `tool: "pi"`, `status` (`completed` | `failed` | `timeout` | `aborted` | `unavailable`), optional tool-specific `sourceStatus` (for example `pi_unavailable`), `exitCode`, `signal`.
- `piVersion`, `sessionId`, `cwd`, `mode` (`read-only` | `write`), `requestedModel`, `resolvedModel`, `thinking`, `resumed`.
- `startedAt`, `finishedAt`, `finalMessage`, `touchedFiles` (git porcelain snapshot under `--cd`), `usage` (last message usage when present).
- `structuredOutput` — `{ tool, payload }` when `--review-output` or `--structured-output-tool` captured exactly one successful expected-tool result; otherwise `null`. Absent those flags, always `null`.
- `structuredOutputError` — diagnostic string when a structured-output capture is requested and is not exactly one successful expected-tool result (missing, duplicate, or any error result from the expected tool); otherwise `null`.
- `briefPath`, `finalPath`, `eventsPath`, `stderrPath`, and `error`/`stderrTail` on failure.
- `autoHandoff` — `{ enabled, planFile, handoffDir, extensionRoot }` on every terminal path. Enabled: `{ enabled: true, planFile: "<abs>", handoffDir: "<abs>/auto-handoff", extensionRoot: "<root or null>" }`. Disabled: `{ enabled: false, planFile: null, handoffDir: null, extensionRoot: null }`.

`completed` requires: child process exit, exit code 0, Pi `agent_settled` observed in the event stream, a valid session id, and the atomically written result. Anything else is `failed`/`timeout`/`aborted` with artifacts and the working tree preserved. On failure the relay exits non-zero and never cleans artifacts.

Completion means the Pi process exited and `result.json` exists. A progress display or final-message fragment is not completion.

## Boundary

- The target Pi parent owns repository investigation, planning/implementation, tests, internal delegation, and preparing the product artifact. When the commissioning brief declares an outer native Card review, `write-plan`/`execute-plan` skip only their duplicate internal final-review cycles.
- The target-discovered entry Skill (e.g. `write-plan`) owns internal subagents and domain Skills.
- Hermes owns product discussion and real behavior acceptance.
- This adapter owns only transport mechanics.

Do not inspect code or rerun gates because this adapter says so. The relay never commits, pushes, creates PRs, releases, deploys, publishes, or changes versions.

## Verification

A transport run is valid only when the intended repository, mode, model, thinking, exact session id, terminal result status, and artifact paths are recorded for the commissioning session.

For detailed relay failure semantics, see [references/dispatch-and-poll.md](references/dispatch-and-poll.md).
