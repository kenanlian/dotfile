---
name: hermes-kanban-workflows
description: "Use when building or verifying Hermes Kanban workflows."
version: 3.0.0
tags: [kanban, multi-agent, dispatcher, relay, external-guard, workflow, verification]
---

# Hermes Kanban Workflows

Implement durable board, stage-Card, Dispatcher, dependency, review-lane, external-guard, reconciliation, and handoff mechanics for the development workflow. Development policy is owned by the calling `development-orchestrator`; this Skill implements the requested Kanban transition and must not redefine route or acceptance policy.

## Active-role model

Three roles may act on a development Card, but only one is active at a time:

- **Origin default-profile session** — the interactive session with Kenan. Owns intent convergence, accepted amendment comments, and unblocking; never owns execution.
- **Implement Worker** — a Dispatcher-spawned worker claimed from `ready`; owns one planning/implementation/rework run, any required UI acceptance, landing, and either `kanban_complete` (direct) or `kanban_request_review` (stage Card).
- **Review Worker** — a fresh Dispatcher-spawned worker claimed from `review`; delegates the stage-specific read-only review relay(s) and ends with exactly one of `kanban_complete`, `kanban_request_changes`, or a genuine typed `kanban_block`.

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

The external execution guard owns ONLY write-mode planning/implementation/rework Relay identity/session/result plus Git baseline/commit evidence. Read-only review Relay truth belongs to the native review run handoff; the guard is not reused by a Review Worker. It must not copy Card status, run history, review rounds, phase, heartbeat, retries, artifact arrays, or notification state.

## When to use

Load before creating, finalizing, routing, transitioning, reconciling, or completing a development Card, and before operating its external guard state. Also load for board provisioning, Dispatcher behavior, dependencies, task-scoped tools, handoff integrity, and Kanban verification.

## Board and Card mechanics

- Each active development project under `~/Secret-Projects/` uses a dedicated board whose slug is the kebab-case directory basename and whose default workdir is the project root; a repository without development work needs no board. Hermes self-work and projects outside that tree use `default`.
- Cards work directly in the trusted repository directory on main under Kenan's convention; do not use scratch/worktree unless the caller explicitly chooses another supported workspace contract.
- One Card represents one independently closable direct task or one stage of a plan-driven feature. A plan-driven feature has exactly two Cards (`write-plan` parent, `execute-plan` child); Relay attempts, review rounds, retries, artifacts, and same-stage fixes are never separate Cards.
- Use native parent links. Parent-blocked children remain `todo` and promote automatically after all parents complete.
- Use exact board slugs and explicit board arguments when no task-scoped binding exists. Read back every created or mutated target before claiming success.

For development Cards, the caller supplies a `development-stage.v1` body and policy fields. Create the Card with exactly:

- `board=<exact project board>` — never an implicit profile default;
- `assignee=default` — the literal development-contract assignee;
- `skills=[development-orchestrator, <selected-delegate-adapter>]` — pin both policy and transport (Pi default: `pi-delegate`);
- `workspace_kind=dir`, `workspace_path=<exact repository root>` — the trusted repository itself.

Converged tasks are created directly as dispatchable Cards. `kanban_finalize_intent` remains available only for existing triage/backlog Cards; it validates the complete replacement body and calls the native triage specification path, and it exits the default path. Do not repair missing product policy in this mechanics layer.

## Dispatcher semantics

- Dispatcher claims require `status=ready` and a non-empty assignee. The development contract uses literal `assignee=default`.
- Card `model`/`provider` configure the spawned Hermes worker, not the external Coding Agent.
- The worker receives `HERMES_KANBAN_DB`, `HERMES_KANBAN_BOARD`, `HERMES_KANBAN_TASK`, and the Card's workdir/skills.
- Dispatcher workers must begin with `kanban_show()`. Implement runs end through `kanban_complete`, `kanban_request_review`, or a typed `kanban_block`; review runs end through `kanban_complete`, `kanban_request_changes`, or a typed `kanban_block`.
- Interactive orchestrators need the `kanban` toolset; task-scoped workers receive focused lifecycle tools automatically. Orchestrator-only tools remain hidden from delegated children.
- `kanban.max_in_progress_per_profile` is enforced separately inside each board DB. It does **not** serialize one profile across boards. `kanban.max_in_progress` is the host-wide cap across board dispatch; Kenan's direct-main workflow requires both values to be `1`. Read both back before dispatching trusted-directory work.
- Emit heartbeats during long operations so stale reclaim does not silently recycle active work.
- Before supervising a long background Relay, verify the Worker's effective wait ceiling. `process_manage(wait)` is clamped by `TERMINAL_TIMEOUT`; for a Card with `max_runtime_seconds`, Dispatcher raises the worker-scoped ceiling to `max_runtime_seconds - 30` seconds when needed.
- For Relays expected to run longer than a few minutes, prefer 30–50 minute `process_manage(wait)` slices when the ceiling permits, then heartbeat before the next slice. Do not wake the model every few minutes, and do not reread `result.json` or the event stream while the process is still live; consume terminal artifacts only after process exit or during crash/reclaim reconciliation.

