# Coding Agent Commissioning

`development-orchestrator` owns product policy, Card topology, lifecycle, acceptance, landing, and verdict mapping. The selected transport adapter owns exact CLI syntax, permissions, fresh/resumed Pi Session mechanics, process/result capture, and truthful Relay artifacts. Pi Skills own engineering internals.

Workers commission only the public entry Skill named by the Card. They do not reconstruct that Skill's internal delegation, persistence, or review protocol.

## Rules shared by every relay

1. Begin the brief with `Use the <skill> Skill (discovered from the global Skill root).`
2. Pass the exact Card/Plan/diff inputs named below; do not paste Skill text.
3. State the write boundary and all prohibited external actions.
4. Require a terminal top-level outcome, exact verification evidence, changed-file scope, artifacts, and limitations.
5. A streamed fragment or final prose without a terminal `delegate-relay.result.v1` is not completion.

## Direct implement relay

Start one fresh `--write` Pi parent using `delegate-work`. A direct Card never enters the native review lane.

```text
Use the delegate-work Skill (discovered from the global Skill root).

Implement this bounded direct Card in the current repository.

<Card Goal, Observable acceptance, Included scope, Non-goals,
Settled decisions, UI classification, and Authority boundaries>

Inspect before editing; preserve unrelated work. Own implementation, internal delegation,
focused and integration verification, and a renderer-ready handoff when UI acceptance is
required. Return top-level outcome, exact commands and observed results, changed files,
artifacts, and limitations. Do not commit, push, open a PR, release, deploy, publish,
change versions, or perform unauthorized external effects.
```

If broader coupling or a load-bearing decision appears, stop and return evidence so the Origin can reclassify the feature into stage Cards.

## Write-plan implement relay

Start a fresh Planning Parent with `--write`; never pass an Origin/discussion Session ID. Rework after `kanban_request_changes` resumes this exact Planning Session.

```text
Use the write-plan Skill (discovered from the global Skill root).

Create a self-contained execution Plan from this converged development-stage.v1 write-plan Card.
<Card Goal, Observable acceptance, Included scope, Non-goals,
Settled decisions, UI contract, and Authority boundaries>

Outer native Card review owns final plan review. Skip the Pi-internal review-plan cycle,
create no .dev/plan-review directory, and report `skip: outer review gate`.
Re-verify repository facts. Return the exact Plan path and SHA-256, top-level planning
outcome, artifacts, unresolved decisions, and limitations. Do not implement product code,
commit, push, or perform external effects.
```

The Implement Worker validates the terminal result, exact Plan path, and SHA; commits only the artifacts repository under its convention; then requests review with `reviewer="default"`.

## Execute-plan implement relay

Start a fresh Execution Parent with `--write` and the exact accepted Plan path/SHA; never reuse Planning or Origin Sessions. Rework after review/UI failure resumes this exact Execution Session.

```text
Use the execute-plan Skill (discovered from the global Skill root).

Plan file: <absolute accepted Plan path>
Plan SHA-256: <accepted digest>
Execute the Plan through completion while preserving unrelated work and Card authority.

Outer native Card review owns final patch and plan-conformance review. Skip the
Pi-internal post-execution review cycle, create no .dev/review directory, and report
`skip: outer review gate`.

Return implementation outcome, exact verification commands and observed results,
changed files, renderer build/install/reload steps when UI acceptance is required,
artifacts, deviations, and limitations. Do not commit, push, open a PR, release,
deploy, publish, change versions, or perform unauthorized external effects.
```

## Review relays

Every Review Worker starts fresh Pi Sessions with `--read-only`; it never resumes an implement Session and never uses the write-mode external guard. For Card review round `N`, use `development-artifacts/<board>/tasks/<card-id>/reviews/round-N/run-<kanban-run-id>/<review-skill>/` and its own `result.json`; validate process exit plus `delegate-relay.result.v1`. A replacement review run never reuses the prior run's directory.

`--read-only` restricts only the top-level Pi tools; `delegate_agent` remains available. Every review brief must include:

```text
You and every delegated child are source/worktree read-only. Do not edit files, create
audit artifacts, run builds/tests, invoke write-access children, commit, push, or perform
external effects. Return the complete standalone review in the final response.
```

Do not provide `Raw Review Artifact`; native Card runs/comments are the outer review record.

### Write-plan review

Use `review-plan` with the exact Plan path/SHA, repository root/HEAD, intended behavior, and Card review round. The Plan is mutable only in the later implement rework run.

### Execute-plan reviews

Run two fresh relays and aggregate them:

1. `review-patch`: exact `diff_base`, committed `diff_head`, repository root, intended behavior, implementation handoff, and UI-acceptance evidence when present.
2. `review-plan-conformance`: exact Plan path/SHA plus the same commit range, implementation handoff, and UI-acceptance evidence when present.

Normalize their native verdicts under `development-orchestrator`; do not blindly forward a Pi verdict.

## Rework

A fresh Implement Worker resumes the exact recorded Planning/Execution Session with only the finding or UI-failure delta and stable artifact pointers. It never replaces a resumable Session. Continuity loss is a `needs_input` decision before any fresh replacement.

## Terminal result boundary

A valid handoff contains:

- terminal status and process-exit truth;
- exact Pi Session identity;
- requested/resolved model, thinking, and mode;
- final message and changed-file snapshot;
- load-bearing artifact paths;
- top-level workflow outcome, skipped outer-owned gates, unresolved decisions, and limitations.

The Worker advances only when the adapter result is `status: completed`, `exitCode: 0`, and all stage-required fields are present and unambiguous. Other terminal statuses are evidence to reconcile or block, never permission to continue. If the writable Pi process committed or pushed despite the brief, treat it as a boundary violation and stop for attribution/recovery.
