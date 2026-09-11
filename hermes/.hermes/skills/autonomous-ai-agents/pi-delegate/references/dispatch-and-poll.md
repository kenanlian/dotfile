# Dispatch and poll

`scripts/relay.mjs` wraps Pi's headless print mode (`pi -p --mode json`), captures its
NDJSON event stream, and writes a `result.json` (`delegate-relay.result.v1`). Run one
command, then read one file.

## Before the first run

```bash
command -v pi          # ~/.local/bin/pi on Kenan's machine
pi --version           # 0.84.4 verified
pi --list-models glm   # browse provider-prefixed model ids
```

Install/config reference: the `pi-coding-agent` Skill. The relay needs no other setup;
it discovers the delegate-agent extension at `~/.pi/agent/extensions/delegate-agent`
(override with `PI_DELEGATE_AGENT_ROOT`). When `--auto-handoff-plan` is enabled, it
also discovers the auto-handoff extension at `~/Secret-Projects/pi-auto-handoff`
(override with `PI_AUTO_HANDOFF_ROOT`, a relay-internal discovery override, not a
workflow-facing parameter).

## Dispatching

```bash
node "<skill-dir>/scripts/relay.mjs" --brief brief.txt --cd /path/to/repo
```

`<skill-dir>` is the installed folder containing this skill's `SKILL.md`.

| Flag | Effect |
| --- | --- |
| `--brief <file>` | Brief path. Omit it to read the brief from stdin. |
| `--cd <dir>` | Working root and child process cwd (default: relay cwd). |
| `--read-only` | Tool allowlist `read,grep,find,ls,delegate_agent` — the default for fresh runs. |
| `--write` | Tool allowlist `read,grep,find,ls,bash,edit,write,delegate_agent`. |
| `--model <id>` | Explicit `provider/model` id (e.g. `zai-coding-cn/glm-5.3`); a `:thinking` suffix is also accepted. Default: Pi's own configured default. |
| `--thinking <level>` | `off\|minimal\|low\|medium\|high\|xhigh\|max` (default `high`). |
| `--session <id>` | Resume one existing exact Pi session via Pi `--session`; fail if missing or mismatched. Send only the delta brief. |
| `--timeout <dur>` | Optional relay watchdog (default: off; h/m/s strings). Normal orchestration omits it; a deliberately long guard (`4h`) beats a task estimate. |
| `--out-dir <dir>` | Artifact directory (default: a fresh directory under the system temp dir). |
| `--auto-handoff-plan <file>` | Enable top-level Auto Handoff: one additional `-e` plus child-process `PI_AUTO_HANDOFF_PLAN_FILE` (the exact validated plan path) and `PI_AUTO_HANDOFF_HANDOFF_DIR` (`<actual out dir>/auto-handoff`). `<file>` must be an absolute readable non-empty regular file. Absence disables atomically. |
| `-h`, `--help` | Print the relay's header help. |

A fresh run defaults to read-only. Writing requires an explicit `--write`. The relay
always passes `--no-extensions` plus an explicit `-e <delegate-agent-root>` so extension
loading is deterministic: the `delegate_agent` tool exists and nothing implicit loads.
When `--auto-handoff-plan` is present, one additional `-e` loads the auto-handoff
extension; delegated children keep `--no-extensions` and never receive it. Global
Skills discovery stays enabled; the relay never copies or mirrors Skills.

There is no `call_allowlist` in this relay: a `--read-only` parent can still ask
`delegate_agent` for a write-access child. Tool-gating applies only to the top-level
Pi process. Therefore every commissioned review brief must forbid the parent and all
delegated children from writing or invoking write-access children. Treat read-only as
an instruction boundary, not an OS sandbox.

The brief rides a temp file referenced at Pi's final argv position (`-- @prompt-file`).
The file remains available while Pi runs and is removed after the child exits; the brief
text itself is not visible in the host process list and has no argv-size cap.

## Artifacts and result fields

Artifacts live outside the repo by default so they do not appear in `touchedFiles`:

- `brief.txt` — the exact brief.
- `events.jsonl` — Pi's raw NDJSON event stream.
- `final.txt` — the last assistant message text; absent if none was emitted.
- `stderr.txt` — complete stderr.
- `result.json` — the stable `delegate-relay.result.v1` contract.
- `auto-handoff/` — when `--auto-handoff-plan` is enabled, the plugin writes
  `handoff-NNN-<timestamp>.md` and `.auto-handoff-events.jsonl` under
  `<out-dir>/auto-handoff/`, outside the product repository. The relay does not
  pre-create this directory.

`result.json` fields:

- `schema`, `tool` (`"pi"`), `status` (`completed` | `failed` | `timeout` | `aborted` |
  `unavailable`; a missing binary reports `unavailable` with `sourceStatus` keeping the
  tool-specific `pi_unavailable`), `exitCode`, `signal`.