## Status transitions (native flow)

Use native lifecycle tools, not raw SQL. This workflow uses only:

- draft specification: `triage → todo`, then `recompute_ready()` promotes to `ready` if parent gates are closed;
- Dispatcher claim: `ready → running`;
- completion: `running → done` via `kanban_complete` after landing;
- stage handoff: implement `running → review` via `kanban_request_review(reviewer="default")`;
- review pass: review `running → done` via `kanban_complete`;
- review revise: review `running → ready|todo` via `kanban_request_changes`, restoring the recorded implementer and parent gating without block-loop accounting;
- blocker: `running → blocked` with the typed `dependency | needs_input | capability | transient` kind that matches reality; unblock returns the Card to dispatch;
- parking: `block` fires ONLY from `running`/`ready`; to park a `todo` Card non-dispatchably use `schedule` (`todo/ready/running/blocked → scheduled`, not claimable; `unblock` re-gates it).
- hard park — a Card that must not auto-dispatch after parent completion stays in `triage` while `kanban.auto_decompose=false`; only the specification surface may release it.

Direct Cards do not use the review lane. Both plan-driven stage Cards do. Keep `kanban.review_dispatch: true`; the Implement Worker completes required UI acceptance before requesting execute-stage review. Review Workers are fresh runs and receive `sdlc-review` plus the Card-pinned policy and adapter Skills.

## External execution guard

Each development Card owns at most one canonical guard state for its write-mode implement/rework lineage:

```text
~/Secret-Projects/development-artifacts/<board>/tasks/<card-id>/external-execution.json
```

schema `development-external-execution.v1`, written only through `development_external_guard.py`. The guard is fail-closed: it reserves before process creation, never retries automatically, records the exact terminal session ID, verifies the current native run before side effects, and detects the Card-trailer landing commit. Allowed outcomes are `spawned | attach | terminal | uncertain` (`inspect` also returns `none` when no attempt exists). `uncertain` blocks the Card.

Never hand-edit the state file, bypass the guard CLI for a write-mode Relay, or infer process safety from prose, PID absence, or elapsed time. Load `references/execution-recovery.md` before initializing, starting, inspecting, resuming, or landing a Card's external execution. A Review Worker instead validates each fresh read-only adapter process and `delegate-relay.result.v1` directly, records its result paths under a run-ID-specific directory, and relies on the native expected-run guard for its verdict. A reclaimed review run may leave duplicate read-only compute, but cannot overwrite another run's evidence or submit a stale verdict.

## Scheduled jobs

None. The global status Digest Cron (`development-status-digest`) was removed on 2026-09-07; the Cron job list is empty and no per-Card Cron, monitor, or wrapper exists. Observe active Cards through native Kanban notifications, direct board queries, or the Worker's own heartbeats.

## Reconciliation

Do not trust a column or self-report alone. Check cheapest-first:

1. exact board/Card and comments/events;
2. implement/rework: guard state, process identity, result path, session ID, commit;
3. review: native review run plus each fresh adapter process and `result.json`;
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
- the write-mode guard state validates: expected schema, one canonical current-attempt lineage, terminal session ID, and recorded commit when landing applies;
- `check-run` passes immediately before any write-mode Relay start, UI mutation, or Git commit; Review Workers validate their native review run through `kanban_show` and task-scoped terminal actions;
- truthful `delegate-relay.result.v1` terminal truth and load-bearing paths;
- `kanban.review_dispatch=true`; direct Cards complete without review, while both stage Cards use `request_review`/`request_changes` and a fresh Review Worker;
- the Cron job list matches the current scheduled-jobs decision in §Scheduled jobs (empty as of 2026-09-07) with no per-Card Crons, monitors, or wrappers — check the live list, do not assert it;
- requested status transition and no unrelated board mutation.

Detailed mechanics live in `references/kanban-mechanics.md`, `references/execution-recovery.md`, and `references/handoff-integrity.md`.
