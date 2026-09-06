---
name: hermes-kanban-workflows
description: "Use when building or verifying Hermes Kanban workflows."
version: 1.4.0
tags: [kanban, multi-agent, dispatcher, relay, workflow, verification]
---

# Hermes Kanban Workflows

Implement durable board, Card, Dispatcher, dependency, Relay-monitor, reconciliation, and handoff mechanics. Development policy is owned by the calling `development-orchestrator`; this Skill implements the requested Kanban/Relay transition and must not redefine the route or acceptance policy.

## When to use

Load before creating, finalizing, routing, transitioning, reconciling, or completing a development Card, and before creating or operating its Relay monitor. Also load for board provisioning, Dispatcher behavior, dependencies, task-scoped tools, handoff integrity, and Kanban verification.

## Board and Card mechanics

- Each `~/Secret-Projects/<project>` repository uses a dedicated board whose slug is the kebab-case directory basename and whose default workdir is the project root. Hermes self-work and projects outside that tree use `default`.
- Cards work directly in the trusted repository directory on main under Kenan's convention; do not use scratch/worktree unless the caller explicitly chooses another supported workspace contract.
- One Card represents one independently closable task. Internal Planning, Execution, review, Relay attempts, retries, artifacts, and same-scope fixes are not separate Cards.
- Use native parent links. Parent-blocked children remain `todo` and promote automatically after all parents complete.
- Use exact board slugs and explicit board arguments when no task-scoped binding exists. Read back every created or mutated target before claiming success.

For development Cards, the caller supplies a `development-task.v1` body and policy fields. Draft creation uses `triage=true` while retaining `assignee=default`; this prevents dispatch without using assignment as a policy switch. Finalize only through `kanban_finalize_intent`, which validates the complete replacement body and calls the native triage specification path. Do not repair missing product policy in this mechanics layer.

## Dispatcher semantics

- Dispatcher claims require `status=ready` and a non-empty assignee. The development contract uses literal `assignee=default`.
- Card `model`/`provider` configure the spawned Hermes worker, not the external Coding Agent.
- The worker receives `HERMES_KANBAN_DB`, `HERMES_KANBAN_BOARD`, `HERMES_KANBAN_TASK`, and the Card's workdir/skills.
- Dispatcher workers must begin with `kanban_show()` and terminate through `kanban_complete`, `kanban_block`, or the review transition prescribed by the caller.
- Interactive orchestrators need the `kanban` toolset; task-scoped workers receive focused lifecycle tools automatically. Orchestrator-only tools remain hidden from delegated children.
- `kanban.max_in_progress_per_profile` is per board; host-wide limits are separate.
- Emit heartbeats during long operations so stale reclaim does not silently recycle active work.

## Status transitions

Use native lifecycle tools, not raw SQL:

- draft specification: `triage → todo`, then `recompute_ready()` promotes to `ready` if parent gates are closed;
- Dispatcher claim: `ready → running`;
- caller-authorized UI acceptance: `running → review`;
- same-card UI rework: `review → running` through the supported review/rework surface;
- non-UI closure: `running → done`;
- blocker: use the typed `dependency | needs_input | capability | transient` kind that matches reality.

Keep `kanban.review_dispatch: false` for Kenan's workflow. This is a configuration fact; acceptance policy belongs to `development-orchestrator`.

## Relay monitor mechanics

Each development Card owns exactly one:

- `development-monitor.v2` state;
- fixed generated wrapper;
- recurring Cron named `t_<card-id> development-monitor`;
- schedule exactly `every 10m`.

A new top-level Relay only increments `generation` and binds a new `attempt.out_dir`. Canonical state values are lowercase `idle | relay_running | closed`. Never hand-edit monitor state, create per-attempt monitors, or use uppercase `RUNNING` (invalid state can become permanently silent).

Load `references/relay-monitoring.md` before creating, rearming, waking, closing, or tearing down a monitor.

## Reconciliation

Do not trust a column or self-report alone. Check cheapest-first:

1. exact board/Card and comments/events;
2. monitor Cron, state, current generation, process identity, and output directory;
3. live process state and adapter `result.json`;
4. declared load-bearing artifacts and digests;
5. Git status/history;
6. acceptance evidence when the caller requires it;
7. session history only if ambiguity remains.

Never mutate monitor state, Cron, wrapper, board, or Git during a progress-only read. Comment compact verified evidence on the Card when reconciliation changes lifecycle understanding.

## Handoff integrity

A completed-looking Relay is incomplete if the process is live, the terminal result is malformed/missing, or declared artifacts are absent or hash-mismatched. Validate terminal truth and producer-owned artifacts without duplicating engineering behavior tests. See `references/handoff-integrity.md`.

## Tool and API pitfalls

1. Prefer `kanban_*` tools; never patch Kanban SQLite directly.
2. Board resolution precedence is task-scoped DB/board binding, explicit board, active-board symlink, then profile default. Use profile-safe Hermes paths.
3. A bare `task_id` in an unclaimed interactive session needs `board="default"` or the exact slug when the target is not the active board.
4. `edit` does not replace lifecycle transitions; use specification, review, completion, block, or unblock surfaces.
5. Repeated same-cause block/unblock can trigger triage. Use a precise typed blocker and do not loop.
6. `workflow_template_id` and `current_step_key` are metadata, not Dispatcher routing.
7. Native top-level `artifacts` are attachment paths; keep structured result objects under a nested metadata key to avoid collisions.
8. Teardown uses the supported Cron API/tool surface. Never remove the source Cron inside its own active fire.

## Verification

Before reporting success, read back and confirm:

- exact board/workdir/task and parent gating;
- exact body/assignee/status/event after intent finalization;
- one monitor state, one wrapper, one Cron;
- Cron name `t_<card-id> development-monitor` and schedule `every 10m`;
- lowercase monitor state and current-generation output path;
- truthful terminal result and declared artifacts;
- requested status transition and no unrelated board mutation.

Detailed evidence and drills live in `references/kanban-mechanics.md`, `references/handoff-integrity.md`, and `references/pilot-drills.md`.
