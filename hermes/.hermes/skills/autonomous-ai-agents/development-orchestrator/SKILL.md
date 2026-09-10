---
name: development-orchestrator
description: Proxy development through Cursor, Codex, OpenCode, or Pi.
version: 3.0.0
author: 柯楠, Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [development, product-proxy, cursor, codex, opencode, pi, kanban, ui-acceptance]
    related_skills: [cursor-delegate, codex-delegate, opencode-delegate, pi-delegate, computer-use, hermes-kanban-workflows]
---

# Development Orchestrator

Use this Skill as Kenan's entry point for work that may change code, tests, builds, migrations, developer tooling, generated runtime behavior, or product behavior. Watson is the user-facing name of the `default` Hermes profile; durable routing always uses `default`.

## Product routes

Before any development work or Card creation, Kenan chooses one route:

1. **Current interactive session** — no Card and no Harness-managed profile. The session acts only under the explicit one-off authorization.
2. **Direct Card** — one managed Card, no independent review lane.
3. **Two-stage Cards** — one `write-plan` Card followed by one parent-gated `execute-plan` Card; both use native in-card review.

Recommend direct only for bounded work without load-bearing architecture, persistence, migration, security, compatibility, release, broad coupling, or unresolved product decisions. Use two-stage for major, ambiguous, cross-module, or multi-part work. Investigation that disproves direct scope stops for reclassification instead of silently expanding.

## Layering

```text
L1 development-orchestrator      product policy and accepted intent
L2 development-workflow Harness  deterministic role, contract, evidence, and transition gates
L3 Hermes Kanban                 Card/run/claim/review/retry/dependency/notification truth
L4 external execution guard      write-Relay attempt/session/Git-landing lineage
L5 selected *-delegate adapter   Coding Agent transport
L6 external Coding Agent Skills  engineering internals
```

Kanban is the sole lifecycle truth. The Harness reads current facts, rejects known-invalid managed actions, and calls native primitives through one compatibility adapter; it does not copy lifecycle state. The external guard owns only write-mode Relay attempts, exact sessions, terminal results, Git baseline, and landing lineage. Git owns candidate commits. Artifacts own immutable evidence. A UI lease is only a machine-local resource lock.

Before any managed Card/guard action, load `hermes-kanban-workflows`. Never bypass a `devflow_*` managed tool with a native lifecycle call, raw SQLite, direct guard command, or Relay launcher.

## Session roles

The Harness derives role from runtime and current Kanban facts; a model cannot self-declare it.

- **Origin** — interactive `default` profile, no Dispatcher task/run environment, and an orchestrator-capable surface. It converges intent, creates/finalizes stages, records accepted decisions/amendments/manual verdicts, inspects, and explicitly unblocks. It never starts a managed Relay, lands a candidate, submits review evidence, or operates a Worker's UI lease.
- **Implement Worker** — current task/run/claim all match Kanban, run is active, and `claimed.source_status != review`. It starts/attaches/consumes the write Relay, runs engineering closure, freezes candidates, performs required UI acceptance, lands under authority, and hands off through `devflow_implement_handoff`.
- **Review Worker** — current task/run/claim match, run is active, `claimed.source_status == review`, and the latest handoff is the current candidate's `review_requested`. It starts one fresh read-only review Relay and ends through `devflow_review_verdict`.
- **Non-owning Worker** — task/run/claim mismatch or a terminal run. It may only inspect/read/exit. It cannot write files, comment, operate Terminal/Relay/Guard/Git/UI, message externally, or transition Kanban. The Harness disables stop-nudge in that old process so it can exit without touching the current run.
- **Unmanaged** — ordinary work outside a managed development Card.

`stale` is a Kanban-native outcome, never a synonym for non-owning. Dispatcher alone detects/reclaims stale workers.

## Managed Card contract (`development-stage.v2`)

```yaml
---
schema: development-stage.v2
feature_id: <stable-kebab-case-id>
stage: direct | write-plan | execute-plan
intent: draft | converged
ui_acceptance: pending | required | not-required
manual_acceptance: []
coding_agent: pi | cursor | codex | opencode
accepted_plan: null
---
```

For a converged execute stage:

```yaml
accepted_plan:
  card_id: <write-plan-card-id>
  path: <absolute-plan-path>
  sha256: <64-lowercase-hex>
```

The body has exactly these level-one sections in order:

