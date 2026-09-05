---
name: development-orchestrator
description: Proxy development through Cursor, Codex, OpenCode, or Pi.
version: 0.11.0
author: 柯楠, Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [development, product-proxy, cursor, codex, opencode, pi, kanban, ui-acceptance]
    related_skills: [cursor-delegate, codex-delegate, opencode-delegate, pi-delegate, computer-use, hermes-kanban-workflows]
---

# Development Orchestrator

Act as Kenan's product proxy while an external coding agent owns engineering. Every independent development task has one Kanban card; complexity chooses direct delegation versus `write-plan`/`execute-plan`, while UI scope alone determines whether Watson performs behavior acceptance.

## When to Use

Load for requests that may change source code, tests, builds, migrations, developer tooling, generated runtime behavior, or product behavior.

Do not use for read-only research, implementation-free discussion, personal notes, or routine coordination/artifact writes that do not change project behavior.

## Ownership

### Watson: product control plane

Watson owns scope, observable success, card state, coding-agent selection, user decisions, top-level commissioning, UI behavior acceptance, landing authority, and completion. A Watson session woken by a monitor becomes the active orchestrator: it verifies durable state, updates the user, and continues the authorized lifecycle.

Watson does **not** write, repair, refactor, or code-review product code. It also does not dispatch or adjudicate `review-plan`, `review-patch`, or `review-plan-conformance`; those remain internal to the coding-agent parent.

### Coding agent: engineering control plane

The selected parent owns repository investigation, technical design, planning, implementation, tests, integration, internal delegation/review, and a verified handoff.

- Planning parent: `write-plan` plus its internal `review-plan` loop.
- Execution parent: fresh `execute-plan`, final verification, and risk-selected internal execution reviews.
- Direct parent: bounded implementation plus focused verification without `execute-plan`.

Watson consumes the compact terminal result and escalations rather than reproducing the internal protocol.

## Session Roles

A card's life passes through up to three Watson session roles. Handoffs happen through durable state — the board and the monitor state file — never through conversation memory. At most one role is the card's active orchestrator at any moment.

| Role | Spawned by | Owns |
|---|---|---|
| Origin session (interactive) | The user | Card creation with acceptance criteria; intent convergence; setting the assignee at convergence. During execution: read-only reconciliation only. When the card declares `manual_acceptance` items: close-out after user manual acceptance (commit → push → CI green → complete → monitor teardown). |
| Dispatcher worker (headless) | Gateway dispatcher claiming a `ready` card that carries an assignee (`hermes -p <assignee> chat -q`, `HERMES_KANBAN_TASK` injected) | Becomes active orchestrator: routes simple/structured, delegates to the coding agent, arms the card's single monitor. |
| Monitor-woken session (headless) | The card's 10-minute monitor Cron on an actionable tick | Verifies terminal state independently, updates the user, then continues the authorized lifecycle: rearm + fresh `execute-plan`, UI acceptance, or non-UI closure. Never defers ordinary continuation back to the origin session. |

Recognition: monitor-woken runs arrive as "Cronjob Response: t_<id> development-monitor" with `cron_`-prefixed session ids.

- **Assignee is the execution switch.** The dispatcher claims only `ready` cards with a non-empty assignee; `ready` alone just queues. Keep an intent-unconverged card unassigned; setting the assignee (`default`) at convergence is the explicit authorization to start.
- The creating session never launches that card's Relay; execution is initiated by the dispatcher worker and continued by monitor-woken sessions.
- While a Relay runs, the origin session observes read-only — no second Relay, no hand-edited `monitor-state.json` (a hand-written illegal enum once caused permanent BAD_STATE silence). It re-engages only at product decisions, blockers, or manual-acceptance close-out.

## Delegation Policy

- Default to **OpenCode**. Use Cursor, Codex, or **Pi** only when the user explicitly selects it for the current task.
- **Pi** is a formal selectable transport in gradual migration: same lifecycle, same one-monitor model, via the `pi-delegate` adapter. Choosing Pi means every stage of the card (discussion, planning, execution, rework) stays on Pi unless the user says otherwise.
- Preserve the current implementer for same-scope rework when its outer session is resumable.
- Load only the selected transport adapter; it owns mechanics, not workflow decisions.
- Do not ask which agent to use when the user has not specified one.

## Card and Board Rules

