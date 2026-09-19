# Operations

Operator procedures for the external autonomous development workflow plugin.
Commands assume the plugin is already on Hermes' discovery path.

**Not done in this milestone:** creating or cloning Hermes Profiles, running
`hermes profile` / `hermes plugins enable` / `hermes tools enable|disable`,
or a real Dispatcher Worker pass against Pi/models. A coordinator will
perform those steps separately. The procedures below are the intended
operations once that wiring exists.

## Enqueue

From the **control** profile, create a blocked card, bind a Manifest, copy the
requirement into an immutable Artifact, and publish only after Kanban
read-back:

```bash
hermes -p <control-profile> autodev enqueue \
  --board <board> \
  --repo /absolute/git/root \
  --title "Card title" \
  --requirement /absolute/requirement.md \
  --profile autodev
```

`--flow` is `full` or `direct` (default `full`). Direct mode also requires
`--verification /absolute/autodev.verification.v1.json` with a non-empty
`checks` array using Harness job-check fields. Full mode derives verification
from the approved Plan and must not pass `--verification`.

Templates:

- `full` → `autonomous-development.v1`: Plan → Plan Review → Implement → Verify → Execute Review → Product Acceptance.
- `direct` → `direct-implementation.v1`: Requirement → coding-agent implementation → host checks → Complete. No planner, reviewers, Hermes review lane, or product acceptance.

Rules:

- `--repo` must be the git root, on `main_branch`, with a clean worktree.
- The card is created `blocked`, then unblocked to `ready` (or left `todo` if
  a same-board predecessor is still active).
- Replay the same `--idempotency-key` to reuse a published card.
- The plugin does not start a Worker. Hermes Dispatcher claims `ready` cards.

Completion notifications: CLI enqueue carries no chat session, so unlike
in-chat `kanban_create` there is no automatic subscription. Pass
`--notify-platform <platform> --notify-chat-id <chat-id>` (both required
together) to subscribe a destination at publish time; optional
`--notify-chat-type`, `--notify-thread-id`, `--notify-user-id`,
`--notify-user-id-alt`, and `--notify-mode` (`notify` | `notify+wake` |
`wake`) refine delivery. The subscription is best-effort bookkeeping: a
failed subscribe never fails an already-published card, and replaying an
enqueue with notify flags heals a missing subscription. The result JSON
reports `notify_subscribed` (and `notify_error` on failure).

## Status

```bash
hermes -p <control-profile> autodev status --board <board> <task-id>
```

Prints the Manifest checkpoint (`templateId`, `flow`, `workflowStatus`, `revision`,
`nextAction`, `inProgress`, `pendingLifecycle`) plus the current Kanban status. It does not
advance the workflow or dispatch lifecycle tools.

Worker-side equivalent: `autodev_workflow_status` inside a claimed run.

## Human unblock and abandon

### Unblock a card waiting on a person

`needs_human` and external `blocked` verdicts call native `kanban_block`.
After the operator answers the question or clears the blocker:

```bash
hermes kanban --board <board> unblock <task-id>
```

Then let Dispatcher claim the card again. The Worker should call
`autodev_workflow_status` / `autodev_workflow_advance` (and typed acceptance
if the Manifest is still `product_acceptance`). Do not `kanban complete` by
hand on a Manifest-bound card.

### Abandon

Abandon is **operator-only**. It is not registered as a model tool.

```bash
hermes -p <control-profile> autodev abandon \
  --board <board> \
  <task-id> \
  --reason "why this card is stopping"
```

Effects:

- Refuses if a Harness process is still live.
- Records `abandonReason` on the Manifest and moves workflow status to
  `blocked`.
- Releases the repo lease (`reason=abandon`).
- Does not archive the Kanban card and does not rewrite serial successor
  edges. Unblock or retarget those cards separately if needed.

## Hermes update compatibility check

After upgrading Hermes, before enabling the plugin on a real board:

```bash
hermes plugins doctor \
  /Users/kenan/Secret-Projects/dotfile/hermes/.hermes/plugins/autonomous-development-workflow \
  --ci
hermes -p autodev plugins doctor autonomous-development-workflow --ci
hermes -p autodev plugins compat autonomous-development-workflow
hermes -p autodev plugins list
```

The plugin must keep using the documented plugin API only (register tools,
hooks, CLI, skills, `ctx.get_config`, `ctx.dispatch_tool`). Fail the upgrade
if doctor/compat report a break, or if discovery starts importing Hermes
private modules.

## Harness failure recovery

`doctor` is read-only. `reconcile` only applies recoveries that are already
idempotent: a pending lifecycle whose Kanban read-back already matches, or
consumption of an identity-matched terminal Result without launching a new
Harness.

