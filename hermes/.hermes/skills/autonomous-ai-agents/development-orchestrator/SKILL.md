---
name: development-orchestrator
description: Proxy development through Cursor, Codex, OpenCode, or Pi.
version: 2.0.0
author: 柯楠, Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [development, product-proxy, cursor, codex, opencode, pi, kanban, ui-acceptance]
    related_skills: [cursor-delegate, codex-delegate, opencode-delegate, pi-delegate, computer-use, hermes-kanban-workflows]
---

# Development Orchestrator

Use this Skill as Kenan's single entry point for work that may change source code, tests, builds, migrations, developer tooling, generated runtime behavior, or product behavior. One feature flows through ONE direct Card or TWO stage Cards (Write Plan → Execute Plan); every implement round and every review round is delegated to the Pi Coding Agent by a fresh Dispatcher Worker.

Watson is the user-facing name of the `default` Hermes profile; durable routing always uses `default`.

## MVP contract

Hermes Kanban is the sole Card/run/retry/heartbeat/handoff/notification control plane. Dispatcher-spawned Workers own runs. The small external execution guard (`development_external_guard.py`, documented in `hermes-kanban-workflows/references/execution-recovery.md`) only prevents duplicate Coding Agent Relays, records session/recovery facts, and detects the Card-trailer landing commit. Ambiguous external state blocks the Card; a Worker never guesses that a new spawn is safe.

Topology: simple features run on ONE direct Card (no card review). Plan-driven features run on TWO stage Cards — `write-plan` then `execute-plan`, child depends on parent. Each stage Card owns its review IN-CARD through the native review lane: the implement Worker calls `kanban_request_review`; a fresh review Worker (default profile) delegates read-only Pi review relays; `kanban_request_changes` returns the Card to the implementer without block-loop accounting.

No Goal Mode, no auto-decompose, no per-Card Cron, no monitor, no scheduled job of any kind.

## Layering and ownership

```text
L1 development-orchestrator      product/development control plane (this Skill)
L2 hermes-kanban-workflows       durable Kanban mechanics + external guard reference
L3 selected *-delegate adapter   Coding Agent transport mechanics
L4 external Coding Agent Skills  engineering workflow internals (agent_skills repo)
```

Dependencies are one-way. This Skill owns user intent, topology, authority, UI classification, commissioning, landing, and completion. Lower layers expose public results; they must not redefine policy. The Pi-side skills (write-plan, execute-plan, review-*, delegate-work) are lifted one level: they are now commissioned per Card round by the Worker, not run inside one long session. Their content is unchanged — the card split matches their existing contracts (execute-plan already starts from a saved plan path; review skills already accept workspace/commit-range scope).

The selected Coding Agent parent owns repository investigation, technical design, planning, implementation, tests, integration, internal delegation/review, and a verified handoff. Its internal workflow (including write-plan's built-in review cycle and execute-plan's default-on internal gates) is an external black box at its defaults; the card review is the independent outer gate. Never adjudicate internal reviewer names, rounds, or formats.

Before creating, finalizing, routing, transitioning, reconciling, or completing a development Card — or operating its external guard state — load `hermes-kanban-workflows`.

## Session roles

Handoffs use the Card, its comments/events, and the guard state file — never conversation memory.

- **Origin default-profile session** — interactive session with Kenan. Owns intent convergence and dispatch authorization; records append-only amendments; may commission temporary read-only grounding; never implements, reviews engineering output, or lands.
- **Implement Worker** — Dispatcher-spawned worker owning one implement run: guard init/inspect, Pi implement relay, UI acceptance (execute/direct cards), landing, then `kanban_request_review` (stage cards) or `kanban_complete` (direct card).
- **Review Worker** — fresh Dispatcher-spawned worker claimed from the review lane: delegates read-only Pi review relay(s), maps findings to exactly one verdict, never edits implementation.

At most one role actively orchestrates a Card at a time. No scheduled job ever advances a Card.

## Pi commissioning map

| Card stage | Implement relay brief | Review relay brief(s) | Review rounds |
|---|---|---|---|
| `direct` | `delegate-work` | none | — |
| `write-plan` | `write-plan` | `review-plan` | ≤3 |
| `execute-plan` | `execute-plan` | `review-patch` + `review-plan-conformance` | ≤3 |

- Every relay goes through exactly one selected `*-delegate` adapter (default Pi). Implement relays are write-mode; review relays are fresh, read-only, and never resume an implement session.
- Begin every brief with `Use the <skill> Skill (discovered from the global Skill root).` plus exact inputs: plan path for write/execute relays; diff base/head, reviewed head, or workspace scope plus intended behavior for review relays.
- Card `skills` pins the selected delegate adapter. Review Workers additionally get `sdlc-review` force-loaded by the dispatcher — treat it as generic verdict discipline; this Skill's commissioning map overrides its inspection method (delegate read-only Pi relays instead of local file inspection).
- If a brief's task scoping proves wrong mid-run, stop expansion and reclassify rather than silently switching skills.