Create the card before delegation. One card represents one user-recognizable, independently closable task; reconnaissance, planning, execution, internal reviews, Relay attempts, retries, artifact writes, and same-scope fixes stay inside it. Create another card only for a new independent feature, bug, deliverable, or scope expansion.

Route `~/Secret-Projects/<project>` to a dedicated board matching the project directory in kebab-case, with the project root as default workdir. Hermes self-work and projects outside `~/Secret-Projects` use `default`. The Initiative layer is retired and read-only.

Work happens directly in the project repository on its main branch — the board's default workdir anchors the worker and the coding agent there. Never use scratch or git-worktree workspaces for project cards; landing is a local commit plus the authorized push, not a branch merge.

A dispatcher-owned card is launched by its claimed Watson worker. Put any external tool/model choice in the card body. Kanban `model`/`provider` fields configure the **Hermes worker**, not Cursor, Codex, or OpenCode. The creating session must not also launch the external Relay; execution initiation belongs to the dispatcher worker and terminal takeover to monitor-woken sessions (see Session Roles). Use `initial_status: blocked` only for a real immediate human-operations gate.

Read `hermes-kanban-workflows` for board provisioning, dependencies, dispatch mechanics, and reconciliation.

## Task Router

### Simple

Use one bounded writable parent only when impact is narrow, no architecture/persistence/migration/dependency/release/security/compatibility decision exists, no user-visible choice is unresolved, and a short behavior brief plus repository inspection is sufficient.

Require repository inspection, implementation, focused and relevant integration/end-to-end checks, exact observed results, changed-file scope, and residual limitations. Preserve unrelated work and forbid commits or external effects unless separately authorized.

Do not invoke `write-plan` or `execute-plan`. If investigation reveals broader coupling or a load-bearing decision, stop expansion, update the same card, and reclassify it as structured.

### Structured

Use for major, cross-module, architectural, persistent, migratory, ambiguous, broad-impact, or multi-part work.

If product intent is unsettled, create the card with draft acceptance criteria and `intent: unconverged`, and leave it unassigned; clear the marker and set the assignee only after live-repository grounding and user convergence — that assignment is the execution authorization (see Session Roles). Never plan or implement while the marker remains.

```text
card → intent/recon → write-plan (internal review-plan)
     → fresh execute-plan (verification + internal execution reviews)
     → UI acceptance when applicable → landing → done
```

## Structured Lifecycle

1. **Ground intent.** Start or resume one read-only coding-agent parent against the live repository. Keep routine technical choices with the agent; return only product, scope, compatibility, irreversible, or high-impact choices to the user. Finalize acceptance criteria, decisions, non-goals, and `ui_acceptance: required | not-required` in the card.
2. **Run `write-plan`.** Resume the same planning parent and invoke the discovered `write-plan` Skill. Permit only plan/audit writes; do not implement or commit. The parent owns reviewer dispatch, revisions, evidence, and its three-round ceiling. Require the exact final plan path, internal gate outcome, artifacts, and unresolved user decisions.
3. **Run fresh `execute-plan`.** Unless plan-only or blocked on a user decision, immediately start a fresh writable parent from the accepted plan. It owns implementation, integration, final verification, internal execution reviews, fixes, and evidence. Require a renderer-ready artifact for UI work or a complete engineering handoff otherwise.

Read `references/external-agent-workflow.md` before prompting or resuming a coding agent; it contains permission modes and canonical prompt shapes.

## Relay Monitoring

For background work, read `references/relay-monitoring.md`. The monitor is armed by the dispatcher worker at the first Relay; actionable ticks wake a fresh monitor-woken session (see Session Roles).

Each card owns exactly one `development-monitor.v2` state, one fixed wrapper, and one recurring 10-minute Cron across direct work, planning, execution, retries, recovery, and rework — regardless of transport (Cursor, OpenCode, or Pi all share the same single monitor). Every new Relay only rearms that state (`generation += 1`, new `attempt.out_dir`); `operation` is descriptive. Never create per-attempt monitors or monitors for internal review rounds. Healthy `RUNNING`, `idle`, and `closed` ticks are silent.

An actionable tick starts a fresh Watson session. It must independently confirm process exit, a valid terminal result, and every declared load-bearing artifact; then update the user before any new side effect and continue the already-authorized next stage. Stop only for a user decision, authority boundary, blocker, continuity loss, or completed task.

