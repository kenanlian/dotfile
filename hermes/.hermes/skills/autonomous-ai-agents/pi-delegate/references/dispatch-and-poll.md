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
(override with `PI_DELEGATE_AGENT_ROOT`).

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
| `--session <id>` | Resume one exact Pi session via `--session-id` (create-if-missing). Send only the delta brief. |
| `--timeout <dur>` | Optional relay watchdog (default: off; h/m/s strings). Normal orchestration omits it; a deliberately long guard (`4h`) beats a task estimate. |
| `--out-dir <dir>` | Artifact directory (default: a fresh directory under the system temp dir). |
| `-h`, `--help` | Print the relay's header help. |

A fresh run defaults to read-only. Writing requires an explicit `--write`. The relay
always passes `--no-extensions` plus an explicit `-e <delegate-agent-root>` so extension
loading is deterministic: the `delegate_agent` tool exists and nothing implicit loads.
Global Skills discovery stays enabled; the relay never copies or mirrors Skills.

Per the settled user decision there is NO call_allowlist in this relay: a read-only
parent may invoke a write-access child through `delegate_agent`. Tool-gating is the
only access fence, and it applies to the top-level Pi process alone.

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

`result.json` fields:

- `schema`, `tool` (`"pi"`), `status` (`completed` | `failed` | `timeout` | `aborted` |
  `pi_unavailable`), `exitCode`, `signal`.
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

Completion (`completed`) requires ALL of: child process exit, exit code 0, Pi
`agent_settled` observed in the event stream, and a valid session id. A zero exit
without `agent_settled` or a session id is `failed` with an explicit `error`.

## Waiting for completion

The helper blocks. Use the orchestrator's background-command facility, or background
it in a shell and poll for `result.json`. The run is done only when the process has
exited and the file carries a `status`.

A pre-run usage error exits 2 and writes no result. A missing `pi` binary exits 127
and writes `status: "pi_unavailable"`.

## When a run misbehaves

- **`status: "pi_unavailable"` (exit 127):** install Pi, configure auth, re-dispatch.
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

`--session <id>` maps to Pi's `--session-id`: it resumes the exact session when it
exists and creates it when it does not. The lifecycle mapping is:

- discussion: fresh `--read-only`; preserve the returned `sessionId`;
- every follow-up discussion turn: `--session <id> --read-only`;
- write-plan: `--session <discussion-id> --write`;
- execute-plan: fresh `--write`; preserve the new execution session id;
- rework: `--session <execution-id> --write`.

Never replace a resumable session with a fresh agent. If a session file was deleted,
report continuity loss under the orchestrator's policy.

## What the relay runs

The argv is equivalent to:

```bash
pi --mode json -p --no-extensions -e ~/.pi/agent/extensions/delegate-agent \
  --tools read,grep,find,ls,delegate_agent            # or the write set
  [--model provider/model] --thinking high \
  [--session-id <id>] \
  -- @<temp-prompt-file>
```

## The commit boundary

The relay never commits or performs remote/release actions. Pi edits the working
tree; the orchestrator reviews, re-runs the gates, and commits under its own
authority. See `development-orchestrator`.