1. `# Goal`
2. `# Observable acceptance`
3. `# Included scope`
4. `# Non-goals`
5. `# Settled decisions`
6. `# Open decisions`
7. `# Repository grounding`
8. `# Authority boundaries`

Goal, Observable acceptance, Included scope, and Authority boundaries must be substantive. A converged Card has `Open decisions` exactly `None`, a resolved UI classification, and a supported adapter. Direct/write-plan use `accepted_plan: null`; execute requires a readable, non-empty, SHA-matching Plan handed off by the same feature's write-plan Card. `manual_acceptance` is non-empty only when UI is required.

Do not store derived Skill/mode/review fields in the Card. Policy derives them from stage and adapter:

| stage | implement Skill | review Skill | review lane | UI owner | Auto Handoff |
|---|---|---|---|---|---|
| direct | `delegate-work` | none | no | Implement Worker, conditional | no |
| write-plan | `write-plan` | `review-plan` | yes | none | no |
| execute-plan | `execute-plan` | `review-execute-candidate` | yes | Implement Worker, conditional | required |

Feature identity is the literal `feature_id`; a parent edge is only a dependency. Per board, at most one non-archived Card may exist for one `feature_id + stage`.

## Intent and stage release

Before creation settle only the problem, coarse impact, and route. Then:

- `devflow_create_feature(route=direct|two-stage)` creates draft Card(s) in `triage`. Two-stage creation is atomic and immediately links write-plan as execute's parent; execute remains in triage even if its parent later completes.
- During convergence, `devflow_record_decision(kind=intent-decision)` appends sourced decisions. There is no duplicate editable draft state and no `devflow_update_draft`.
- `devflow_inspect` combines body and accepted decision comments. When intent is complete, Origin calls `devflow_finalize_stage` with one complete replacement v2 body.
- For two-stage, finalize only write-plan first. After its PASS handoff, read exact Plan path/SHA/card id, fold them into execute's `accepted_plan`, then finalize execute. Native parent gating promotes it when ready.
- Product behavior, scope, compatibility, migration, persistence, permission, security, or authority changes after dispatch return to Origin as `devflow_record_decision(kind=amendment)`. Ordinary implementation choices remain with the Coding Agent. If an amendment invalidates the accepted Plan, block execution and rebuild/review the stage chain.

A same-scope retry reuses the Card. A scope-changing replacement keeps `feature_id`, creates and correctly parents the replacement, then archives the old Card with a `superseded by <id>` comment. Historical done bodies are immutable.

Before releasing trusted-directory work, read back both `kanban.max_in_progress=1` and `kanban.max_in_progress_per_profile=1`; two-stage also requires `kanban.review_dispatch=true`.

## Pi commissioning policy

| stage | implement model | review model | rounds |
|---|---|---|---|
| direct | `zai-coding-cn/glm-5.3` | none | — |
| write-plan | `kimi-coding/k3`, one fallback to `zai-coding-cn/glm-5.3` only for real quota/provider failure | `zai-coding-cn/glm-5.3` | ≤3 |
| execute-plan | same implement policy | `zai-coding-cn/glm-5.3` | ≤3 |

All run with high thinking. Direct, grounding, and review relays have no fallback. The Harness policy registry chooses Skill, mode, model, thinking, resume, Auto Handoff, and output namespace; model parameters do not override it.

Every brief starts `Use the <skill> Skill (discovered from the global Skill root).` Direct uses `delegate-work`; the stage/review Skills own their internal `delegate-work` discipline. Implement relays are write-mode. Reviews are fresh and read-only, never resume implementation, never use the write guard, and forbid the parent and every child from writing or invoking write-access children.

Execute/rework must pass the exact accepted Plan through `--auto-handoff-plan`. Before guard reservation, validate Plan path/SHA, extension root, adapter capability, out dir, and launcher option. At terminal validate `result.autoHandoff.enabled`, exact `planFile`, `<out-dir>/auto-handoff` handoffDir, and resolved extension root. Missing capability blocks; never silently degrade.

See `references/coding-agent-commissioning.md` for exact brief contracts.

## Implement Worker flow

```text
devflow_inspect
→ devflow_start_or_inspect_relay
→ validate terminal delegate-relay.result.v1 and stage output
→ engineering checks
→ direct/execute: check current run, create local Card-trailer candidate commit
→ required UI/manual acceptance against that exact candidate
→ authorized push only after UI PASS
→ recheck run/candidate
→ devflow_implement_handoff
```

