---
name: hermes-kanban-workflows
description: "Use when building or verifying Hermes Kanban workflows."
version: 2.1.0
tags: [kanban, multi-agent, dispatcher, relay, external-guard, workflow, verification]
---

# Hermes Kanban Workflows

Implement durable board, Card, Dispatcher, dependency, external-guard, reconciliation, and handoff mechanics for the one-owner development workflow. Development policy is owned by the calling `development-orchestrator`; this Skill implements the requested Kanban transition and must not redefine the route or acceptance policy.

## One-owner model

Exactly two roles ever drive a development Card:

- **Origin default-profile session** — the interactive session with Kenan. Owns intent convergence, accepted amendment comments, and unblocking; never owns execution.
- **Execution Worker** — the ONE Dispatcher-spawned worker that owns the Card from claim to completion: every Relay attempt, UI acceptance, landing, and the terminal `kanban_complete`/`kanban_block`.

No scheduled job ever advances, retries, blocks, unblocks, commits, or completes a Card. No scheduled job exists in this workflow — the global status Digest was removed 2026-09-07 and the Cron job list is empty.

## Ownership split

Hermes Kanban natively owns all of:

- statuses `triage/todo/ready/running/blocked/done`;
- the current run and claim;
- worker PID, heartbeat, stale/crash reclaim, retry/circuit-breaker;
- dependencies and parent handoffs;
- comments and user decisions;
- completion metadata and downloadable artifacts;
- terminal notifications.

The external execution guard owns ONLY Relay identity/session/result plus Git baseline/commit evidence. It must not copy Card status, run history, phase, heartbeat, retries, artifact arrays, or notification state.

## When to use

Load before creating, finalizing, routing, transitioning, reconciling, or completing a development Card, and before operating its external guard state. Also load for board provisioning, Dispatcher behavior, dependencies, task-scoped tools, handoff integrity, and Kanban verification.

## Board and Card mechanics

- Each active development project under `~/Secret-Projects/` uses a dedicated board whose slug is the kebab-case directory basename and whose default workdir is the project root; a repository without development work needs no board. Hermes self-work and projects outside that tree use `default`.
- Cards work directly in the trusted repository directory on main under Kenan's convention; do not use scratch/worktree unless the caller explicitly chooses another supported workspace contract.
- One Card represents one independently closable task. Internal Planning, Execution, Relay attempts, retries, artifacts, and same-scope fixes are not separate Cards.
- Use native parent links. Parent-blocked children remain `todo` and promote automatically after all parents complete.
- Use exact board slugs and explicit board arguments when no task-scoped binding exists. Read back every created or mutated target before claiming success.

For development Cards, the caller supplies a `development-task.v1` body and policy fields. Create the Card with exactly:

- `board=<exact project board>` — never an implicit profile default;
- `assignee=default` — the literal development-contract assignee;
- `skills=[development-orchestrator]` — the task-pinned policy Skill;
- `workspace_kind=dir`, `workspace_path=<exact repository root>` — the trusted repository itself.

Converged tasks are created directly as dispatchable Cards. `kanban_finalize_intent` remains available only for existing triage/backlog Cards; it validates the complete replacement body and calls the native triage specification path, and it exits the default path. Do not repair missing product policy in this mechanics layer.

## Dispatcher semantics

- Dispatcher claims require `status=ready` and a non-empty assignee. The development contract uses literal `assignee=default`.
- Card `model`/`provider` configure the spawned Hermes worker, not the external Coding Agent.
- The worker receives `HERMES_KANBAN_DB`, `HERMES_KANBAN_BOARD`, `HERMES_KANBAN_TASK`, and the Card's workdir/skills.
- Dispatcher workers must begin with `kanban_show()` and end only through `kanban_complete` or a typed `kanban_block`.
- Interactive orchestrators need the `kanban` toolset; task-scoped workers receive focused lifecycle tools automatically. Orchestrator-only tools remain hidden from delegated children.
- There is no per-board concurrency knob. `kanban.max_in_progress_per_profile` in the global `config.yaml` caps concurrent running tasks per profile across ALL boards (the host-wide `kanban.max_in_progress` memory guard is separate). It is set to 1 in Kenan's config, serializing Execution Workers across boards; read it back before dispatching direct-main work.
- Emit heartbeats during long operations so stale reclaim does not silently recycle active work.
- Before supervising a long background Relay, verify the Worker's effective wait ceiling. `process_manage(wait)` is clamped by `TERMINAL_TIMEOUT`; for a Card with `max_runtime_seconds`, Dispatcher raises the worker-scoped ceiling to `max_runtime_seconds - 30` seconds when needed.
- For Relays expected to run longer than a few minutes, prefer 30–50 minute `process_manage(wait)` slices when the ceiling permits, then heartbeat before the next slice. Do not wake the model every few minutes, and do not reread `result.json` or the event stream while the process is still live; consume terminal artifacts only after process exit or during crash/reclaim reconciliation.

