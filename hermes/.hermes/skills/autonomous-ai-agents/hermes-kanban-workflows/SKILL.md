---
name: hermes-kanban-workflows
description: "Use when building or verifying Hermes Kanban workflows."
version: 1.3.7
tags: [kanban, multi-agent, dispatcher, workflow, verification]
---

# Hermes Kanban Workflows

Own board routing, dispatch mechanics, dependencies, handoffs, and reconciliation. The development lifecycle inside a card belongs to `development-orchestrator`; coding-agent review protocols do not belong here.

## When to Use

- Build, execute, or review a Kanban-controlled workflow.
- Create or route project boards and cards.
- Verify configuration, dispatch, concurrency, heartbeat, handoff, or reconciliation.

## Board Topology and Card Granularity

Every `~/Secret-Projects/<project>` repository uses a long-lived dedicated board whose slug is the directory basename in kebab-case and whose default workdir is the project root. Hermes self-work and projects outside that tree use `default`. Create a missing project board before its first card. Cards execute directly in the project repository on its main branch — never in scratch or git-worktree workspaces.

One card represents one user-recognizable, independently closable task or deliverable. Keep reconnaissance, discussion, `write-plan`, `execute-plan`, internal work packages/reviews, Relay attempts, monitoring, retries, artifact writes, and same-scope defects inside it. Create another card only for a new independent feature, bug, deliverable, or scope expansion.

The Initiative layer is retired and read-only. Kanban owns task progress, the repository owns product context, and durable artifacts own execution evidence.

Create the card before delegation. For unsettled structured work, record the initial goal, draft acceptance criteria, dependencies, and `intent: unconverged`; clear it only after live-repository grounding and user convergence. That marker blocks planning and implementation.

Use native parent links for cross-card dependencies. Parent-blocked children remain `todo` and promote automatically after all parents complete.

## Worker Ownership

A ready card assigned to a Hermes profile is dispatcher-owned; the claimed worker orchestrates it and launches any external coding agent through the matching adapter.

Session topology: the interactive origin session creates the card and converges intent; the dispatcher worker claims it, orchestrates, and arms the monitor; a monitor-woken session takes over terminal states. The dispatcher claims only `ready` cards that carry an assignee — assignee is the execution switch, set at intent convergence; an unassigned ready card merely queues. Full model: `development-orchestrator` → Session Roles.

- Card `model`/`provider` configure the spawned **Hermes worker**, not Cursor, Codex, or OpenCode. Put the external tool/model in the card body.
- Normal creation follows the dispatch path and appears `ready` until claimed. The creator must not also launch a Relay.
- Use `initial_status: blocked` only for a real immediate human-operations gate.

## Initiation Lanes and Message Identity

Execution has three session lanes; simple/structured routing is orthogonal to them:

1. **Origin interactive session** — creates the card, converges intent, does read-only reconciliation, owns close-out after user manual acceptance; never launches the Relay itself.
2. **Dispatcher worker (headless)** — the gateway dispatcher spawns `hermes -p <assignee> --cli chat -q` (`HERMES_KANBAN_TASK` injected) for a `ready` card; it becomes that card's active orchestrator and arms the single monitor. Its stdout goes to per-task logs under `<board-root>/logs/`, never to chat — the user sees only machine-formatted lifecycle notifications and card comments.
3. **Monitor-woken session (headless, Cron-spawned)** — fresh Watson spawned by an actionable tick; its reports arrive enveloped as `Cronjob Response: <job> (job_id: …)`, a deterministic delivery-layer wrapper, not model-added text.

Telling the lanes apart from the chat side: bare prose continuing the user's thread = interactive; `Cronjob Response:` envelope = monitor lane (session ids prefixed `cron_`); machine-formatted card events = worker notifications. A quote-reply to an enveloped cron message lands in the interactive session, not the cron session. An unwrapped conversational message from a worker is an anomaly — workers have no chat binding under the standard protocol.

