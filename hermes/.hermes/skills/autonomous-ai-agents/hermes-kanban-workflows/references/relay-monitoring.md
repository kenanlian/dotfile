# Relay Monitoring

This mechanics reference implements the one-monitor-per-Card model requested by `development-orchestrator`. It does not select the development route, Coding Agent, acceptance policy, or landing authority.

## Canonical monitor contract

Each Card owns exactly one recurring Cron, one fixed generated wrapper, and one `development-monitor.v2` state across direct work, Planning, Execution, retries, recovery, and same-scope rework.

```text
name:      t_<card-id> development-monitor
schedule:  every 10m
script:    generated-development-monitors/card-<card_id>.py
workdir:   exact trusted repository
skills:    [development-orchestrator]
profile:   default
```

Delivery and `attach_to_session` follow the Card's originating conversation contract. Create state, wrapper, then Cron; atomically record the resulting Cron ID and wrapper path; read the job back and verify every field. A bare `10m` is not the accepted recurring schedule.

## State and attempts

Canonical Secret-Projects path:

```text
~/Secret-Projects/development-artifacts/<project>/tasks/<card-id>/monitor-state.json
```

A project `.dev` may expose the same location by symlink. Helpers live at `~/.hermes/scripts/development_relay_gate.py` and the schema at `~/.hermes/schemas/development-monitor.schema.yaml`.

Use only atomic helpers: `new_monitor_state`, `write_monitor_state_atomic`, `update_monitor_state`, `rearm_attempt`, `idle_monitor`, `close_monitor`, and `acknowledge_event`. Never hand-edit the file.

Canonical monitor states are exactly:

```text
idle | relay_running | closed
```

State contains runtime identity/routing only: Card/project/repo/origin, minimal goal, fixed Cron/wrapper/state paths, state, descriptive operation, monotonic generation, current attempt, and at most one pending event. Kanban owns the development contract and status.

Attempt directories are immutable:

```text
tasks/<card-id>/attempts/<generation>-<operation>/
```

`rearm_attempt` increments generation, rebuilds the attempt block from a whitelist, clears the pending event, and requires a new `attempt.out_dir`. `operation` is descriptive, not a transition policy. Classification reads only the current attempt.

## Wrapper

Generate idempotently with:

```text
/usr/bin/python3 ~/.hermes/scripts/development_relay_gate.py --state <abs-path> --make-wrapper
```

The stable wrapper is `card-<card_id>.py`. Retries and stage changes reuse it.

## Tick behavior

`idle` and `closed` ticks are zero-agent. Healthy `relay_running` ticks are also silent. Only actionable terminal, stalled, or awaiting-input classifications notify/wake. `BAD_STATE` remains zero-agent; an unexplained long silence requires state validation rather than an assumption of success.

## Monitor-woken takeover

A woken default-profile session must:

1. Read Script Output, exact state, event ID, board/Card, and source Cron ID.
2. Verify that the source Cron matches the state and current Card.
3. Reconstruct current-generation truth from process identity, adapter `result.json`, events, Git, and declared artifacts. Do not trust the gate summary or parent self-report alone.
4. Update the user concisely before any new side effect: stage, observed outcome, next authorized action, and whether input is needed.
5. Persist the transition and acknowledge the exact generation-fenced event.
6. Continue only the lifecycle already authorized by the caller. If another Relay is needed, rearm the same state with a new generation/output directory.
7. Stop for a genuine decision, authority boundary, continuity loss, abnormal terminal state, or completed task.

Never remove, pause, or materially edit the source Cron from inside its own active execution; doing so can invalidate fire ownership and discard the result.

## Terminal semantics

`COMPLETED` requires process exit, readable `delegate-relay.result.v1`, `status=completed`, and `exitCode=0`. A completed-looking result while the process lives remains `RUNNING`.

Actionable abnormal states include `FAILED`, `ABORTED`, `EXITED_WITHOUT_RESULT`, `MALFORMED_RESULT`, `STALLED`, `TIMEOUT`, and `AWAITING_INPUT`. Missing declared artifacts make a completed-looking run an incomplete handoff.

For a false positive while the process remains healthy, acknowledge the event and keep the generation unchanged. Inspect process and durable event activity before declaring long internal work stalled. Do not kill a healthy run because an estimated duration elapsed.

## Retry and teardown

A transient Relay failure may be retried once for the same cause when the calling policy permits it; rearm the same monitor. A repeated same-cause failure or any resolution that changes scope/decisions becomes a typed Card blocker.

After durable final delivery, `close_monitor` writes `closed`. A later non-source owner removes the Cron through the supported Cron tool/API and deletes the wrapper; retain state and attempts as evidence. If same-scope rework later reopens execution, rearm with a fresh generation and event fence.

## Interruption recovery

After an interrupted wait, verify process identity and `result.json` before declaring status. Recover from the current immutable attempt and exact transport Session when possible. If monitor creation itself failed, bounded in-session observation is the fallback; do not create a competing monitor.
