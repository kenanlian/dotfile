---
name: development-orchestrator
description: Proxy development through Cursor, Codex, OpenCode, or Pi.
version: 0.12.0
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

## Layering and ownership

```text
L1 development-orchestrator      product/development control plane
L2 hermes-kanban-workflows       durable Kanban and Relay mechanics
L3 selected *-delegate adapter   Coding Agent transport mechanics
L4 external Coding Agent Skills  engineering workflow internals
```

Dependencies are one-way. This Skill owns user intent, route selection, authority, UI classification, top-level commissioning, Watson behavior acceptance, landing, and completion. Lower layers expose public results; they must not redefine policy.

The selected Coding Agent parent owns repository investigation, technical design, planning, implementation, tests, integration, internal delegation/review, and a verified handoff. Its `write-plan` and `execute-plan` internals are opaque to Hermes. Never reproduce or directly adjudicate internal reviewer names, rounds, model routing, work-package scheduling, or persistence formats.

Before creating, finalizing, routing, transitioning, reconciling, or completing a development Card—or operating its Relay monitor—load `hermes-kanban-workflows`.

## Session roles

Handoffs use the Card and monitor state, never conversation memory.

- **Origin default-profile session** — interactive session with Kenan. Owns intent convergence and dispatch authorization. It may commission temporary read-only repository grounding, but never implementation, `write-plan`, `execute-plan`, writable rework, landing, or release work.
- **Dispatcher-spawned default worker** — headless worker created after a converged assigned Card reaches `ready`. Begins with `kanban_show()`, validates the complete Card contract, selects the recorded route, dispatches the Coding Agent, and arms the Card monitor.
- **Monitor-woken default-profile session** — reconstructs terminal state from durable evidence and continues an already-authorized lifecycle. It does not defer ordinary continuation to the Origin session.

At most one role actively orchestrates a Card. The Origin grounding Session is ephemeral and its Coding Agent Session ID is never handed to the Dispatcher worker.

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
- Native Card fields are `assignee: default`, `skills: [development-orchestrator]`, and the project board's trusted repository workdir convention. Card `model` and `provider` configure the Hermes worker, not the external Coding Agent.
- Record product decisions, observable contracts, constraints, and concise load-bearing repository facts—not transcripts, chain-of-thought, raw logs, external Session IDs, or copied Coding Agent workflows.

Use `triage=true` with `assignee=default` for draft Cards. A draft remains non-dispatching while intent converges. Finalize it only through `kanban_finalize_intent`, which validates and atomically advances the native `triage → todo → ready` path according to parent gating. An already-converged request may be created directly as an assigned ready Card.

## Intent convergence

Discuss unsettled product intent directly with Kenan. If repository facts are needed, commission a temporary read-only Coding Agent and normalize only verified conclusions into the Card. Before finalization settle Goal, observable acceptance, scope, non-goals, decisions, route, UI classification, Coding Agent, and authority boundaries.

A product, compatibility, persistence, security, scope, irreversible, or authority decision discovered during execution is exceptional: block with `kind="needs_input"`. Ordinary technical choices already authorized by the Card or Plan remain with the Coding Agent.

## Dispatcher fail-closed gate

The Dispatcher worker must call `kanban_show()` first and refuse execution unless all are true:

- `schema: development-task.v1`;
- `intent: converged`;
- route is `direct` or `plan-driven`;
- UI classification is resolved;
- Goal and Observable acceptance are non-empty;
- `Open decisions` is `None`;
- `coding_agent` is supported;
- Board/workdir are expected and assignee is literal `default`.

Never infer a missing route, settle a product decision, or repair a draft Card in a worker. Block with the precise missing-contract reason.

## Route selection

### `direct`

Use only for narrow work with no architecture, persistence, migration, dependency, release, security, compatibility, broad-coupling, or unresolved product decision. Start one fresh ordinary writable Coding Agent parent. Do not invoke `write-plan` or `execute-plan`. Require repository inspection, implementation, focused verification plus relevant integration/end-to-end checks, exact observed results, changed-file scope, and residual limitations.