## Status transitions (native flow)

Use native lifecycle tools, not raw SQL. This workflow uses only:

- draft specification: `triage → todo`, then `recompute_ready()` promotes to `ready` if parent gates are closed;
- Dispatcher claim: `ready → running`;
- completion: `running → done` via `kanban_complete` after landing;
- blocker: `running → blocked` with the typed `dependency | needs_input | capability | transient` kind that matches reality; unblock returns the Card to dispatch;
- parking: `block` fires ONLY from `running`/`ready`; to park a `todo` Card non-dispatchably use `schedule` (`todo/ready/running/blocked → scheduled`, not claimable; `unblock` re-gates it).

There is no review lane in this workflow; UI acceptance runs inside the owning Worker while the Card stays `running`. Keep `kanban.review_dispatch: false` — this is a configuration fact; acceptance policy belongs to `development-orchestrator`.

## External execution guard

Each development Card owns at most one canonical guard state:

```text
~/Secret-Projects/development-artifacts/<board>/tasks/<card-id>/external-execution.json
```

schema `development-external-execution.v1`, written only through `development_external_guard.py`. The guard is fail-closed: it reserves before process creation, never retries automatically, records the exact terminal session ID, verifies the current native run before side effects, and detects the Card-trailer landing commit. Allowed outcomes are `spawned | attach | terminal | uncertain` (`inspect` also returns `none` when no attempt exists). `uncertain` blocks the Card.

Never hand-edit the state file, bypass the guard CLI, or infer process safety from prose, PID absence, or elapsed time. Load `references/execution-recovery.md` before initializing, starting, inspecting, resuming, or landing a Card's external execution.

## Scheduled jobs

None. The global status Digest Cron (`development-status-digest`) was removed on 2026-09-07; the Cron job list is empty and no per-Card Cron, monitor, or wrapper exists. Observe active Cards through native Kanban notifications, direct board queries, or the Worker's own heartbeats.

## Reconciliation

Do not trust a column or self-report alone. Check cheapest-first:

1. exact board/Card and comments/events;
2. guard state: attempt, process identity, result path, session ID, commit;
3. live process state and adapter `result.json`;
4. the accepted Plan path when the operation is planning;
5. Git status/history against the recorded baseline;
6. acceptance evidence when the caller requires it;
7. session history only if ambiguity remains.

Never mutate guard state, board, Git, or Cron during a progress-only read. Comment compact verified evidence on the Card when reconciliation changes lifecycle understanding.

## Handoff integrity

A completed-looking Relay is incomplete if the process is live or the terminal `delegate-relay.result.v1` is malformed/missing. Validate terminal truth and load-bearing paths (state, out directory, result file, accepted Plan path) without duplicating engineering behavior tests; final deliverables ride native Kanban attachments. See `references/handoff-integrity.md`.

## Tool and API pitfalls

1. Prefer `kanban_*` tools; never patch Kanban SQLite directly.
2. Board resolution precedence is task-scoped DB/board binding, explicit board, active-board symlink, then profile default. Use profile-safe Hermes paths.
3. A bare `task_id` in an unclaimed interactive session needs `board="default"` or the exact slug when the target is not the active board.
4. `edit` does not replace lifecycle transitions; use specification, completion, block, or unblock surfaces.
5. Repeated same-cause block/unblock can trigger triage. Use a precise typed blocker and do not loop.
6. `workflow_template_id` and `current_step_key` are metadata, not Dispatcher routing.
7. Native top-level `artifacts` are attachment paths; keep structured result objects under a nested metadata key to avoid collisions.
8. Manage Cron jobs only through the supported Cron API/tool surface. Never remove or materially edit a job from inside its own active fire.
9. In the Kanban CLI, `--board` is a parent-level flag: place it BEFORE the subcommand (`hermes kanban --board <slug> block ...`); positioned after the subcommand it is parsed as a task argument and the call fails.

## Verification

Before reporting success, read back and confirm:

- exact board/workdir/task and parent gating;
- exact body/assignee/status/event after intent finalization;
- the guard state validates: expected schema, single attempt, terminal session ID, recorded commit;
- `check-run` passes immediately before any Relay start, UI mutation, or Git commit;
- truthful `delegate-relay.result.v1` terminal truth and load-bearing paths;
- the Cron job list matches the current scheduled-jobs decision in §Scheduled jobs (empty as of 2026-09-07) with no per-Card Crons, monitors, or wrappers — check the live list, do not assert it;
- requested status transition and no unrelated board mutation.

Detailed mechanics live in `references/kanban-mechanics.md`, `references/execution-recovery.md`, and `references/handoff-integrity.md`.