## Lifecycle Inside One Card

Task complexity and UI scope are independent: simple work takes one direct delegated parent; structured work runs intent gate → `write-plan` (internal `review-plan`) → fresh `execute-plan` (internal execution reviews). Router criteria, the full lifecycle, and the session-role model live in `development-orchestrator`.

Watson does not create cards, Relays, or monitors for internal review stages. Record only meaningful transitions and compact outcomes.

## Review Column

Kanban `review` is exclusively Watson's real-UI behavior-acceptance gate; keep `kanban.review_dispatch: false`.

- Any accepted graphical UI behavior enters `review` after engineering closes.
- Non-UI work—including CLI, API, service, migration, security, and developer tooling—never enters `review` and receives no duplicate Watson behavior test; complete it after coding-agent verification and handoff-integrity closure.
- Mixed tasks use `review` only for UI behavior and its critical integration path.
- On UI failure, record the observed delta, return to `in_progress`, and resume the exact implementation parent.

```text
simple/structured non-UI: todo/ready → in_progress → done
any UI:                 todo/ready → in_progress → review → done
UI rework:              review → in_progress → review
```

Update cards only for intent convergence, plan/execution closure, UI-review entry/verdict, rework, blocker, landing, and completion—not reviewer rounds, process IDs, wrapper/Cron IDs, or routine polling.

## Relay and Handoff

Monitoring is orthogonal to board state. Each card owns one fixed `development-monitor.v2` state, wrapper, and recurring 10-minute Cron across all top-level runs; the dispatcher worker arms it and actionable ticks wake a monitor-woken Watson (see Worker Ownership). When creating that Cron, the schedule must be `every 10m` — a bare `10m` is a one-shot ISO-style job that dies after its first fire. New attempts only increment generation and bind a new output directory; healthy running ticks stay silent. A corrupted state file (e.g. a concurrent session hand-writing an illegal enum into `monitor-state.json`) classifies `BAD_STATE` and goes permanently zero-agent-silent — an unexplained long-silent monitor is a corruption suspect, not a quiet success; restoring a valid enum revives classification.

A monitor-woken Watson verifies current process state, terminal result, and every declared load-bearing artifact; updates the user before new side effects; then continues the authorized lifecycle. A missing plan, execution/review artifact, or deliverable is an incomplete handoff even when the process reports success — an integrity check, not a second non-UI behavior test.

Detailed mechanics live in `development-orchestrator/references/relay-monitoring.md` and `references/handoff-integrity.md`.

## Operating Model

Re-verify after Hermes updates because Kanban evolves quickly.

- Boards are isolated SQLite databases; dependencies never cross boards.
- One board-owner gateway dispatcher may sweep all registered boards and spawn any assignee profile.
- Dispatcher workers receive focused `kanban_*` tools through `HERMES_KANBAN_TASK`; interactive orchestrators need the `kanban` toolset.
- Native features include idempotency, dependencies, blocking kinds, per-task pins/limits, comments, events, run metadata, and attachments.
- `kanban.max_in_progress_per_profile` is per board; use a host-wide limit or policy for cross-board control.
- Long blocking calls need bounded waits or heartbeats so activity remains visible.

## Board Provisioning

For a Secret-Projects repository:

1. Derive the kebab-case slug from the directory basename.
2. List boards and reuse only an exact slug.
3. If absent, create it with a readable name and explicit absolute workdir.
4. Read it back and verify slug, name, and workdir.
5. Create the card on that explicit board without changing the user's active board unnecessarily.

Board slugs are immutable. Renames require an explicit mapping decision; archived/deleted repositories do not authorize board deletion.

## Reconciliation

Do not trust the column alone. Check, cheapest first: live Git status/history; terminal Relay result and final message; declared plan/execution/review/UI artifacts; monitor/teardown state; then session history if still ambiguous.