If investigation exposes broader coupling or a load-bearing decision, stop expansion and block/reclassify the same Card rather than silently switching routes.

### `plan-driven`

Use for major, cross-module, architectural, persistent, migratory, ambiguous, broad-impact, or multi-part work.

1. Start a **fresh Planning Parent** from the standardized Card and explicitly commission `write-plan` through the selected transport adapter. Do not pass an Origin Session ID. Permit only the writes required by that external workflow; do not implement or commit. Require success/blocked status, exact final Plan path, top-level workflow gate status, artifact pointers, and unresolved decisions or limitations.
2. Read back the exact Plan path. Unless plan-only or blocked, start a **fresh Execution Parent** and explicitly commission `execute-plan` with that path. Let the external workflow own implementation, internal delegation/review, fixes, and verification. Require exact commands and observed results, changed files, top-level gate status, renderer-ready artifact or complete non-UI handoff, and limitations.

Read `references/coding-agent-commissioning.md` for the public commissioning contract. Load exactly one selected transport adapter for its invocation syntax, permissions, Session mechanics, and result contract.

## UI classification and acceptance

UI scope includes graphical layout, menus, dialogs, hover, drag, scroll, keyboard/focus behavior, visible state, renderer persistence, and accessibility structure.

- `ui_acceptance: required`: after engineering handoff, enter Kanban `review`, read `references/behavior-acceptance.md`, and exercise accepted scenarios in the real renderer. Engineering tests cannot replace this gate. `FAIL` returns to `in_progress` and resumes the exact Execution/Direct parent with an observed behavior packet; `BLOCKED` keeps the Card open.
- `ui_acceptance: not-required`: never enter `review` or duplicate the Coding Agent's behavior verification. Perform only handoff-integrity closure, then land and complete from `in_progress`.
- `manual_acceptance` is opt-in and only for behaviors Watson cannot reliably judge, such as VoiceOver narration, transient hover/native menus, long-scroll or drag feel, and subjective native density. Without declared items, do not park for manual acceptance.

Keep `kanban.review_dispatch: false`; Kanban `review` is the board state for Watson behavior acceptance, not Coding Agent internal review.

## Landing and authority

After acceptance or non-UI closure:

1. Inspect Git status and separate intended from unrelated files without performing code review.
2. Confirm no unauthorized remote, version, release, publication, deployment, or external-service action occurred.
3. Commit locally under standing authorization.
4. Push `obsidian-card-workspace` `main` under standing authorization; it triggers CI only.
5. Ask case-by-case before pushing `card-workspace-site` `main`, pushing tags, opening PRs, changing versions, publishing, deploying, or releasing.
6. Complete the Card with compact engineering evidence, top-level gate status, UI verdict when relevant, artifacts, limitations, and commit identity.

Return to Kenan before ambiguous visible behavior, scope, compatibility, persisted-data or migration policy, security/privacy, architectural guardrails, production dependencies, external services, irreversible actions, accepted-Plan invalidation, lost required Session continuity, or remote/release actions outside standing authorization.

## Invariants

- One Card per independent development task; no Cards for Planning, Execution, reviews, Relay attempts, or same-scope fixes.
- Pi by default; other transports only by explicit task-scoped request.
- Coding Agent engineering workflows are external black boxes.
- Fresh Planning Parent from the Card; fresh Execution Parent from the accepted Plan.
- Same-scope rework resumes the exact implementation parent when possible.
- Only UI tasks enter Kanban `review`.
- Watson never writes, repairs, refactors, or code-reviews product code.
- No unauthorized commit, push, PR, release, deployment, publication, version change, or irreversible action.

## References

| Situation | Load |
|---|---|
| Coding Agent commissioning boundary | `references/coding-agent-commissioning.md` |
| Real-renderer UI acceptance | `references/behavior-acceptance.md` |
| Any Kanban/Relay operation | `hermes-kanban-workflows` |
| Coding Agent dispatch | exactly one selected `*-delegate` adapter |
