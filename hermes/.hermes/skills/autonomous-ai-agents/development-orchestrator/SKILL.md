---
name: development-orchestrator
description: Proxy development through Cursor, Codex, OpenCode, or Pi.
version: 1.1.0
author: 柯楠, Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [development, product-proxy, cursor, codex, opencode, pi, kanban, ui-acceptance]
    related_skills: [cursor-delegate, codex-delegate, opencode-delegate, pi-delegate, computer-use, hermes-kanban-workflows]
---

# Development Orchestrator

Use this Skill as Kenan's single entry point for work that may change source code, tests, builds, migrations, developer tooling, generated runtime behavior, or product behavior. One development Card carries intent from discussion through engineering, acceptance, landing, and completion.

Watson is the user-facing name of the `default` Hermes profile; durable routing always uses `default`.

## MVP contract

Hermes Kanban is the sole Card/run/retry/heartbeat/handoff/notification control plane. One Dispatcher-spawned Execution Worker owns a Card from claim to completion or block. The small external execution guard (`development_external_guard.py`, documented in `hermes-kanban-workflows/references/execution-recovery.md`) only prevents duplicate Coding Agent Relays, records session/recovery facts, and detects the Card-trailer landing commit. Ambiguous external state blocks the Card; the Worker never guesses that a new spawn is safe.

There is no Goal Mode, no auto-decompose, no review lane, no per-Card Cron, no monitor, and no hook-driven transition. One global read-only status Digest reports active Cards.

## Layering and ownership

```text
L1 development-orchestrator      product/development control plane
L2 hermes-kanban-workflows       durable Kanban mechanics + external guard reference
L3 selected *-delegate adapter   Coding Agent transport mechanics
L4 external Coding Agent Skills  engineering workflow internals
```

Dependencies are one-way. This Skill owns user intent, route selection, authority, UI classification, top-level commissioning, Watson behavior acceptance, landing, and completion. Lower layers expose public results; they must not redefine policy.

The selected Coding Agent parent owns repository investigation, technical design, planning, implementation, tests, integration, internal delegation/review, and a verified handoff. Its `write-plan` and `execute-plan` internals are opaque to Hermes. Never reproduce or directly adjudicate internal reviewer names, rounds, model routing, work-package scheduling, or persistence formats.

Before creating, finalizing, routing, transitioning, reconciling, or completing a development Card—or operating its external guard state—load `hermes-kanban-workflows`.

## Session roles

Handoffs use the Card, its comments/events, and the guard state file—never conversation memory.

- **Origin default-profile session** — interactive session with Kenan. Owns intent convergence and dispatch authorization. It may commission temporary read-only repository grounding, but never implementation, `write-plan`, `execute-plan`, writable rework, landing, or release work.
- **Execution Worker** — the one Dispatcher-spawned headless worker that owns the Card from claim through planning, execution, engineering handoff, optional UI acceptance, rework, landing, and `kanban_complete`/`kanban_block`.

At most one role actively orchestrates a Card. The Origin grounding Session is ephemeral and its Coding Agent Session ID is never handed to the Execution Worker. No scheduled job ever advances, retries, blocks, commits, or completes a Card; the global Digest only reports.

## Standard Card contract

Every development Card body starts with:

```yaml
---
schema: development-task.v1
intent: draft | converged
execution_route: pending | direct | plan-driven
ui_acceptance: pending | required | not-required
manual_acceptance: []
coding_agent: pi | cursor | codex | opencode
---
```

Follow it with all sections below:

```markdown
# Goal

# Observable acceptance

# Included scope

# Non-goals

# Settled decisions

# Open decisions

# Repository grounding

# Authority boundaries
```

Rules:

- `intent: draft` requires `execution_route: pending`; UI may remain `pending` unless conclusively classified.
- `intent: converged` requires `execution_route: direct | plan-driven`, `ui_acceptance: required | not-required`, non-empty Goal and Observable acceptance, and `Open decisions: None`.
- `execution_route` is the only routing field. Do not add a parallel complexity marker.
- `coding_agent` defaults to `pi`; alternatives require explicit task-scoped user selection.
- Native Card fields are `assignee: default`, `workspace_kind=dir` with the exact repository path, and `skills: [development-orchestrator]`. Card `model` and `provider` configure the Hermes worker, not the external Coding Agent.
- Record product decisions, observable contracts, constraints, and concise load-bearing repository facts—not transcripts, chain-of-thought, raw logs, external Session IDs, or copied Coding Agent workflows.

## Creation flow

- **Converged tasks** are created directly as dispatchable Cards: `assignee=default`, `skills=[development-orchestrator]`, `workspace_kind=dir` with the exact repository path, and the complete converged body. They become dispatchable `ready` Cards through normal parent gating.
- **Existing draft/triage/backlog Cards** may still converge through `kanban_finalize_intent`, which validates the complete replacement body and advances the native `triage → todo → ready` path. This tool exits the default path; it is not part of normal dispatch. Draft Cards use `triage=true` while retaining `assignee=default`.
- Do not enable Goal Mode; do not rely on auto-decompose.
- Before dispatching real main-directory work, set the project board's `kanban.max_in_progress_per_profile` to one and read it back. This is a Hermes Kanban configuration matter, not a Card-body promise.

