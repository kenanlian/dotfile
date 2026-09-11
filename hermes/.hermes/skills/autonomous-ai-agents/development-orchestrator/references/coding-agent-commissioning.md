# Coding Agent Commissioning

`development-orchestrator` owns product policy. The Development Workflow Harness derives the stage operation, Skill, mode, model, thinking, resume rule, Plan identity, Auto Handoff, and output namespace from the current `development-stage.v2` Card and run. The selected transport adapter owns exact CLI syntax and terminal Relay artifacts. Pi Skills own engineering internals.

A Worker calls `devflow_start_or_inspect_relay`; it does not launch adapters or the external guard directly. Do not reconstruct a target Skill's internal delegation or persistence protocol.

## Shared rules

1. Every brief starts `Use the <skill> Skill (discovered from the global Skill root).`
2. Pass exact Card/Plan/candidate inputs and stable artifact pointers; do not paste Skill text.
3. State source/write boundaries and all prohibited external effects.
4. Require terminal outcome, exact verification evidence, changed-file scope, artifacts, and limitations.
5. A fragment or prose self-report without terminal `delegate-relay.result.v1` is not completion.
6. Writable Pi may edit only authorized scope and must not commit/push. Every reviewer and delegated child is source/worktree read-only and must not invoke a write-access child.

## Direct implement

Fresh write-mode Pi parent, `delegate-work`, `zai-coding-cn/glm-5.3`, high thinking, no fallback, no Auto Handoff:

```text
/skill:delegate-work 

Implement this bounded direct development-stage.v2 Card in the exact repository.
<Card Goal, Observable acceptance, Included scope, Non-goals,
Settled decisions, UI classification, and Authority boundaries>

Inspect before editing; preserve unrelated work. Own todo decomposition, bounded internal
delegation, implementation, focused/integration verification, and a renderer-ready handoff
when UI acceptance is required. Return outcome, commands and observed results, changed files,
artifacts, and limitations. Do not commit, push, open a PR, release, deploy, publish, change
versions, or perform unauthorized external effects.
```

Broader coupling or a load-bearing product decision stops for Origin reclassification.

## Write-plan implement

Fresh write-mode Planning parent, primary `kimi-coding/k3` and one `zai-coding-cn/glm-5.3` fallback only for real quota/provider unavailability, high thinking. Never reuse an Origin session or pass Auto Handoff. Same-scope rework resumes the exact Planning session.

```text
/skill:write-plan 

Create a self-contained execution Plan from this converged development-stage.v2 write-plan Card.
<Card Goal, Observable acceptance, Included scope, Non-goals,
Settled decisions, UI contract, and Authority boundaries>

Outer native Card review owns final plan review. Skip the Pi-internal review-plan cycle,
create no .dev/plan-review directory, and report `skip: outer review gate`.
Re-verify repository facts. Return the exact Plan path and SHA-256, top-level planning outcome,
artifacts, unresolved decisions, and limitations. Do not implement product code, commit, push,
or perform external effects.
```

The Harness validates the terminal result and exact Plan identity before `devflow_implement_handoff` requests review.

## Execute-plan implement

Fresh write-mode Execution parent, same model policy as write-plan, high thinking, exact accepted Plan path/SHA, and mandatory `--auto-handoff-plan <absolute-plan-path>`. Never reuse Planning or Origin sessions. Same-scope rework resumes the exact Execution session and re-passes the same accepted Plan.

```text
/skill:execute-plan 

Plan file: <absolute accepted Plan path>
Plan SHA-256: <accepted digest>
Execute the Plan through completion while preserving unrelated work and Card authority.

Outer native Card review owns final merged patch/plan-conformance review. Skip the
Pi-internal post-execution review cycle, create no .dev/review directory, and report
`skip: outer review gate`.

Return implementation outcome, exact verification commands and observed results, changed
files, renderer build/install/reload steps when UI acceptance is required, artifacts,
deviations, and limitations. Do not commit, push, open a PR, release, deploy, publish,
change versions, or perform unauthorized external effects.
```

Before guard reservation the Harness verifies Plan SHA, adapter option, Auto Handoff extension root, and output paths. At terminal it verifies the result's exact Auto Handoff identity.

## Review relays

Every Review Worker uses one fresh `--read-only` Pi session under `zai-coding-cn/glm-5.3`, high thinking, no fallback, no implement session, no write guard, and no Auto Handoff. For round `N` use:

```text
~/Secret-Projects/development-artifacts/<board>/tasks/<card-id>/
  reviews/round-<N>/run-<kanban-run-id>/<review-skill>/
```

Every review brief includes:

```text
You and every delegated child are source/worktree read-only. Do not edit files, create
workspace audit artifacts, run builds/tests or state-changing commands, invoke write-access
children, commit, push, or perform external effects. Return the complete standalone review
in the final response.
```

The run-scoped adapter directory is control-plane evidence, not a reviewer-authored workspace artifact. Review workers pass the brief inline via `brief_content` (they have no write tools); the harness validates it, persists it to `<run-dir>/brief.md` for the evidence chain, and spawns the Relay. `devflow_start_or_inspect_relay` waits up to 1800 seconds by default and consumes a terminal result in the same call. If it returns `attach`, heartbeat once and invoke it again with `wait_seconds=1800`; never busy-poll event/result files. `wait_seconds=0` is reserved for immediate diagnostic inspection.

### Write-plan review

Use `/skill:review-plan ` as the brief's first line (same trailing-space rule as implement briefs) with exact Plan path/SHA, repository root/HEAD, intended behavior, Card/run identity, and review round.

### Execute-plan review

Run exactly one `review-execute-candidate` Relay with the first line `/skill:review-execute-candidate `. Pass exact board/card/feature, review run/round, repository, `diff_base`, committed `diff_head`/candidate, accepted Plan path/SHA, intended behavior, implementation handoff, and current candidate-bound UI/manual evidence paths when present.

The Skill returns separate:

```yaml
patch_gate:
  verdict: pass | fail
  findings: []
plan_conformance_gate:
  verdict: pass | fail
  findings: []
overall:
  verdict: pass | revise | blocked
```

Either sub-gate failure forces `overall: revise`. The outer Review Worker validates identity and routes through `devflow_review_verdict`; it never blindly forwards prose.

## Rework

A fresh Implement Worker resumes the exact recorded Planning/Execution session with only the accepted findings or UI-failure delta plus stable artifact pointers. It never replaces a resumable session. Execute rework creates a new guard attempt and re-passes mandatory Auto Handoff. Lost continuity, changed product intent, or invalid Plan returns to Origin rather than guessing.

## Terminal result boundary

Advancement requires process exit plus a valid `delegate-relay.result.v1` with `status: completed`, `exitCode: 0`, expected CWD/mode/model/thinking/session, and stage-required output. Other terminal statuses, malformed evidence, unexpected commits/pushes, or missing capability are evidence to block/reconcile, never permission to continue.
