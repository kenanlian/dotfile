# External Execution Guard

This is the minimal recovery reference for write-mode planning/implementation/rework Relays in the development workflow MVP. The guard (`hermes/.hermes/scripts/development_external_guard.py`) is deliberately small and fail-closed: it prevents duplicate write-mode Coding Agent Relays, records their session/recovery facts, and detects an already-created landing commit. Fresh read-only Card-review Relays do not use this state; their process/result truth is recorded by the native review run. The guard does not recover crashes automatically and implements no workflow phase machine. Hermes Kanban owns everything else (Card status, runs, claims, review rounds, heartbeats, stale reclaim, retries, dependencies, handoff, notifications).

## CLI

```text
development_external_guard.py [--artifacts-root DIR] --home HERMES_HOME --board BOARD --card CARD_ID COMMAND
  init --repo /abs/path
  start-or-inspect --operation planning|execution|rework --out-dir DIR --result-path FILE --cmd-json JSON [--cwd DIR] [--plan-artifact FILE] [--new-attempt]
  inspect
  record-terminal --result-path FILE [--session-id ID]
  check-run
  record-commit --commit SHA
```

Outcomes: `spawned | attach | terminal | uncertain` (`inspect` also returns `none` when no attempt exists).

## Canonical state

```text
~/Secret-Projects/development-artifacts/<board>/tasks/<card-id>/external-execution.json
```

Schema `development-external-execution.v1` (or `--artifacts-root DIR` to relocate). Minimal shape:

```json
{
  "schema": "development-external-execution.v1",
  "card_id": "t_xxx",
  "repo": "/absolute/repo",
  "baseline_head": "<git commit>",
  "baseline_porcelain": ["<git status --porcelain line>"],
  "attempt": {
    "number": 1,
    "operation": "planning | execution | rework",
    "state": "reserved | running | terminal | uncertain",
    "pid": null,
    "process_start": null,
    "out_dir": "/absolute/path",
    "result_path": "/absolute/path/result.json",
    "session_id": null
  },
  "commit": null,
  "updated_at": "<ISO-8601>"
}
```

Never hand-edit this file. Do not add Card status, run history, phase, heartbeat, retries, artifact arrays, revision, owner object, plan object, or landing object — those belong to Hermes Kanban or do not exist in the MVP.

## Commands

- **`init --repo /abs/path`** — record Card/repo/Git baseline (HEAD + `git status --porcelain`) once, before the Coding Agent writes.
- **`start-or-inspect`** — atomically reserve/start once, or report the existing state. Reserves before process creation. `--operation` is `planning`, `execution`, or `rework`. `--plan-artifact`, when supplied, must be an absolute readable non-empty file. Initial `write-plan` omits it because the Plan does not exist yet; `execute-plan` supplies the accepted Plan path; direct execution omits it. Validate only load-bearing paths: state path, out directory, result file, and any supplied Plan artifact.
- **`inspect`** — classify the existing process/result without mutation. Returns `none` when no attempt exists.
- **`record-terminal`** — accept a terminal `delegate-relay.result.v1` and record the exact session ID.
- **`check-run`** — verify the current `HERMES_KANBAN_TASK`/`RUN_ID` still owns the native Card; rejects a stale/reclaimed Worker.
- **`record-commit`** — record a commit that contains the exact `Kanban-Task: <card-id>` trailer.

Classification rules:

- A matching live PID/start identity returns `attach`.
- A dead process with a valid `delegate-relay.result.v1` returns `terminal` and records the exact session ID.
- Reserved-without-proof, PID mismatch, dead-without-result, or a malformed result returns `uncertain`; the guard never retries automatically.
- A new attempt is allowed only after the previous attempt is recorded terminal — via a lifecycle-stage change (`planning` → `execution` → `rework`) or an explicit `--new-attempt`; plain same-operation re-entry consumes the recorded terminal result instead of rerunning.
- Every attempt uses a fresh out dir and result path, so one attempt's `result.json` can never be mis-attributed to the next.

## Safety rules

1. Reserve before starting a Relay.
2. Never start a second Relay while an earlier attempt may exist.
3. Resume only an exact recorded Coding Agent Session after a known terminal attempt.
4. Check the current native Kanban run (`check-run`) immediately before a write-mode Relay start, UI mutation, and Git commit.
5. Detect an already-created commit using the Card-specific Git trailer.
6. Any ambiguous state blocks the Card; the MVP never guesses that a new spawn is safe.

`uncertain` handling: preserve evidence, block the Card with a precise typed blocker, and let the human decide. Exact-session continuation is a Worker policy decision using the terminal result's `session_id`; the guard does not implement a workflow phase machine.

## Landing rule

Before commit:

1. `check-run` must pass.
2. Compare current Git status with the recorded baseline.
3. Stage only paths listed in the Coding Agent handoff.
4. If a staged path was dirty at baseline, block instead of attempting attribution.
5. Search Git history for the exact trailer `Kanban-Task: <card-id>`.
6. If a matching commit already exists at/after `baseline_head`, record it with `record-commit` and complete without a second commit.
7. Otherwise create one commit with that trailer, read back its hash and trailer, then `record-commit`.

## Relay-state vocabulary

The global status Digest was removed on 2026-09-07; no Cron renders Relay state. The vocabulary `none/reserved/live/terminal/uncertain` remains the guard-state vocabulary seen in `inspect` output and guard state files. Missing or malformed guard state never hides the Card's native status.