A card the user calls running but showing zero kanban runs is on the Relay line, not stalled: Kanban columns don't reflect Relay progress. Inspect cheapest-first, mutating nothing — `cronjob list` (the card's single `t_<card-id> development-monitor` Cron: enabled, last/next fire), `~/Secret-Projects/development-artifacts/<project>/tasks/<card-id>/monitor-state.json` (`monitor.state`, current attempt session/pid/out_dir, `generation`, any acknowledged `pending_event` = takeover already fired), `attempts/<gen>-<op>/` file sizes+mtimes and `ps -p <pid>` for live activity, the card comment thread (`kanban_show`) for takeover summaries, `acceptance/<slug>/<yyyymmdd>/verdict.md` + `final.txt` for behavior-acceptance verdicts, and repo `git status` for the uncommitted deliverable. Report stage, evidence timestamps, gates, verdicts, and what remains (user manual-acceptance items, commit/push, card closure, Cron teardown); never edit monitor state, Cron, wrapper, or board during a progress read.

Fuzzy board names resolve structurally, never by literal string match: a repo rename can leave a stale EMPTY board beside the live one (observed: empty `card-workspace` beside live `obsidian-card-workspace`). Read `~/.hermes/kanban/current`, list boards, prefer the non-empty one whose dependency graph matches the project, and answer "what's next" from `task_links` order plus per-card comment state (e.g. a `ready` card parked on user manual acceptance is the real next step, not the first `todo` card).

Comment the reconciled evidence. Move UI-ready work to `review`; complete non-UI work only after engineering and handoff closure; complete UI work only after a real-renderer verdict.

Origin-session closure after user manual acceptance — only for cards declaring `manual_acceptance` items, the origin role's final duty (monitor already `idle`, no woken takeover): the origin Watson owns the whole close-out — verify worktree matches the card's declared scope (no drift; build artifacts gitignored) → commit recording the manual verdict → push under standing authorization → confirm CI green before reporting (new `gh run list` entry may lag the push; sleep and re-check) → comment + `complete` the card → `close_monitor` if state still reads `idle` → remove the card's single Cron and wrapper, leaving `monitor-state.json`/`attempts/` as archive. A listed Cron showing `state: completed, enabled: false` is NOT torn down — it still occupies the one-Cron slot and must be explicitly removed.

## CLI and API Pitfalls

1. Prefer `kanban_*` tools in dispatcher workers; never write board SQLite directly.
2. CLI `--board` precedes the subcommand; `comment`/`create` take positional body/title. Use the exact listed slug.
3. `edit` does not change status; use `request-review` or `complete`.
4. Enable orchestration with `hermes config set toolsets '["hermes-cli", "kanban"]'`, then read back the resolved value.
5. CLI/scripts must run under the board-owner profile's `HERMES_HOME`.
6. Repeated same-cause block/unblock may trigger triage and auto-decomposition; disable `kanban.auto_decompose` when decomposition is forbidden.
7. `workflow_template_id` and `current_step_key` are metadata, not dispatcher routing.
8. When native top-level `artifacts` are used, keep result-owned artifacts under a metadata envelope to avoid path collisions.
9. The `kanban_*` lookup tools resolve a bare `task_id` against the session's active board context only. In an interactive session with no claimed `HERMES_KANBAN_TASK`, a card living in the `default` board needs `board="default"` (or the exact slug) passed explicitly, or `kanban_show` returns not-found.

## Verification

Before reporting a transition, confirm:

- exact board/workdir and one-card granularity;
- no unresolved `intent: unconverged` before planning/implementation;
- internal reviews stayed inside their coding-agent parent;
- only UI work entered `review`, with a real-renderer verdict before completion;
- non-UI closure used coding-agent evidence plus handoff integrity, not duplicate behavior testing;
- metadata/attachments read back correctly; and
- no unrelated board was mutated.

Current source-level behavior evidence lives in `references/kanban-mechanics.md`.
