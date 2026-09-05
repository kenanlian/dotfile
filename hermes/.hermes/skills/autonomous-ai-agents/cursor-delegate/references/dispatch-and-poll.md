# Dispatch and poll

`scripts/relay.mjs` wraps Cursor's headless print mode (`agent -p`), captures its structured
stream, and writes a `result.json`. Run one command, then read one file.

## Before the first run

```bash
command -v agent
agent --version
agent status
```

Follow the installer for your platform at [cursor.com/cli](https://cursor.com/cli), inspect what it
will run, then authenticate with `agent login`. On Windows the CLI installs as a `.cmd` shim;
the relay handles that launch itself, no setup needed.

## Dispatching

```bash
node "<skill-dir>/scripts/relay.mjs" --brief brief.txt --cd /path/to/repo
```

`<skill-dir>` is the installed folder containing this skill's `SKILL.md`.

| Flag | Effect |
| --- | --- |
| `--brief <file>` | Brief path. Omit it to read the brief from stdin. |
| `--cd <dir>` | Working root and child process cwd (default: current directory). |
| `--lane <name>` | Fleet lane from `delegate-setup` config. Applies that lane's dials; fails if the lane's `implementer` is not this relay. Explicit dial flags win. |
| `--model <name>` | Cursor model for this run (default: your Cursor default, usually `auto`). Names come from `agent models`. |
| `--read-only` | Run in Cursor's plan mode: read-only analysis, no edits (the local default). |
| `--force` | Explicitly enable writes and automatic command approval. |
| `--sandbox <mode>` | Override Cursor's sandbox for this dispatch: `enabled` or `disabled`. |
| `--no-force` | Rejected by this locally hardened variant; use `--read-only` or explicit `--force`. |
| `--session <id>` | Resume a specific Cursor chat (`--resume <id>`); send only the delta brief. |
| `--resume-last` | Resume the most recent Cursor chat (`--continue`); send only the delta brief. |
| `--add-dir <dir>` | Add an extra workspace root on Cursor `2026.07.23` or newer. Repeatable. Edits there are not reported in `touchedFiles`. |
| `--timeout <dur>` | Optional Relay watchdog (default: off; h/m/s strings). Normal orchestration omits it; if an external hard bound is required, prefer a deliberately long guard such as `4h`. agent has no timeout flag. |
| `--out-dir <dir>` | Artifact directory (default: a fresh directory under the system temp dir). |
| `-h`, `--help` | Print the relay's header help. |

`--session` and `--resume-last` are mutually exclusive. The child cwd pins the primary workspace;
`--add-dir` adds extra workspace roots only.

A fresh run defaults to read-only plan mode. Writing requires an explicit `--force`, which enables
file edits and automatic command approval unless Cursor config denies an action. `--no-force` is
rejected by this locally hardened variant. The relay always passes `--trust` so a headless run never
stalls on the workspace-trust prompt — point `--cd` only at repositories you trust.

## Artifacts and result fields

Artifacts live outside the repo by default, so they do not appear in `touchedFiles`; an `--out-dir`
inside the worktree can make the artifacts appear there:

- `brief.txt` — the exact brief.
- `events.jsonl` — raw agent stdout events.
- `final.txt` — the final report; absent if none was emitted.
- `stderr.txt` — complete stderr.
- `result.json` — the stable `delegate-relay.result.v1` contract.

`result.json` fields:

- `schema`, `tool` (`"agent"`), `status` (`completed` | `failed` | `timeout` | `aborted` |
  `cursor_agent_unavailable`), `exitCode`, and `signal` (`null` unless the child died on a signal).
- `workdir`, `model` (the requested name or `null`), `resolvedModel` (the model Cursor actually
  served, from its init event), `permissionMode` (the mode Cursor reported applying), `readOnly`,
  `force`, `sandbox` (the requested value or `null`, not a claim about what Cursor applied),
  `resumed`, `cursorAgentVersion`, `sessionId`, `startedAt`, and `finishedAt`.
- `briefPath`, `finalPath`, `eventsPath`, and `stderrPath`.
- `finalMessage` — in read-only plan mode, the newest `createPlan` payload when Cursor emits one;
  otherwise the `result` field of Cursor's closing event, falling back to assistant text chunks when
  the run ended without either. Other tool calls and tool results are excluded.
- `touchedFiles` — `git status --porcelain` lines for the **final working tree under `--cd` only**,
  not an attribution of Cursor's edits: anything already dirty before dispatch shows up too, and
  edits Cursor makes inside `--add-dir` roots do not show up at all — inspect those trees yourself.
  Dispatch from a clean tree when you want the list to read as "what Cursor changed". `null` means
  git could not report; `[]` means git ran and the tree is clean.
- `usage` — Cursor's token-usage object from the closing result event, or `null` if no result event
  supplied one.
- `stderrTail` — the last 20 non-empty stderr lines on any run that did not complete (`failed`,
  `timeout`, `aborted`), except a launch failure, which reports `failed` with no `stderrTail`.
- `error` — present for launch failures, when the relay watchdog fires (`timeout`), on an `aborted`
  run, and when Cursor's own result event carries `is_error: true`.

## Waiting for completion

The helper blocks. Use the orchestrator's background-command facility, or background it in a shell
and poll for `result.json`. The run is done only when the process exits and the file contains a
`status`.

A pre-run usage error exits 2 and writes no result. A missing `agent` exits 127 and writes
`status: "cursor_agent_unavailable"`.

## When a run misbehaves

- **`status: "cursor_agent_unavailable"` (exit 127):** install the Cursor CLI, authenticate with
  `agent login`, and re-dispatch.
- **`status: "failed"`:** read `stderrTail`, `stderrPath`, and the tail of `events.jsonl`. If the
  result event carried `is_error: true` the relay reports `failed` even on a zero exit; Cursor's own
  message is in `finalMessage`. An unknown `--model` name fails fast — re-check against
  `agent models`.
- **A version-preflight failure:** the relay writes `failed` with the probe's exit code, or `timeout`
  with exit 124 when the probe exceeds the smaller of the run watchdog and 10 seconds. Cursor is not
  dispatched.
- **`status: "aborted"`:** the relay itself was killed (its parent's timeout, a stopped task, a
  closed terminal) and forwarded the kill to agent. The result is written before the relay
  exits; inspect the working tree before re-dispatching. On native Windows a hard kill of the relay
  is uncatchable (Node supports no `SIGTERM` handler there), so this status may never get written —
  a relay process that is gone without a `result.json` is an aborted run; inspect the working tree
  and `events.jsonl` directly.
- **`status: "failed"` with `signal: "SIGKILL"`:** the host killed the process, commonly through the
  OOM killer or a supervisor timeout. This is not a Cursor error; check host memory and re-dispatch,
  or split the task into smaller briefs.
- **`status: "timeout"`:** the `--timeout` watchdog killed the run; `error` reads
  `agent did not finish within --timeout <dur>; killed by the relay watchdog`. Increase
  `--timeout` or split the task. The relay sends SIGTERM, waits 10 seconds, then sends SIGKILL if
  needed (on Windows a single process-tree kill).
- **Empty `finalMessage`:** inspect `touchedFiles` and the diff. Add a
  `<structured_output_contract>` to the next brief to require a closing report.
- **Every command Cursor runs is rejected with "Hook blocked with message: … eval: … syntax error
  near unexpected token `&`" (or Cursor reports "the terminal hook failed"):** a agent bug,
  not a hook bug. When agent is launched from a Git Bash (MSYS) console on Windows — which
  is what an orchestrator's bash tool uses — it selects `bash.exe` as its persistent shell while
  still generating its hook wrappers in PowerShell syntax, so every configured hook (its own
  `~/.cursor/hooks.json` and any imported Claude Code `PreToolUse` hooks) errors and Cursor blocks
  the command, fail-closed. File edits still work; command execution does not — which also means
  Cursor cannot run the gates, only claim it could not. Workaround: dispatch the relay from a
  PowerShell or cmd console instead (observed fixed there); or temporarily remove the hook entries
  for the run. Verified on agent 2026.07.23.

## Recovering lost work

`events.jsonl` in the run directory records every event the implementer streamed. If finished
work is lost — the run killed late, or the working tree damaged afterward — read the event log
before re-dispatching: it identifies which files and tool commands were involved, which scopes
what needs redoing. Whether it also carries the edit contents depends on what the CLI streams,
so treat any reconstruction as unverified until it matches a working-tree diff — when the tree
still holds the work, preserve the tree rather than replaying the log.

## What the relay runs

The argv is equivalent to:

```bash
agent --print --output-format stream-json --trust \
  [--mode plan (default) | --force] [--sandbox enabled|disabled] [--model <name>] \
  [--resume <id> | --continue] \
  [--add-dir <dir> ...]   # brief on stdin
```

`--no-force` is rejected by this locally hardened variant.

The brief rides stdin, so it is not visible in the host process list and has no OS argument-size
cap. On Windows the launch goes through the shell so the `agent.cmd` shim resolves; the brief
still travels on stdin, sandbox, model, session, and directory values are validated, and spaceable
values are quoted.

## The commit boundary

The relay never commits. Cursor edits the working tree; the orchestrator reviews, re-runs the gates,
and commits. See [review-and-land.md](review-and-land.md).
