# Relay Monitoring

The main Skill owns delegation and completion routing. This reference owns observation of a card's top-level direct implementation, `write-plan`, or `execute-plan` Relays under the ONE-monitor-per-card model: the fixed card monitor, `development-monitor.v2`, terminal-state wakeup, handoff verification, and teardown.

Internal `review-plan`, `review-patch`, and `review-plan-conformance` rounds remain inside their coding-agent parent. Never create a separate Relay, monitor state, Cron, or card for those rounds.

## One card, one monitor

A Kanban card owns exactly one recurring 10-minute Cron job, one fixed generated wrapper, and one active card-level monitor state file. Direct implementation, `write-plan`, `execute-plan`, retries, abnormal recovery, and same-scope rework all share that single monitor; stage transitions only rewrite the state file. Never create a second Cron, wrapper, or state file for the same card, and never chain a "predecessor Cron" for a successor to clean up.

```text
card accepted
  → new_monitor_state → tasks/<card-id>/monitor-state.json   (monitor.state: idle)
  → make_card_wrapper → generated-development-monitors/card-<card_id>.py
  → create the card's single 10-minute Cron (once)
  → rearm_attempt(...) per Relay start                         (monitor.state: relay_running)

stage change / retry / rework
  → rearm_attempt ONLY; the Cron, wrapper, and state path never change
  → generation += 1 and a new attempt.out_dir; operation is descriptive only

terminal takeover
  → fresh independent Watson becomes the active orchestrator
  → verify process, result contract, and declared artifacts
  → continue the already-authorized lifecycle:
       write-plan complete → rearm and start fresh execute-plan
       execute/direct complete + UI → perform UI acceptance
       execute/direct complete + non-UI → close, land, and complete
  → persist the transition; rearm the same monitor when the next Relay starts
  → finish normally so scheduler delivery commits

final closure
  → close_monitor after durable delivery (monitor.state: closed)
  → a later non-source execution removes the single Cron and wrapper
```

## Card monitor contract

One Cron per card, never a shared watcher or cross-profile handoff.

```text
name:     dev-card-<card-id>
schedule: */10 * * * *
script:   generated-development-monitors/card-<card_id>.py
prompt:   self-contained takeover/authority instructions
deliver:  origin task chat or exact platform:chat_id
workdir:  exact repository
skills:   development-orchestrator
attach_to_session: true
profile:  default
```

Create the state, wrapper, and Cron in that order, then atomically record `monitor.cron_job_id` and `monitor.wrapper_path` in the state file.

### Monitor state

Canonical path for Secret-Projects work: `~/Secret-Projects/development-artifacts/<project>/tasks/<card-id>/monitor-state.json`. The Cron binds the resolved absolute realpath; a project `.dev` may expose the same location by symlink. Helpers live in `~/.hermes/scripts/development_relay_gate.py`: `new_monitor_state`, `write_monitor_state_atomic`, `update_monitor_state`, `rearm_attempt`, `idle_monitor`, `close_monitor`, `acknowledge_event`. Use the atomic helpers; never hand-edit the file. It is indented JSON under the `development-monitor.v2` contract documented at `~/.hermes/schemas/development-monitor.schema.yaml`.

The file holds only runtime identity and routing: card/project/repo/origin, a minimal `product.goal`, fixed Cron/wrapper/state paths, `monitor.state`, descriptive `operation`, monotonic `generation`, the current attempt, and at most one pending actionable event. Kanban is the source of truth for acceptance, UI classification, and card closure. Do not copy those into the monitor file.

Relay attempts stay immutable beside the state: `tasks/<card-id>/attempts/<generation>-<operation>/`, each retaining its own result/events/final/brief. Classification reads `attempt.out_dir` from the current attempt block only and never scans older attempt directories, so an old generation's terminal files, fingerprints, or ACKs can neither wake nor suppress the active generation. The coding-agent `session_id` is a field of the current attempt, keeping session resume separate from monitor state.

### Rearm

`rearm_attempt(state_path, attempt=..., operation=...)` increments `monitor.generation` by 1, rebuilds the attempt block from a whitelist, and clears `pending_event` in one atomic write. A new Relay must bind a NEW `out_dir`. `operation` is descriptive (`direct`, `write-plan`, `execute-plan`, `rework`, …); it does not drive a transition algebra. The first arming of an idle card moves generation 0 → 1, so the first Relay owns `attempts/1-<operation>/`.

Healthy false-positive recovery does not rearm. ACK the spurious event; if the process remains healthy, later ticks stay silent `RUNNING`.

### Wrapper

Generate through:

```text
/usr/bin/python3 ~/.hermes/scripts/development_relay_gate.py --state <abs-path> --make-wrapper
```

The wrapper name is `card-<card_id>.py`; it binds the exact resolved state path and passes compilation verification. Re-running is idempotent; retries and stage changes never create a second wrapper.

### Tick silence

`idle` and `closed` are zero-agent: the tick prints `{"wakeAgent":false}` and does nothing else. Healthy `RUNNING` is also silent: `wakeAgent:false` and no group/chat progress message. Only actionable terminal, stalled, or awaiting-input states notify or wake.