## Legacy Cards

The existing legacy Cards on `obsidian-card-workspace` (`t_5b033bdb`, `t_0af96a52`) stay untouched during implementation and the Pilot; they remain parked until the MVP pilot passes. After activation, a separate explicit mutation set will be proposed for them — either archive and recreate under the new contract, or park in `triage`/`blocked`, update all fields, then promote deliberately. Never change `watson → default` while a Card remains dispatchable `ready`. No automatic legacy migration exists.

## Intent convergence

Discuss unsettled product intent directly with Kenan. If repository facts are needed, commission a temporary read-only Coding Agent and normalize only verified conclusions into the Card. Before dispatch settle Goal, observable acceptance, scope, non-goals, decisions, route, UI classification, Coding Agent, and authority boundaries.

A product, compatibility, persistence, security, scope, irreversible, or authority decision discovered during execution is exceptional: block with `kind="needs_input"`. Ordinary technical choices already authorized by the Card or Plan remain with the Coding Agent.

## Dispatcher fail-closed gate

The Execution Worker must call `kanban_show()` first and refuse execution unless all are true:

- `schema: development-task.v1`;
- `intent: converged`;
- route is `direct` or `plan-driven`;
- UI classification is resolved;
- Goal and Observable acceptance are non-empty;
- `Open decisions` is `None`;
- `coding_agent` is supported;
- Board/workdir are expected and assignee is literal `default`.

Never infer a missing route, settle a product decision, or repair a draft Card in a worker. Block with the precise missing-contract reason.

## Required Worker flow

```text
kanban_show
→ validate converged Card
→ external guard init/inspect
→ Pi direct OR write-plan → fresh execute-plan
→ exact-session rework only when recorded
→ real renderer UI acceptance when required
→ check-run
→ Card-trailer commit/read-back
→ kanban_complete
```

1. **Claim.** `kanban_show()` and the fail-closed gate above.
2. **Guard init/inspect.** Run the external guard `init` (records Card/repo/Git baseline once) and `inspect`/`start-or-inspect` before any Relay. `attach` → observe the live Relay; `terminal` → consume the recorded result; `uncertain` → block.
3. **Engineering.** Route `direct`: one fresh ordinary writable Coding Agent parent. Route `plan-driven`: fresh Planning Parent (`write-plan`), then a fresh Execution Parent (`execute-plan`) with the exact accepted Plan path.
4. **Rework.** Same-scope rework resumes the exact recorded Coding Agent session only when the prior guard attempt is terminal and its session ID is recorded; otherwise start a fresh Relay through `start-or-inspect --operation rework`. A further rework round after a recorded-terminal rework attempt passes `--new-attempt`; each attempt uses a fresh out dir and result path. Report continuity loss before replacing a non-resumable session.
5. **UI acceptance.** When `ui_acceptance: required`, the same Worker exercises the real renderer per `references/behavior-acceptance.md`.
6. **Landing.** `check-run`, then the Card-trailer landing rule below.
7. **Completion.** `kanban_complete` with native summary, metadata, and artifacts.

Liveness while a Relay runs: bounded observation slices (~5 minutes), a Kanban heartbeat during long operations, and never deliberately exit while the Card is `running`. Native stale reclaim and the retry/circuit-breaker own Worker recycling; the guard only refuses unsafe duplicate spawns afterwards.

## Safety rules

1. Reserve before starting a Relay.
2. Never start a second Relay while an earlier attempt may exist.
3. Resume only an exact recorded Coding Agent Session after a known terminal attempt.
4. Check the current native Kanban run (`check-run`) immediately before Relay start, UI mutation, and Git commit.
5. Detect an already-created commit using the Card-specific Git trailer `Kanban-Task: <card-id>`.
6. Any ambiguous state blocks the Card; never guess that a new spawn is safe.

## Route selection

### `direct`

Use only for narrow work with no architecture, persistence, migration, dependency, release, security, compatibility, broad-coupling, or unresolved product decision. Start one fresh ordinary writable Coding Agent parent. Do not invoke `write-plan` or `execute-plan`. Require repository inspection, implementation, focused verification plus relevant integration/end-to-end checks, exact observed results, changed-file scope, and residual limitations.

If investigation exposes broader coupling or a load-bearing decision, stop expansion and block/reclassify the same Card rather than silently switching routes.

### `plan-driven`

Use for major, cross-module, architectural, persistent, migratory, ambiguous, broad-impact, or multi-part work.

1. Start a **fresh Planning Parent** from the standardized Card and explicitly commission `write-plan` through the selected transport adapter (`start-or-inspect --operation planning`). Do not pass an Origin Session ID. Permit only the writes required by that external workflow; do not implement or commit. Require success/blocked status, exact final Plan path, top-level workflow gate status, artifact pointers, and unresolved decisions or limitations.
2. Read back the exact Plan path. Unless plan-only or blocked, start a **fresh Execution Parent** (`start-or-inspect --operation execution`) and explicitly commission `execute-plan` with that path. Let the external workflow own implementation, internal delegation/review, fixes, and verification. Require exact commands and observed results, changed files, top-level gate status, renderer-ready artifact or complete non-UI handoff, and limitations.

