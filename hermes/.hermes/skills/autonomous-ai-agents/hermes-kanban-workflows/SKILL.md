---
name: hermes-kanban-workflows
description: "Use when building or verifying Hermes Kanban workflows."
version: 4.0.0
tags: [kanban, multi-agent, dispatcher, relay, external-guard, workflow, verification]
---

# Hermes Kanban Workflows

Implement durable Kanban and Development Workflow Harness mechanics. Product route and acceptance policy come from `development-orchestrator`; this Skill must not redefine them.

## Ownership

Hermes Kanban is the only Card/run/claim/status/dependency/review/retry/heartbeat/stale-reclaim/handoff/comment/notification truth. The standalone `development-workflow` plugin reads that truth, validates managed actions, and invokes native primitives through one adapter; it does not copy lifecycle state. The external guard owns only write-mode Relay attempt/session/result, Git baseline, and landing lineage. Git owns candidate commits. Artifacts own immutable evidence. UI leases own short-lived local resource exclusion.

No Goal Mode, auto-decompose, monitor, scheduled workflow job, generic workflow DSL, or second phase database advances development Cards.

## Roles and ownership loss

The Harness derives role from runtime and current Kanban facts:

- Origin: interactive `default` profile without Dispatcher task/run env; creates/finalizes/records decisions/inspects/unblocks.
- Implement Worker: task, run, claim lock, active run, and `claimed.source_status != review` all match.
- Review Worker: the same ownership checks, `claimed.source_status == review`, and current `review_requested` candidate handoff.
- Non-owning Worker: any ownership mismatch or terminal run; inspect/read/exit only.

`stale`, `timed_out`, `crashed`, and `reclaimed` are distinct native outcomes. Ownership loss is `non-owning` / `RUN_OWNERSHIP_LOST` and never changes Kanban. A non-owning Worker cannot write comments/files, run Terminal/Relay/Guard/Git/UI, message externally, or transition a Card; its process-local stop nudge is disabled so it can exit normally.

## Managed Card mechanics

New development Cards use `development-stage.v2`. The body stores stable product identity only: feature/stage/intent/UI/manual/coding-agent/accepted-Plan plus the fixed eight sections. Skill, mode, review gate, Auto Handoff, and completion owner are derived by the Harness policy registry.

Use the Harness surface for managed Cards:

| Tool | Role | Purpose |
|---|---|---|
| `devflow_inspect` | any/read-only | Reconstruct role, Card pair, Plan, guard, candidate, gates, lease, allowed actions, remediation |
| `devflow_create_feature` | Origin | Create direct draft or atomic write-plan+execute-plan draft pair |
| `devflow_record_decision` | Origin | Append sourced intent decision, amendment, or candidate-bound manual verdict |
| `devflow_finalize_stage` | Origin | Validate full v2 replacement body/capabilities and call native specification |
| `devflow_start_or_inspect_relay` | owning Worker | Derive and launch/attach/consume the exact write or review Relay |
| `devflow_ui_lease` | Implement Worker | Acquire/release/inspect a candidate/run-bound named resource |
| `devflow_implement_handoff` | Implement Worker | Validate current Plan/candidate/checks/UI then native complete/request-review |
| `devflow_review_verdict` | Review Worker | Validate current review evidence then native complete/request-changes/block |

Do not use raw `kanban_create/link/finalize`, native lifecycle transitions, direct guard calls, or direct Relay launchers to bypass these tools on a managed v2 Card. The plugin's `pre_tool_call` hook is a safety net, not the preferred happy path. It blocks known bypasses, review writes, and non-owning mutations; internal failure returns `HARNESS_STATE_UNAVAILABLE` for protected actions while unrelated tools remain unaffected.

Legacy running/completed `development-stage.v1` and grandfathered `development-task.v1` cards retain narrow inspect/transition compatibility until terminal. New features never use them.

## Creation and release

- One direct route creates one triage draft.
- Two-stage creation creates both triage drafts and their parent edge in one outer transaction, then readbacks both identities and the edge before commit. Failure rolls back everything.
- Draft decisions are append-only comments. Finalization supplies one complete replacement body; no second draft store exists.
- Only write-plan is finalized initially. Execute remains triage until Origin folds the exact same-feature write-plan handoff `{card_id,path,sha256}` into its v2 body and finalizes it.
- Per board, one `feature_id + stage` has at most one non-archived Card.
- Read back `kanban.max_in_progress=1`, `kanban.max_in_progress_per_profile=1`, and for two-stage `kanban.review_dispatch=true` before release.

Native parent gates still own `todo→ready` promotion. The Harness never claims, dispatches, reclaims, retries, or sends notifications.

## Managed transitions

Native status effects remain:

- specification: `triage → todo|ready` after parent recomputation;
- dispatch claim: `ready|review → running`;
- direct implement handoff: `running → done`;
- stage implement handoff: `running → review` with default reviewer routing;
- review PASS: `running → done`;
- review REVISE: `running → ready|todo`, restoring implementer and parent gating without block-loop accounting;
- genuine blocker: `running → blocked`, typed `dependency|needs_input|capability|transient`;
- explicit Origin unblock: `blocked → todo|ready` by parent gating.

For managed v2 Cards these effects occur inside `devflow_implement_handoff` or `devflow_review_verdict`, bound to the expected current run. Never perform a separate preflight then manually copy parameters into a native transition.

## External guard v2

Canonical state:

```text
~/Secret-Projects/development-artifacts/<board>/tasks/<card-id>/external-execution.json
```

Schema `development-external-execution.v2` stores immutable baseline plus append-only `attempts[]` and `landings[]`. At most one attempt is non-terminal; attempt numbers increase; only terminal attempts can land; duplicate recording of one commit is idempotent while a new rework commit appends. It stores no Card status, review round, UI verdict, Plan acceptance, heartbeat, retry, or notification state.

The Harness validates ownership, brief, stage, Plan, adapter, Auto Handoff, argv, and paths **before** asking the guard to reserve. Outcomes remain `spawned|attach|terminal|uncertain` (`none` before an attempt). Uncertain always blocks; never reset or retry automatically.

Guard v1 migrates on the first exclusive write: atomic backup, lossless mapping to the first attempt and optional landing, full validation, then replacement. Migration failure returns `HARNESS_INCOMPATIBLE` and preserves evidence.

Load `references/execution-recovery.md` before any guard operation.

## Relay and review evidence

A completed-looking Relay is incomplete until the process exited and `delegate-relay.result.v1` validates. Write attempts belong to Guard v2. Reviews are fresh read-only processes under:

```text
.../reviews/round-<N>/run-<run-id>/<review-skill>/
```

One review run cannot reuse another run's result. A reclaimed read-only process may finish, but its verdict cannot satisfy the current run.

Write-plan review uses one `review-plan`. Execute review uses one `review-execute-candidate` with independent patch and plan-conformance gates. Review evidence binds board/card/feature/run/round/candidate/diff/accepted-Plan and artifact hashes. Any identity change invalidates it.

## Candidate and UI evidence

Direct/execute handoff requires a local candidate commit with exact `Kanban-Task: <card-id>` trailer and an immutable manifest under `candidates/<sha>/candidate.json`. It binds current implement run, guard attempt/terminal session, diff base/head, and accepted Plan. Candidate commits follow engineering checks and precede required UI acceptance. Push occurs only after current-candidate UI/manual PASS under applicable authority.

Automated UI acceptance runs under a named `devflow_ui_lease` and writes evidence under `ui/<candidate>/<run>/`. A live current owner blocks another holder. Reclaim requires dead PID and non-current run. Review validates current evidence; it does not drive the renderer.

## Recovery

`devflow_inspect` is the common recovery index:

- Worker with no args uses Dispatcher env.
- Origin notification uses exact board + task id.
- Known feature uses board + feature id.
- Board-only lookup returns bounded active candidates and never guesses among multiples.

Rebuild cheapest-first: Card/current run/claim/events → decisions/amendments → Guard v2 or current review result → accepted Plan → Git/candidate → UI/manual evidence → session history only if still ambiguous.

Write guard live means attach; terminal means consume; uncertain means typed block. Only same-scope rework resumes the exact implement session. Old Worker chats never regain ownership.

## Reconciliation and readback

After every external mutation, read back the exact target. Verify:

- board/task/workspace/assignee/body/status/event and parent edge;
- runtime role, current run, and claim lock immediately before side effects;
- Guard schema, baseline, monotonic attempt lineage, one active attempt, terminal session, and append-only landing;
- process exit and terminal Relay schema/status/CWD/mode/model/session/Auto Handoff identity;
- accepted Plan path/SHA and same-feature write-plan handoff;
- candidate trailer, manifest identity, diff range, and unchanged current HEAD at handoff;
- review/UI/manual evidence identity and verdict;
- the exact native transition and absence of unrelated board mutation.

See `references/kanban-mechanics.md`, `references/execution-recovery.md`, and `references/handoff-integrity.md`.

## Recovery authority

No general force exists. A zero-side-effect pre-spawn uncertain recovery is Origin-only, requires Kenan's explicit single-Card approval, and must prove no live PID, no result, unchanged artifacts, and clean attributable Git state before restoring a previously committed terminal state. It never authorizes a non-owning Worker or overrides live/ambiguous write risk.
