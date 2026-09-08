---
name: development-orchestrator
description: Proxy development through Cursor, Codex, OpenCode, or Pi.
version: 2.1.1
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

Topology: simple features run on ONE direct Card (no card review). Plan-driven features run on TWO stage Cards — `write-plan` then `execute-plan`, child depends on parent. Each stage Card owns its review IN-CARD through the native review lane: the implement Worker calls `kanban_request_review` without pinning a reviewer; Kanban's native default reviewer routing launches a fresh review Worker to delegate read-only Pi review relays; `kanban_request_changes` returns the Card to the implementer without block-loop accounting.

No Goal Mode, no auto-decompose, no per-Card Cron, no monitor, no scheduled job of any kind.

## Layering and ownership

```text
L1 development-orchestrator      product/development control plane (this Skill)
L2 hermes-kanban-workflows       durable Kanban mechanics + external guard reference
L3 selected *-delegate adapter   Coding Agent transport mechanics
L4 external Coding Agent Skills  engineering workflow internals (agent_skills repo)
```

Dependencies are one-way. This Skill owns user intent, topology, authority, UI classification, commissioning, landing, and completion. Lower layers expose public results; they must not redefine policy. Pi-side entry Skills are commissioned per Card run. `write-plan` and `execute-plan` were explicitly amended so a brief declaring this outer native review gate skips their duplicate internal final-review cycles; their internal planning, delegation, implementation, and verification remain unchanged.

The selected Coding Agent parent owns repository investigation, technical design, planning/implementation, tests, integration, internal work-package delegation, and a verified handoff. Every stage implement brief must say that the **outer native Card review gate owns final review**. This causes `write-plan`/`execute-plan` to report `skip: outer review gate` and prevents duplicate `.dev/plan-review` or `.dev/review` cycles. Never reconstruct their internal persistence formats.

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
- Card `skills` pins both `development-orchestrator` and the selected delegate adapter. Review Workers additionally get `sdlc-review` force-loaded by the dispatcher. For a `development-stage.v1` Card, use `sdlc-review` only for role separation and terminal verdict discipline; this Skill's commissioning map replaces its local inspection/test procedure with the required read-only Pi review relay(s).
- Adapter `--read-only` constrains only the top-level Pi tool set; `delegate_agent` is still available. Every review brief must therefore forbid the reviewer **and all delegated children** from editing files or invoking write-access children. This is an instruction boundary, not an OS sandbox.
- If a brief's task scoping proves wrong mid-run, stop expansion and reclassify rather than silently switching skills.
- Execute-plan implement relays and every same-session rework relay pass `--auto-handoff-plan <absolute accepted plan path>` so the top-level Pi parent runs Auto Handoff scoped to the relay out dir; direct, write-plan, and all review relays never pass it; delegated children never receive the extension.

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
- Native Card fields: `assignee: default`, `workspace_kind=dir` with the exact repository path, `skills: [development-orchestrator, <delegate-adapter>]`. Card `model`/`provider` configure the Hermes worker, not Pi.
- Record product decisions, observable contracts, constraints, and concise load-bearing repository facts — never transcripts, raw logs, or copied Coding Agent internals.

## Card topology and route selection

The Origin recommends, Kenan decides:

- **One direct Card** — narrow, single-module work with no architecture, persistence, migration, dependency, release, security, broad-coupling, or unresolved product decision. One write-mode relay with `delegate-work`; the Worker verifies, accepts UI when required, lands, and completes. No card review.
- **Two stage Cards** — major, cross-module, architectural, persistent, migratory, ambiguous, broad-impact, or multi-part work. Write Plan Card first; Execute Plan Card as its child (native parent link). The plan file produced by the write-plan Card is the sole authority for the execute-plan Card.
- Investigation on a direct Card that exposes broader coupling or a load-bearing decision stops and re-routes the same feature into stage cards (converge with Kenan first) rather than silently expanding.
- Downstream feature cards parent the feature's execute-plan Card (or the direct Card). Never park a long-running coordinator Card to wait for children — parent links and auto-promotion do that.

## Creation and stage-release flow