```bash
hermes -p <control-profile> autodev doctor --board <board> <task-id>
hermes -p <control-profile> autodev reconcile --board <board> <task-id>
```

### Stale intake baselines and precondition failures

Cards queued behind an upstream card pin `baseline.head` at intake time.
When the upstream card commits, HEAD advances and the pinned baseline goes
stale. The controller therefore re-checks the baseline before every Job
creation: while the workflow has **no consumed Job yet**, a stale baseline
is refreshed to the repo's current HEAD/branch, so the queued card starts
against reality instead of failing preflight (`workspace_mismatch`). After
the first consumed Job the baseline is the relay contract between stages
(candidate changes travel uncommitted in the tree) and is never refreshed;
branch drift is also never absorbed.

A Harness **preflight** `workspace_mismatch` (status `failed`, error kind
`workspace_mismatch`, no adapter run) is classified as a **precondition
failure**, not a transport failure: it means an environment premise was not
met, so it blocks the card immediately (with `resumeStatus` preserved) for
operator triage and never counts toward `MAX_STAGE_TRANSPORT_FAILURES`.
Post-adapter workspace mismatches keep the transport classification.

### Resetting transport failure counts

When a card hits `transport_failure_limit`, the operator repair is:

```bash
hermes -p <control-profile> autodev reconcile \
  --board <board> <task-id> --reset-failures
```

It performs both required steps in one Manifest revision: clears
`runFailureCounts` and sets `activeJobId` to `null`. Clearing the counts
alone is not enough: the controller would re-derive an attempt-1/retry-0
Job identity that collides with already-consumed dead Jobs ("job document
identity conflict" in the run dir and the Job ledger) — the t_bf68d977
second blockage. The reset refuses while a Harness process is live, marks a
not-yet-consumed dead active Job as consumed, preserves all Job rows for
audit, and leaves `resumeStatus` intact so the card resumes at its prior
stage after `kanban unblock`.

Typical findings:

| Code | Meaning | What to do |
| --- | --- | --- |
| `orphan_lock` | `run.lock` exists, process identity does not | Do not delete the lock to force a rerun. Confirm the process is dead, then use an explicit recover/retry path or abandon. |
| `artifact_hash` | Artifact bytes drifted from the ledger | Stop. Restore or reject the candidate; do not advance. |
| `pending_lifecycle` | Native Kanban tool not applied yet | Reconcile from the bound Worker run, or finish that run so `pendingLifecycle.runId` matches. |
| `lane_mismatch` | Manifest vs Kanban lane | Inspect with `status`; do not invent a second task state. |
| `missing_manifest` | Ordinary Kanban card | Guard is a no-op; this plugin does not own the card. |

Transport failures create a new Job id and out-dir at the same business
attempt (`transport_retry + 1`) and do not increment plan/implement rework
counts. Result-before-checkpoint must not relaunch the same Job. A late
Result from an old run must not move a new run. Transport retries reuse the
Stage's frozen agent selection exactly like business rework. Preflight
`workspace_mismatch` Results are the exception: they are precondition
failures (see above) and never enter the transport-retry loop.

## Per-Stage agent routing and lineage constraints

`stage_agents` plugin config (see the plugin README) routes each Harness
Stage to `pi` or `cursor` with its own model/thinking. Operator-facing rules:

- The frozen per-Stage `{adapter, model, thinking}` lives in the Manifest
  (`stageAgents`) and survives restarts; `status`/`doctor`/`reconcile` never
  re-derive it from current config. A Manifest written before this field
  existed recovers the selection from the Stage's latest persisted Job
  document.
- Editing `stage_agents` (or `agents`) mid-run only affects Stages that have
  not created a Job yet.
- There is no automatic fallback or in-lineage adapter switch: a mismatched
  `result.adapter` is a protocol failure that blocks the card for operator
  triage instead of silently rerunning on the other adapter.
- To move a Stage to another adapter, abandon/complete the current card and
  enqueue a fresh lineage with the new config. Never paste a Cursor session
  id into a Pi job or the reverse; the controller binds sessions per Stage
  adapter.

## Unsupported in this MVP

- No git `commit`, `push`, or release/publish.
- No Dashboard or extra UI. Kanban + plugin CLI are the operator surfaces.
- No parallel cards on the same repo. Same-board successors stay `todo`
  until the predecessor leaves the active serial chain; the repo lease is
  held by the working card.
- No second Dispatcher, no forged Worker env, no parsing Coding Agent
  `final.txt` as protocol.
- No real Profile wiring or live Dispatcher E2E in this milestone (see the
  README).
