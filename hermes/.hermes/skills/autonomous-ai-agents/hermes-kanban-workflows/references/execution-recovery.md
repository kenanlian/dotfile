# External Execution Guard

Use for write-mode planning/implementation/rework Relays on managed development Cards. The guard prevents duplicate writes, records exact Relay/session recovery facts, and tracks Git landing lineage. Kanban owns lifecycle/run/review/retry/heartbeat/stale/notification state. Fresh read-only Review Relays do not use the guard.

## Interpreter and CLI

Run with the Hermes venv Python (`~/.hermes/hermes-agent/venv/bin/python3`, Python 3.11+). System `/usr/bin/python3` 3.9 fails when `check-run` lazily imports current `hermes_cli` because of PEP 604 annotations; other commands may appear to work and hide the mismatch.

```text
development_external_guard.py [--artifacts-root DIR] --home HERMES_HOME --board BOARD --card CARD_ID COMMAND

  init --repo /abs/path
  start-or-inspect --operation planning|execution|rework \
    --out-dir DIR --result-path FILE --cmd-json JSON [--cwd DIR] \
    [--plan-artifact FILE] [--new-attempt]
  inspect
  record-terminal --result-path FILE [--session-id ID]
  check-run
  record-commit --commit SHA
```

The Harness normally owns invocation through `devflow_start_or_inspect_relay`; Workers do not call this CLI directly. Outcomes are `spawned|attach|terminal|uncertain`; inspect also returns `none` before any attempt.

## Canonical v2 state

```text
~/Secret-Projects/development-artifacts/<board>/tasks/<card-id>/external-execution.json
```

```json
{
  "schema": "development-external-execution.v2",
  "card_id": "t_xxx",
  "repo": "/absolute/repo",
  "baseline": {
    "head": "<git commit>",
    "porcelain": ["<git status --porcelain line>"]
  },
  "attempts": [
    {
      "number": 1,
      "operation": "planning | execution | rework",
      "state": "reserved | running | terminal | uncertain",
      "pid": null,
      "process_start": null,
      "out_dir": "/absolute/path",
      "result_path": "/absolute/path/result.json",
      "session_id": null,
      "terminal_status": null
    }
  ],
  "landings": [
    {
      "attempt_number": 1,
      "commit": "<sha>",
      "parent": "<sha>",
      "recorded_at": "<ISO-8601>"
    }
  ],
  "updated_at": "<ISO-8601>"
}
```

Constraints:

- attempt number is monotonic;
- at most one attempt is non-terminal;
- every attempt has a unique output directory/result path;
- only a terminal attempt can produce a landing;
- recording the same commit for the same attempt is idempotent;
- a different rework commit appends a landing instead of overwriting history;
- exact-session rework takes its session from a prior terminal attempt;
- no Card status, review round, UI/manual verdict, Plan acceptance, heartbeat, retry, or notification state is stored.

## v1 migration

A valid `development-external-execution.v1` state migrates only on the first exclusive managed write:

1. lock and validate the existing state;
2. write an atomic `.bak` snapshot before replacement;
3. map `baseline_head`/`baseline_porcelain` into `baseline`;
4. map the single `attempt` into `attempts[0]` without changing identity;
5. map an existing recorded commit into the first landing bound to that terminal attempt;
6. validate the complete v2 result and atomically replace the canonical file.

Read-only inspect may report legacy facts without mutating them. Any lossy/ambiguous migration fails closed as `HARNESS_INCOMPATIBLE`; never reset history.

## Commands and ordering

- `init` captures immutable Card/repository/Git baseline once before Coding Agent writes.
- Before `start-or-inspect`, the Harness validates current run ownership, contract/stage, brief existence, adapter capability, command shape, output paths, and required accepted Plan/Auto Handoff. Invalid preflight must not create an attempt.
- `start-or-inspect` reserves atomically before spawning. Plain re-entry attaches/consumes the current attempt. A new attempt is allowed only after the prior attempt is terminal and policy authorizes lifecycle progression or explicit rework.
- `inspect` classifies without lifecycle mutation.
- `record-terminal` validates terminal `delegate-relay.result.v1`, process exit, exact result path and session, then seals the current attempt.
- `check-run` verifies `HERMES_KANBAN_TASK`, run id, and claim lock still own the native current run.
- `record-commit` verifies an exact Card trailer and appends/idempotently reuses the landing bound to the current terminal attempt.

Classification:

- matching live PID/start identity → `attach`;
- dead process plus valid terminal result → `terminal`;
- reserved without spawn proof, PID mismatch, dead without result, malformed result, or conflicting paths/session → `uncertain`;
- uncertainty is never retried or deleted automatically.

## Auto Handoff

For execute-plan and execute rework, before reservation validate an absolute readable non-empty accepted Plan with matching SHA, Relay support for `--auto-handoff-plan`, extension root, and scoped output directory. At terminal require:

```text
result.autoHandoff.enabled == true
result.autoHandoff.planFile == <exact accepted Plan>
result.autoHandoff.handoffDir == <attempt out-dir>/auto-handoff
result.autoHandoff.extensionRoot == <resolved root>
```

Direct, write-plan, review, and delegated child runs do not load Auto Handoff.

## Landing

After terminal Relay and engineering checks:

1. `check-run` passes.
2. Compare current Git status with immutable baseline and preserve unrelated pre-existing changes.
3. Stage only handoff-owned paths; an ambiguously dirty baseline path blocks attribution.
4. Create or locate one local candidate commit with exact `Kanban-Task: <card-id>` trailer.
5. Record the landing against the terminal attempt.
6. Generate a candidate manifest.
7. Perform required UI/manual acceptance against that exact local commit.
8. Push only after UI PASS and only under applicable authority.
9. Recheck run and candidate before managed handoff.

Rework creates a new terminal attempt and a new landing/candidate. Old landings and evidence remain historical.

## Uncertain recovery

Default action is preserve evidence and typed block. There is no CLI reset and no general force.

A known zero-side-effect pre-spawn false uncertainty may be repaired only by the interactive Origin after Kenan explicitly approves that exact Card/action. Reconfirm all of: no live PID, no result, artifact SHA unchanged, repository clean/at baseline, and no external side effect. Snapshot the state to a separate backup, then restore it from the last committed terminal truth and inspect before unblocking. Prefer restoring a valid prior terminal state over deleting the file: deletion creates a separate state-missing condition that requires reinitialization. A blocked/non-owning Worker never performs this recovery.