## Stage Card contract (development-stage.v1)

Every Card body starts with:

```yaml
---
schema: development-stage.v1
workflow: <kebab-case feature id shared by the feature's cards>
stage: direct | write-plan | execute-plan
intent: draft | converged
ui_acceptance: pending | required | not-required
manual_acceptance: []
coding_agent: pi
pi_implement_skill: delegate-work | write-plan | execute-plan
pi_review_skill: none | review-plan | review-patch+review-plan-conformance
---
```

Follow it with the same sections as before: `# Goal`, `# Observable acceptance`, `# Included scope`, `# Non-goals`, `# Settled decisions`, `# Open decisions`, `# Repository grounding`, `# Authority boundaries`.

Rules:

- `intent: draft` cards sit in `triage`. `intent: converged` requires non-empty Goal and Observable acceptance, resolved UI classification, `Open decisions: None`, and stage-consistent skill fields (`direct`→`delegate-work`/`none`; `write-plan`→`write-plan`/`review-plan`; `execute-plan`→`execute-plan`/`review-patch+review-plan-conformance`).
- `execute-plan` bodies carry the accepted plan path (and plan SHA-256 when available) plus the write-plan Card id in Repository grounding.
- Native Card fields: `assignee: default`, `workspace_kind=dir` with the exact repository path, `skills: [<delegate-adapter>]`. Card `model`/`provider` configure the Hermes worker, not Pi.
- Record product decisions, observable contracts, constraints, and concise load-bearing repository facts — never transcripts, raw logs, or copied Coding Agent internals.

## Card topology and route selection

The Origin recommends, Kenan decides:

- **One direct Card** — narrow, single-module work with no architecture, persistence, migration, dependency, release, security, broad-coupling, or unresolved product decision. One write-mode relay with `delegate-work`; the Worker verifies, accepts UI when required, lands, and completes. No card review.
- **Two stage Cards** — major, cross-module, architectural, persistent, migratory, ambiguous, broad-impact, or multi-part work. Write Plan Card first; Execute Plan Card as its child (native parent link). The plan file produced by the write-plan Card is the sole authority for the execute-plan Card.
- Investigation on a direct Card that exposes broader coupling or a load-bearing decision stops and re-routes the same feature into stage cards (converge with Kenan first) rather than silently expanding.
- Downstream feature cards parent the feature's execute-plan Card (or the direct Card). Never park a long-running coordinator Card to wait for children — parent links and auto-promotion do that.

## Creation flow

- Before a feature's full intent has been discussed with Kenan, create its card(s) in `triage` (`triage=true`, `assignee=default`, draft body, both stage cards for a plan-driven feature). Converge through discussion; then finalize the body via `kanban_finalize_intent` (triage → todo → ready with parent gating).
- Already-converged requests may be created directly as dispatchable cards.
- Do not enable Goal Mode; do not rely on auto-decompose (`kanban.auto_decompose` is false).
- Before dispatching main-directory work, verify `kanban.max_in_progress_per_profile` is 1 in `config.yaml` (it serializes Execution Workers across boards; no per-board knob exists).

## Intent convergence

Discuss unsettled product intent directly with Kenan. If repository facts are needed, commission a temporary read-only relay and normalize only verified conclusions into the card. Before dispatch settle Goal, observable acceptance, scope, non-goals, decisions, topology (one vs two cards), UI classification, Coding Agent, and authority boundaries.

A product, compatibility, persistence, security, scope, irreversible, or authority decision discovered during execution is exceptional: block with `kind="needs_input"`. Ordinary technical choices already authorized by the card or plan remain with the Coding Agent.

## Dispatcher fail-closed gate

Every Worker (implement or review) begins with `kanban_show()` and refuses execution unless:

- `schema: development-stage.v1` (a legacy `development-task.v1` card explicitly grandfathered on a board is acceptable);
- implement runs: `intent: converged`, stage-consistent skill fields, resolved UI classification, non-empty Goal and Observable acceptance, `Open decisions: None`;
- review runs: the card was claimed from `review` and the latest handoff is this card's `review_requested`;
- Board/workdir are expected and assignee is literal `default`; `coding_agent` is supported.

Never infer a missing route, settle a product decision, or repair a draft card in a worker. Block with the precise missing-contract reason.

## Implement Worker flow

```text
kanban_show → fail-closed gate
→ guard init/inspect → Pi implement relay (skill per stage)
→ consume terminal result (commands, observed results, changed files, artifacts, limitations)
→ direct:      handoff-integrity closure → UI acceptance (if required) → check-run → landing commit → kanban_complete
→ write-plan:  verify exact plan path → artifacts-repo commit per its convention → kanban_request_review (metadata: plan path, review run facts)
→ execute-plan: handoff-integrity closure → UI acceptance (if required) → check-run → landing commit → kanban_request_review (metadata: commit, diff base/head)
```