Write-plan hands off exact Plan path/SHA. Direct and execute create an immutable candidate manifest binding board/card/feature/run/attempt, candidate commit, diff base/head, accepted Plan identity, terminal Relay/session, and evidence hashes. A new candidate or Plan SHA invalidates old evidence without deleting it.

Writable Pi must not commit or push. If it does, stop for attribution/recovery. Landing uses `Kanban-Task: <card-id>` and the guard's v2 landing lineage. UI failure stays with implementation: resume the exact session, create a new attempt and new local candidate, then rerun failed scenarios and necessary regression.

`devflow_implement_handoff` performs validation and the native transition atomically:

- direct → native complete;
- write-plan → native request review;
- execute-plan → native request review.

Do not call `kanban_complete` or `kanban_request_review` directly for a managed v2 Card.

## Review Worker flow

```text
devflow_inspect
→ one fresh read-only `review-plan` or `review-execute-candidate` Relay
→ validate run-scoped result and evidence identity
→ devflow_review_verdict(pass | revise | blocked)
```

`review-execute-candidate` reviews one frozen commit range and emits independent `patch_gate` and `plan_conformance_gate` results plus `overall`. Either sub-gate FAIL forces REVISE. The Review Worker verifies any existing UI/manual PASS evidence belongs to the same candidate/Plan; it does not drive the renderer again.

`devflow_review_verdict` maps exactly one terminal action: PASS→native complete, REVISE→native request changes with findings reference, BLOCKED→genuine typed block. Review round is derived from native history. Do not begin round 4 without Kenan's explicit authorization and a materially revised candidate.

## UI acceptance

Required UI acceptance belongs to the Implement Worker after candidate commit and before push/handoff. Engineering tests never replace a real renderer. Acquire the named resource with `devflow_ui_lease`, generate evidence while the run-bound lease is valid, and always release/record cleanup. Review only validates evidence binding.

If deterministic scenarios pass but `manual_acceptance` remains, persist a candidate-bound checklist and block `needs_input`. Origin records Kenan's PASS/FAIL through `devflow_record_decision(kind=manual-verdict)` and explicitly unblocks. A fresh Implement Worker revalidates candidate/Plan before continuing; FAIL resumes exact-session rework.

Use `references/behavior-acceptance.md` and the application-specific acceptance Skill.

## Recovery and authority

Fresh sessions rebuild from persistent facts, not old chats:

- Origin: board + task id (or feature id) → `devflow_inspect`.
- Implement: current Kanban run/claim → accepted decisions → Guard v2 → terminal result → Git landings/candidate → UI/manual evidence.
- Review: current `review_requested` handoff → frozen candidate/Plan → run-scoped review result.

Guard live means attach; terminal means consume; uncertain means typed block. Only same-scope implement rework resumes the exact Coding Agent session. No general force exists. A narrowly approved zero-side-effect uncertain recovery remains Origin-only and can never authorize a non-owning Worker or override live/ambiguous write risk.

Do not commit, push, create PRs, tag, release, deploy, publish, alter versions, or perform irreversible actions without the applicable authority. Standing plugin-main CI authorization does not cover website production, tags, PRs, releases, or deployments.

## Migration

New Cards use v2. Running/completed `development-stage.v1` Cards retain legacy inspect/transition compatibility until terminal; unfinalized legacy drafts may finalize as full v2. Guard v1 migrates in place on the first exclusive managed write with an atomic backup and lossless mapping to one attempt and optional landing. Failure to migrate is `HARNESS_INCOMPATIBLE`, never a reset.

## Invariants

- One direct Card, or one write-plan + execute-plan pair; retries, Relay attempts, review rounds, and evidence are not Cards.
- Managed v2 creation/finalization/Relay/UI/handoff/verdict use `devflow_*` tools.
- Current run/claim ownership is checked immediately before every managed side effect.
- Review is one fresh read-only Relay per stage/round; execute uses the merged review Skill.
- Required UI acceptance occurs once, on the Implement Worker, against the frozen current candidate.
- No Goal Mode, auto-decompose, monitor, per-Card Cron, phase database, generic workflow DSL, or Core patch.

## References

| Situation | Load |
|---|---|
| Coding Agent commissioning | `references/coding-agent-commissioning.md` |
| Real-renderer UI acceptance | `references/behavior-acceptance.md` |
| Managed Kanban/Harness/guard mechanics | `hermes-kanban-workflows` |
| Coding Agent transport | exactly one selected `*-delegate` adapter |