Read `references/coding-agent-commissioning.md` for the public commissioning contract. Load exactly one selected transport adapter for its invocation syntax, permissions, Session mechanics, and result contract.

## UI classification and acceptance

UI scope includes graphical layout, menus, dialogs, hover, drag, scroll, keyboard/focus behavior, visible state, renderer persistence, and accessibility structure.

- `ui_acceptance: required`: after engineering handoff, the same Execution Worker follows `references/behavior-acceptance.md` and exercises accepted scenarios in the real renderer while the Card stays `running`. Engineering tests cannot replace this gate. Automatic `FAIL` returns to the implementation step with an observed behavior packet via exact-session rework; `BLOCKED` keeps the Card open.
- `ui_acceptance: not-required`: never duplicate the Coding Agent's behavior verification. Perform handoff-integrity closure, then land and complete from `running`.
- `manual_acceptance` is opt-in and only for behaviors Watson cannot reliably judge, such as VoiceOver narration, transient hover/native menus, long-scroll or drag feel, and subjective native density. Without declared items, do not park for manual acceptance. When automated scenarios pass but manual items remain, comment the exact checklist on the Card and block `kind="needs_input"`; a user `PASS` unblocks into landing.

This workflow never enters the Kanban `review` state. Keep `kanban.review_dispatch: false`.

## Landing and authority

Before the Coding Agent writes, the Worker's guard `init` has recorded the Git baseline (HEAD plus `git status --porcelain`). Landing rule:

1. `check-run` must pass.
2. Compare current Git status with the recorded baseline.
3. Stage only paths listed in the Coding Agent handoff.
4. A path dirty at baseline blocks instead of attempting attribution.
5. Search Git history for the exact trailer `Kanban-Task: <card-id>`.
6. If a matching commit already exists at/after `baseline_head`, record it with `record-commit` and complete without a second commit.
7. Otherwise create exactly one local commit with that trailer, read back its hash and trailer, then `record-commit`.

Authority: commit locally under standing authorization. Push `obsidian-card-workspace` `main` under standing authorization; it triggers CI only. Ask case-by-case before pushing `card-workspace-site` `main`, pushing tags, opening PRs, changing versions, publishing, deploying, or releasing. Confirm no unauthorized remote, version, release, publication, deployment, or external-service action occurred.

Return to Kenan before ambiguous visible behavior, scope, compatibility, persisted-data or migration policy, security/privacy, architectural guardrails, production dependencies, external services, irreversible actions, accepted-Plan invalidation, lost required Session continuity, or remote/release actions outside standing authorization.

## Completion and amendments

`kanban_complete(summary, metadata, artifacts)` stores the native handoff; subscribed conversations receive the terminal Gateway notification. Include compact engineering evidence, top-level gate status, UI verdict when relevant, artifacts, limitations, and commit identity.

Decisions after dispatch are append-only structured Card comments recorded by the Origin session; the Worker honors body plus amendments in sequence. Conflicting or non-user-approved amendments fail closed to `needs_input`. Repeated same-kind `needs_input` pauses may recurrence-route the Card to `triage`; the Origin folds body plus amendments into one converged body and re-finalizes.

## Status digest

Exactly one global read-only status Digest runs through the existing Cron `development-status-digest` (id `7f5731367ce5`, `every 30m`, `no_agent=true`). It prints one line per active development Card, including the external Relay state (`none/reserved/live/terminal/uncertain`), and nothing when none are active. It never mutates anything and never wakes an agent. No per-Card Cron, monitor, or wrapper exists.

## Invariants

- One Card per independent development task; no Cards for Planning, Execution, Relay attempts, or same-scope fixes.
- Pi by default; other transports only by explicit task-scoped request.
- Coding Agent engineering workflows are external black boxes.
- Fresh Planning Parent from the Card; fresh Execution Parent from the accepted Plan.
- Same-scope rework resumes the exact recorded session when possible; never a second Relay while an earlier attempt may exist.
- One Execution Worker owns the Card claim-to-completion; UI acceptance stays with that Worker in the real renderer.
- The guard owns only Relay identity/session/result and Git baseline/commit evidence; it never copies Card status, run history, heartbeats, retries, notifications, or handoff.
- Watson never writes, repairs, refactors, or code-reviews product code.
- No unauthorized commit, push, PR, release, deployment, publication, version change, or irreversible action.

## References

| Situation | Load |
|---|---|
| Coding Agent commissioning boundary | `references/coding-agent-commissioning.md` |
| Real-renderer UI acceptance | `references/behavior-acceptance.md` |
| Any Kanban/external-guard operation | `hermes-kanban-workflows` |
| Guard CLI and fail-closed semantics | `hermes-kanban-workflows/references/execution-recovery.md` |
| Coding Agent dispatch | exactly one selected `*-delegate` adapter |