- Direct feature: create one draft Card in `triage`; after intent convergence, finalize it to dispatch.
- Plan-driven feature: create both draft Cards in `triage` and immediately link `write-plan` as parent of `execute-plan`. After product intent converges, finalize **only the write-plan Card**. The execute-plan Card must remain `triage` because no accepted Plan path/SHA exists yet.
- A PASS review completes the write-plan Card. The Origin then reads its exact Plan path and SHA-256 from the native handoff, folds those plus the write-plan Card id into the execute-plan body, and finalizes the execute-plan Card. Since its parent is now done, native gating promotes it to `ready`.
- An already-accepted Plan is the only case where an execute-plan Card may be created/finalized directly. A merely converged feature request is not an accepted Plan.
- Do not enable Goal Mode; do not rely on auto-decompose (`kanban.auto_decompose` is false).
- Before dispatching trusted-directory work, verify both `kanban.max_in_progress_per_profile=1` (per board) and `kanban.max_in_progress=1` (host-wide across boards).

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
→ write-plan:  verify exact plan path + SHA → artifacts-repo commit per its convention → kanban_request_review(metadata: plan path/SHA + relay result; reviewer omitted)
→ execute-plan: handoff-integrity closure → UI acceptance (if required) → check-run → landing commit → kanban_request_review(metadata: commit + diff base/head + relay result; reviewer omitted)
```

- Advance beyond Relay handling only when `delegate-relay.result.v1` is terminal with `status: completed`, `exitCode: 0`, the expected mode/session/CWD, and every stage-required output. `unavailable` blocks `capability`; `failed`, `timeout`, or `aborted` never proceed to UI/landing/review and must be reconciled or blocked with the matching typed cause. Missing or ambiguous required output is not success.
- Relay liveness: bounded observation slices, Kanban heartbeats during long operations, never deliberately exit while `running`. Native stale reclaim and the retry/circuit-breaker own Worker recycling.
- Every implement brief begins with the stage Skill directive and explicitly says `Outer native Card review owns final review; skip the Pi-internal final review gate.`
- Rework after `kanban_request_changes` runs in a fresh Implement Worker but resumes the exact recorded Pi implement session. A further rework round after a recorded-terminal rework attempt starts its next guard attempt with `start-or-inspect --new-attempt` (a guard CLI flag, not a relay flag); every attempt uses a fresh out dir and result path. Execute-plan rework relays re-pass `--auto-handoff-plan` with the same accepted plan path; write-plan rework does not.

## Review Worker flow

```text
kanban_show → read handoff + prior rounds (count changes_requested runs)
→ fresh read-only Pi review relay(s), one per pi_review_skill
→ map findings → exactly one verdict:
   PASS   → kanban_complete(summary, metadata {verdict: pass, evidence, caveats})
   REVISE → kanban_comment(full findings) + kanban_request_changes(reason)
   BLOCK  → kanban_block (typed needs_input/capability; genuine human decision only)