### Woken-Watson requirements

The order is mandatory:

1. Recognize that this is a fresh independent takeover session, not a notification-only helper or a resumption of the origin conversation.
2. Read `state_path`, `event_id`, and `relay_state` from Script Output; load the exact board/card and verify `monitor.cron_job_id` identifies the source Cron.
3. Reconstruct and independently verify the current stage from the live repository, process state, `result.json`, events, and declared artifacts of the CURRENT attempt directory. Never trust the script summary or parent self-report alone.
4. **Before rearming the next Relay, entering UI acceptance, landing, committing, or changing card state, send the user one concise progress update:** current stage, observed outcome, next action, and whether input is needed.
5. Persist takeover/closure state. Acknowledge the exact event id; an ACK from another generation is refused and never silences the active one.
6. Continue the already-authorized lifecycle. On successful `write-plan`, immediately rearm and start fresh `execute-plan` unless the card is plan-only or needs a decision. On successful direct implementation or `execute-plan`, continue into UI acceptance or non-UI closure, landing, and card completion. Between top-level Relays during a card's life, `idle_monitor` parks the monitor so ticks stay zero-agent without touching the Cron.
7. Do not hand ordinary continuation back to the dormant origin session. Stop only for a genuine product decision, authority boundary, continuity loss, abnormal terminal state, or completed task.

Additional invariants:

- Exactly one monitor state per card may be in `relay_running`; there is no predecessor job, because the card's single Cron is never replaced for routine transitions.
- If the source Cron ID is missing, does not match the running job, or cannot be read back, report the handoff inconsistency and do not rearm until it is reconciled.
- Never remove, pause, or materially edit the source Cron from inside its own woken execution. Historical evidence shows this invalidates the active fire claim and yields `Fire claim ownership lost; stale result was discarded`, even when the agent completed its work.
- Abnormal terminal states never advance the card. Report evidence and return product/authority decisions to the user.
- Do not create a replacement coding-agent session without first reporting continuity loss.
- Persist every transition in the card/state before starting the next operation.
- Do not commit, push, open a PR, release, deploy, publish, change versions, or authorize external effects outside the standing boundary.

### Creation verification

Read the created job back and confirm: schedule exactly `*/10 * * * *`, exact wrapper, exact destination, exact workdir, `attach_to_session: true`, and default profile. If creation fails, do not exit into waiting; continue observing from the current session and report takeover failure.

## Terminal-state semantics

`COMPLETED` requires process exit, readable `delegate-relay.result.v1`, `status: completed`, and `exitCode: 0`. A completed-looking result with a live process remains `RUNNING`. New Pi transport runs publish and use the same result contract, including explicit failed/timeout/aborted states. Historical Pi JSONL-only runs remain readable through a compatibility fallback that requires process exit plus `agent_settled` when no `result.json` exists.

Distinct actionable states include `FAILED`, `ABORTED`, `EXITED_WITHOUT_RESULT`, `MALFORMED_RESULT`, `STALLED`, `TIMEOUT`, and `AWAITING_INPUT`. `IDLE` covers `monitor.state` in `{idle, closed}` and is always zero-agent. `BAD_STATE` marks an unreadable or contract-violating state file and stays zero-agent. A missing declared plan, execution state, review artifact, or deliverable makes a completed-looking run an incomplete handoff.

## False-positive terminal states

ACK records `acknowledged_at` on the pending event and silences the gate for that event. If an event was a false positive while the process remains healthy, ACK it and leave the generation unchanged. The ACKed fingerprint must not re-fire; a genuinely new event gets a fresh, generation-fenced fingerprint.

For long internal subagent work, inspect process activity and the coding tool's durable event/database activity before declaring a stall. Do not kill a healthy run because an expected duration elapsed.

## Teardown

The woken execution must not tear down its own source job. It should record closure in the state/card and finish normally while the Cron still exists, allowing the scheduler to persist the execution and deliver its final result.

After final card closure and durable delivery, `close_monitor` sets `monitor.state: closed`; later ticks are zero-agent. A different owner may then remove the card's single Cron (`hermes cron remove <job-id>`) and its wrapper. If rework or incomplete-handoff repair starts another Relay later, rearm the same monitor: the state file gains a fresh generation and event fence; never reuse a closed event.

## Historical evidence

Archived `delegations/*/resume.yaml` files are read-only history under `development-resume.v1`. Inspect them with `--resume <path> --check`. New wrappers use `--state <path> --make-wrapper`. Nothing rewrites, migrates, or auto-detects historical resume files.

## Interruption recovery

If a wait is interrupted, verify live process state and `result.json` before assuming the Relay still runs. Treat aborted status, exit code 143, or missing process state as a possibly killed Relay and recover from the last durable artifact and exact session when possible.

## In-session fallback cadence

Only when monitor creation failed or the task must be watched in-session: inspect approximately every three minutes for trivial runs and every 15–30 minutes for complex runs, combining process state, `result.json`, event activity, and top-level workflow artifacts.