- Relay liveness: bounded observation slices, Kanban heartbeats during long operations, never deliberately exit while `running`. Native stale reclaim and the retry/circuit-breaker own Worker recycling.
- Rework resumes the exact recorded Pi session (adapter rework rules); a further rework round after a recorded-terminal rework attempt passes `--new-attempt`; each attempt uses a fresh out dir and result path.

## Review Worker flow

```text
kanban_show → read handoff + prior rounds (count changes_requested runs)
→ fresh read-only Pi review relay(s), one per pi_review_skill
→ map findings → exactly one verdict:
   PASS   → kanban_complete(summary, metadata {verdict: pass, evidence, caveats})
   REVISE → kanban_comment(full findings) + kanban_request_changes(reason)
   BLOCK  → kanban_block (typed needs_input/capability; genuine human decision only)
```

- Blocking finding = P0/P1, or anything forcing a load-bearing change. P2-only rounds may pass with recorded caveats.
- `execute-plan` review aggregates BOTH relays (patch first, then conformance); any blocking finding in either → REVISE with merged findings in two labeled sections.
- Review round = prior `changes_requested` runs + 1. Do not start round 4: comment the state and `kanban_block(needs_input)` for Kenan's authorization and a materially revised candidate.
- The reviewer never edits implementation, never resumes implement sessions, never runs state-changing local commands; relays are read-only with `workspace` or commit-range scope.

## UI classification and acceptance

UI scope includes graphical layout, menus, dialogs, hover, drag, scroll, keyboard/focus behavior, visible state, renderer persistence, and accessibility structure.

- `ui_acceptance: required`: the IMPLEMENT Worker exercises accepted scenarios in the real renderer per `references/behavior-acceptance.md`, BEFORE requesting review (execute/direct cards). Engineering tests never replace this gate.
- `ui_acceptance: not-required`: never duplicate the Coding Agent's behavior verification; perform handoff-integrity closure only.
- `manual_acceptance` is opt-in for behaviors Watson cannot reliably judge (VoiceOver narration, transient hover feel, drag feel, subjective density). When automated scenarios pass but manual items remain, comment the checklist and block `needs_input`; a user PASS unblocks into review/landing.

## Landing and authority

Landing runs on the implement Worker (execute/direct cards) BEFORE `kanban_request_review`, so the reviewer sees a commit range:

1. `check-run` passes; 2. compare Git status with the guard baseline; 3. stage only handoff-listed paths (a path dirty at baseline blocks); 4. search history for the trailer `Kanban-Task: <card-id>`; 5. an existing matching commit at/after baseline is recorded, not re-committed; 6. otherwise create exactly one commit with that trailer, read back hash + trailer, then `record-commit`.

A REVISE → rework cycle produces a follow-up trailer commit the same way; push follows each landing commit under standing authorization (plugin repo main, CI only) — the card review may therefore land further commits. Ask case-by-case before pushing the site repo, tags, PRs, versions, releases, deployments, or any external action. The write-plan Card lands nothing in the product repo; artifacts-repo changes follow that repo's own convention.

Return to Kenan before ambiguous visible behavior, scope, compatibility, persisted-data or migration policy, security/privacy, architectural guardrails, production dependencies, external services, irreversible actions, accepted-plan invalidation, lost session continuity, or remote/release actions outside standing authorization.

## Completion and amendments

`kanban_complete(summary, metadata, artifacts)` stores the native handoff; subscribed conversations get the terminal notification. Include compact engineering evidence, verdict, UI verdict when relevant, artifacts, limitations, and commit identity.

Decisions after dispatch are append-only structured comments recorded by the Origin; Workers honor body plus amendments in sequence; conflicting or non-user-approved amendments fail closed to `needs_input`. Repeated same-kind `needs_input` may recurrence-route to `triage`; the Origin folds body plus amendments into one converged body and re-finalizes.

## Legacy cards (obsidian-card-workspace)

`t_3a4ea8ff` (架构加固) is the grandfathered execute-plan stage card — its plan was accepted on another machine and its guard/session history stands; it enters the card review lane on request like any execute-plan card. `t_5b033bdb` stays parked, never dispatched. `t_0af96a52` (Links 双链) stays parked `scheduled` pending Kenan's archive-and-recreate vs converge decision. The two experimental standalone review cards created 2026-09-07 were archived when the in-card review model was chosen.

## Scheduled jobs

None. Active-card visibility comes from native Kanban notifications and Worker reporting. No per-Card Cron, monitor, or wrapper exists.

## Invariants

- Per feature: one direct Card, or one Write Plan + one Execute Plan stage Card. Relay attempts, retries, review rounds, artifacts, and same-scope fixes never become separate Cards.
- Pi by default; other transports only by explicit task-scoped request.
- Fresh relay per round; reviews are read-only and never resume implement sessions; rework resumes the exact recorded implement session.
- Review is the native in-card lane: reviewer = `default` profile, `sdlc-review` + adapter skill, ≤3 rounds without Kenan's authorization.
- UI acceptance runs on the implement Worker before review request; engineering tests never replace it.
- The guard owns only Relay identity/session/result and Git baseline/commit evidence.
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