- `piVersion`, `sessionId` (from the stream's `session` event), `cwd`, `mode`
  (`read-only` | `write`), `requestedModel`, `resolvedModel` (last assistant
  `provider/model` from the stream — only what is honestly observable; `null` when
  the run never produced an assistant message), `resolvedProvider`, `thinking`, `resumed`.
- `startedAt`, `finishedAt`, `finalMessage`, `usage` (last assistant usage), `stopReason`,
  `autoRetryCount` (Pi auto-retries are normal; they are counted, not failed).
- `briefPath`, `finalPath` (null when absent), `eventsPath`, `stderrPath`.
- `touchedFiles` — `git status --porcelain` lines for the working tree under `--cd`
  only, taken at terminal time. It is a snapshot, not an attribution of Pi's edits:
  pre-existing dirt shows up too. `null` means git could not report; `[]` means clean.
- `stderrTail` — last 20 non-empty stderr lines on any non-completed outcome.
- `error` — the concrete reason a run did not complete.
- `autoHandoff` — `{ enabled, planFile, handoffDir, extensionRoot }` on every
  terminal path. Enabled: `{ enabled: true, planFile: "<abs>",
  handoffDir: "<abs>/auto-handoff", extensionRoot: "<root or null>" }`.
  Disabled: `{ enabled: false, planFile: null, handoffDir: null,
  extensionRoot: null }`.

Completion (`completed`) requires ALL of: child process exit, exit code 0, Pi
`agent_settled` observed in the event stream, and a valid session id. A zero exit
without `agent_settled` or a session id is `failed` with an explicit `error`.

## Waiting for completion

The helper blocks. Use the orchestrator's background-command facility, or background
it in a shell and poll for `result.json`. The run is done only when the process has
exited and the file carries a `status`.

Managed `development-stage.v2` Review Workers do not launch this helper directly.
`devflow_start_or_inspect_relay` owns the process and blocks in slices clamped just
below the agent sequential-tool ceiling (420s by default); an `attach` response means heartbeat once and repeat that bounded wait,
never busy-poll the artifact files in model turns.

A pre-run usage error exits 2 and writes no result. A missing `pi` binary exits 127
and writes `status: "unavailable"`.

## When a run misbehaves

- **`status: "unavailable"` (exit 127):** install Pi, configure auth, re-dispatch.
- **`status: "failed"` with `pi exited with code N`:** read `stderrTail`, `stderrPath`,
  and the tail of `events.jsonl`. An unknown `--model` id fails here.
- **`status: "failed"` with `agent_settled was never observed`:** Pi exited 0 but the
  stream ended early — treat the terminal state as unproven; inspect the tree.
- **`status: "timeout"`:** the `--timeout` watchdog killed the run. Increase it or
  split the brief. SIGTERM first, SIGKILL after 10 s.
- **`status: "aborted"`:** the relay itself was killed and forwarded the kill to Pi.
  The result is written before the relay exits; inspect the working tree before
  re-dispatching.
- **Empty `finalMessage`:** inspect `touchedFiles` and the diff. Add a closing-report
  requirement to the next brief.
- **`autoRetryCount > 0` on a completed run:** normal GLM endpoint flakiness absorbed
  by Pi's retry; not an incident.

## Session continuity

`--session <id>` maps to Pi's `--session`, not `--session-id`: it resumes an
existing Session and fails when no match exists. The relay also requires the Session
ID observed in Pi's event stream to equal the requested full ID. The lifecycle mapping is:

- discussion: fresh `--read-only`; preserve the returned `sessionId`;
- every follow-up discussion turn: `--session <id> --read-only`;
- write-plan: fresh `--write`; never reuse the discussion session;
- execute-plan: fresh `--write` plus `--auto-handoff-plan <absolute accepted plan path>`; preserve the new execution session id;
- rework: `--session <execution-id> --write` plus `--auto-handoff-plan` (execute-plan rework only; write-plan rework does not re-pass the option).

Card review relays are always fresh `--read-only` Sessions. They never resume a
planning/execution Session, never pass `--auto-handoff-plan`, and are validated
directly by the native review run rather than the write-mode external guard.

When Auto Handoff is enabled, handoff artifacts land under `<out-dir>/auto-handoff/`
(`handoff-NNN-*.md`, `.auto-handoff-events.jsonl`), outside the product repository.

Never replace a resumable session with a fresh agent. If a session file was deleted,
report continuity loss under the orchestrator's policy.

## What the relay runs

The argv is equivalent to:

```bash
pi --mode json -p --no-extensions -e ~/.pi/agent/extensions/delegate-agent \
  [-e ~/Secret-Projects/pi-auto-handoff]              # only with --auto-handoff-plan
  --tools read,grep,find,ls,delegate_agent            # or the write set
  [--model provider/model] --thinking high \
  [--session <existing-id>] \
  -- @<temp-prompt-file>
```

When `--auto-handoff-plan` is set, the child is spawned with a fresh env copy that
sets `PI_AUTO_HANDOFF_PLAN_FILE` (the exact validated plan path) and
`PI_AUTO_HANDOFF_HANDOFF_DIR` (`<actual out dir>/auto-handoff`). Those two variables
are child-process scoped only; the relay never assigns them on its own environment.
Delegated children keep `--no-extensions` and never receive the auto-handoff `-e`.

## The commit boundary

The relay never commits or performs remote/release actions. Pi edits the working
tree; the orchestrator reviews, re-runs the gates, and commits under its own
authority. See `development-orchestrator`.