```

- The Review Worker does not use the write-mode external guard. For round `N`, each relay gets `development-artifacts/<board>/tasks/<card-id>/reviews/round-N/run-<kanban-run-id>/<review-skill>/` with its own `result.json`; the Worker waits for process exit, validates `delegate-relay.result.v1`, and records those paths in the native review run.
- Normalize Pi verdict vocabularies before routing: `review-plan APPROVE`, `review-patch correct`, and `review-plan-conformance CONFORMS` are pass candidates. Any P0/P1 or finding that forces a load-bearing change is blocking; P2-only findings may pass only when the Review Worker records why they are bounded caveats. `INCOMPLETE` blocks only when the missing evidence needs human/external input; otherwise request changes for the missing proof.
- `execute-plan` review aggregates BOTH relays (patch first, then conformance) over the same committed diff range and includes implementation plus UI-acceptance evidence in both briefs; any blocking finding in either → REVISE with merged findings in two labeled sections.
- Review round = prior `changes_requested` runs + 1. Do not start round 4: comment the state and `kanban_block(needs_input)` for Kenan's authorization and a materially revised candidate.
- The reviewer never edits implementation, never resumes implement sessions, and never runs local project checks. Its Pi relays are fresh `--read-only`, use plan or commit-range scope, and forbid write-access delegated children.

## UI classification and acceptance

UI scope includes graphical layout, menus, dialogs, hover, drag, scroll, keyboard/focus behavior, visible state, renderer persistence, and accessibility structure.

- `ui_acceptance: required`: the IMPLEMENT Worker exercises accepted scenarios in the real renderer per `references/behavior-acceptance.md`, BEFORE requesting review (execute/direct cards). Engineering tests never replace this gate.
- `ui_acceptance: not-required`: never duplicate the Coding Agent's behavior verification; perform handoff-integrity closure only.
- `manual_acceptance` is opt-in for behaviors Watson cannot reliably judge (VoiceOver narration, transient hover feel, drag feel, subjective density). When automated scenarios pass but manual items remain, comment the checklist and block `needs_input`; a user PASS unblocks to a fresh Implement Worker, which re-verifies run ownership and continues with landing then review/completion.

## Landing and authority

Landing runs on the implement Worker (execute/direct cards) BEFORE `kanban_request_review`, so the reviewer sees a commit range:

1. `check-run` passes; 2. compare Git status with the guard baseline; 3. stage only handoff-listed paths (a path dirty at baseline blocks); 4. search history for the trailer `Kanban-Task: <card-id>`; 5. an existing matching commit at/after baseline is recorded, not re-committed; 6. otherwise create exactly one commit with that trailer, read back hash + trailer, then `record-commit`.

Write-mode Pi has shell access, so “do not commit/push” is an instruction boundary. If Git history shows that Pi committed or pushed despite the brief, stop and block for attribution/recovery; never silently adopt or rewrite that side effect as the Worker's authorized landing.

A REVISE → rework cycle produces a follow-up trailer commit the same way; push follows each landing commit under standing authorization (plugin repo main, CI only) — the card review may therefore land further commits. Ask case-by-case before pushing the site repo, tags, PRs, versions, releases, deployments, or any external action. The write-plan Card lands nothing in the product repo; artifacts-repo changes follow that repo's own convention.

Return to Kenan before ambiguous visible behavior, scope, compatibility, persisted-data or migration policy, security/privacy, architectural guardrails, production dependencies, external services, irreversible actions, accepted-plan invalidation, lost session continuity, or remote/release actions outside standing authorization.

## Completion and amendments

`kanban_complete(summary, metadata, artifacts)` stores the native handoff; subscribed conversations get the terminal notification. Include compact engineering evidence, verdict, UI verdict when relevant, artifacts, limitations, and commit identity.

Decisions after dispatch are append-only structured comments recorded by the Origin; Workers honor body plus amendments in sequence; conflicting or non-user-approved amendments fail closed to `needs_input`. Repeated same-kind `needs_input` may recurrence-route to `triage`; the Origin folds body plus amendments into one converged body and re-finalizes.

## Legacy cards (obsidian-card-workspace)

`t_3a4ea8ff` (架构加固) is the grandfathered execute-plan stage Card — its plan was accepted on another machine and its guard/session history stands; it enters the Card review lane like any execute-plan Card. `t_5b033bdb` stays parked, never dispatched. `t_0af96a52` (Links 双链) stays hard-parked in `triage` pending deliberate convergence. The two experimental standalone review Cards remain archived.

## Scheduled jobs

None. Active-card visibility comes from native Kanban notifications and Worker reporting. No per-Card Cron, monitor, or wrapper exists.

## MVP enforcement boundaries

Mechanically enforced: native Card/run ownership and expected-run terminal transitions; write-mode Relay duplicate/recovery state; top-level Pi tool mode; process-exit/result schema/status; exact resumed Pi Session ID; Card-trailer landing evidence; top-level Auto Handoff extension loading + scoped env injection (execute-plan relays only).

Instruction-enforced and then verified fail-closed: delegated children of a read-only Pi reviewer must not write; writable Pi must not commit/push; stage-specific outputs live in `finalMessage` rather than typed result fields. Workers inspect Git and required outputs and block on any violation or ambiguity.

Read-only review Relays intentionally do not use the write-mode guard. A reclaimed review run can therefore leave an orphan read-only Pi process. The replacement run uses its own run-ID output directory, never overwrites prior evidence, and owns the only valid Kanban verdict through expected-run checking; duplicate read-only compute is tolerated in this MVP, but duplicate writes or Card transitions are not.

## Invariants

- Per feature: one direct Card, or one Write Plan + one Execute Plan stage Card. Relay attempts, retries, review rounds, artifacts, and same-scope fixes never become separate Cards.
- Pi by default; other transports only by explicit task-scoped request.
- Fresh relay per round; reviews are read-only and never resume implement sessions; rework resumes the exact recorded implement session.
- Review is the native in-card lane: use Kanban's default reviewer routing (omit `reviewer`; persisted reviewer provenance owns re-review routing), with `sdlc-review` + adapter skill and ≤3 rounds without Kenan's authorization.
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