Retry policy for failed attempts: a failed Relay (crashed process, invalid or missing terminal result, incomplete handoff) is not automatically a blocker. When the failure looks transient (crash, timeout, transport error) and the same cause has not already consumed one retry on this card, the monitor-woken session rearms the state and retries the same stage once. A repeated same-cause failure — or any failure whose resolution would change scope or decisions — is a blocker: `kanban_block` with cause and evidence instead of retrying further.

## Completion by UI Scope

### UI task

UI scope includes graphical layout, menus, dialogs, hover, drag, scroll, keyboard/focus behavior, visible state, renderer persistence, and accessibility structure.

After engineering closes, move the card to `review`, read `references/behavior-acceptance.md`, and exercise the accepted UI scenarios in the real renderer. Record each as `PASS`, `FAIL`, or `BLOCKED`; engineering checks cannot replace this gate.

- `FAIL`: record the behavioral delta, return to `in_progress`, and resume the exact implementation parent.
- `BLOCKED`: report the blocker and keep the task open.
- Complete only when every authorized UI scenario passes.

Two acceptance layers exist, and Watson's real-renderer verdict is the default and only gate: once every authorized UI scenario passes, proceed directly to landing. User manual acceptance is a second, opt-in layer that applies only when the card body declares `manual_acceptance` items — behaviors Watson cannot reliably verify in the renderer (e.g. VoiceOver narration, transient hover/menus, long-scroll and drag feel, native density). With such items declared, a full Watson PASS does not complete the card: record the verdict, park the card for the user, and the origin session owns close-out after the user confirms. Without declared `manual_acceptance` items, never park for manual acceptance.

### Non-UI task

Never move non-UI work to `review` or independently repeat behavior verification, including CLI, API, service, migration, security, and developer-tooling work.

Perform only handoff-integrity closure: terminal result is truthful; declared artifacts and observed command results exist; internal gates closed; limitations and intended/unrelated Git changes are explicit; no unauthorized external effect occurred. Then land and complete directly from `in_progress`.

## Rework and Landing

For UI failure or incomplete handoff, resume the exact implementation parent with only the observed delta or missing contract. Do not diagnose or patch product code. Report continuity loss before replacing a non-resumable session.

After UI acceptance or non-UI closure:

1. Inspect Git status and separate intended from unrelated files without code-quality review.
2. Confirm no unauthorized remote, version, release, publication, deployment, or external-service action occurred.
3. Commit locally under standing authorization.
4. Push `obsidian-card-workspace` `main` under standing authorization; it triggers CI only.
5. Ask case-by-case before pushing `card-workspace-site` `main`, pushing tags, opening PRs, changing versions, publishing, deploying, or releasing.
6. Complete the card with compact evidence, internal gate outcomes, UI verdict when relevant, artifact pointers, and commit identity.

## Authority Boundaries

Return to the user before changing ambiguous visible behavior, scope, compatibility, persisted data, migration policy, security/privacy, architectural guardrails, production dependencies, or external services; before relying on an unverified external assumption; after accepted-plan invalidation or required-session loss; before discarding user work or any irreversible action; and before remote/release actions outside standing authorization.

## Non-Negotiable Invariants

- One correctly routed card per independent development task; none for internal operations.
- OpenCode by default; Cursor/Codex/Pi only by explicit task-scoped request.
- No brainstorming Skill exists in this workflow.
- `intent: unconverged` blocks planning and implementation.
- Internal reviews stay inside their owning coding-agent parent; Watson never invokes `delegate-work`.
- `execute-plan` always starts in a fresh parent; same-scope rework resumes its exact execution parent when possible.
- One fixed silent monitor per card; never one per attempt or review round.
- One active orchestrator per card at any time; the three session roles hand off only through durable board/monitor state.
- The card-creating session never launches that card's Relay; execution starts when the dispatcher claims an assigned ready card.
- A monitor-woken Watson verifies, updates the user, and continues rather than deferring to the origin session.
- Only UI tasks enter Kanban `review`; non-UI work receives no duplicate Watson behavior test.
- Watson never writes or reviews product code.
- No unauthorized commit, remote, version, release, publication, deployment, or irreversible action.
- Keep `kanban.review_dispatch: false`; review is Watson's UI gate.

## References

| Situation | Load |
|---|---|
| Prompting/resuming a coding agent | `references/external-agent-workflow.md` |
| Background Relay monitoring | `references/relay-monitoring.md` |
| Real-renderer UI acceptance | `references/behavior-acceptance.md` |
| Board routing/mechanics | `hermes-kanban-workflows` |
