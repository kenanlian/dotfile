# Managed Development Handoff Integrity

Use when a managed development stage submits a Plan, candidate, Review verdict, UI/manual evidence, or terminal Coding Agent result. The Harness validates identity and calls the native Kanban transition in the same `devflow_implement_handoff` or `devflow_review_verdict` operation.

## Terminal Relay truth

A Relay is terminal only after process exit and a valid `delegate-relay.result.v1` at the exact expected path. Success requires:

- expected schema, `status: completed`, and `exitCode: 0`;
- expected repository CWD, mode, requested/resolved model, thinking, and fresh/resumed session rule;
- exact Pi session identity;
- expected output namespace and unchanged authority boundary;
- stage-required final output;
- execute/rework: exact enabled Auto Handoff Plan/handoff-dir/extension identity.

`failed`, `timeout`, `aborted`, and `unavailable` are terminal evidence but not successful handoffs. A result-looking file while the process is live, malformed/missing fields, or an unexpected writable-Pi commit/push fails closed.

Write-mode terminal truth is recorded on the current Guard v2 attempt. Read-only Review truth belongs to the current native review run's unique result directory.

## Write-plan handoff

Require exact:

- board/card/feature/stage and producing implement run;
- same-feature write-plan identity;
- absolute readable non-empty Plan path;
- 64-lowercase-hex SHA-256 matching current bytes;
- terminal Planning Relay/session;
- absence of unresolved product decisions.

PASS hands these fields to the native review lane. The later execute body must copy `{card_id,path,sha256}` exactly; a parent edge alone is not Plan identity.

## Candidate manifest

Direct/execute handoff uses an immutable manifest under:

```text
~/Secret-Projects/development-artifacts/<board>/tasks/<card-id>/
  candidates/<candidate-sha>/candidate.json
```

It binds schema, board/card/feature/stage, producing implement run, guard attempt number, candidate commit, diff base/head, accepted Plan identity, terminal Relay/session, and artifact hashes. The commit must resolve, equal `diff_head`, descend from the expected base, and contain exact `Kanban-Task: <card-id>` trailer. Current repository/candidate is rechecked immediately before transition.

## Review evidence

Write-plan uses one `review-plan`. Execute uses one `review-execute-candidate` with independently populated patch and plan-conformance gates. Evidence binds board/card/feature, review run/round, candidate/diff, accepted Plan SHA, source handoff, Relay/session, result path, and content SHA.

Either execute sub-gate failure forces REVISE. `overall: pass` is insufficient when a gate or identity is missing. A result from a reclaimed/prior run cannot satisfy the current verdict.

## UI/manual evidence

When UI is required, PASS evidence must bind the same candidate/diff/accepted Plan and producing implement run, and must prove it was created during a valid named UI lease with cleanup recorded. Review validates it but does not rerun the renderer.

Manual verdict is an Origin-authored append-only decision bound to the current candidate and accepted Plan. Pending, FAIL, or stale identity cannot pass.

Any new candidate commit, Plan SHA, feature/stage, or producing run invalidates old completion eligibility without deleting history.

## Native payloads and attachments

The managed wrapper prepares compact native handoff metadata; callers do not manually reconstruct it. Keep structured metadata under a dedicated nested key and file attachments in the native top-level `artifacts` argument so path arrays do not collide with result objects. After transition, read back the exact Card/event/run metadata and attachment list.

## Checklist

- [ ] Current task/run/claim and role still own this action.
- [ ] Relay process exited and exact terminal result validates.
- [ ] Plan or candidate identity matches current bytes/Git.
- [ ] Candidate trailer, diff range, Guard attempt, and landing agree.
- [ ] Review round/run and every gate belong to this candidate/Plan.
- [ ] Required UI/manual evidence is current and PASS; lease/cleanup validate.
- [ ] Transition uses the matching `devflow_*` wrapper and expected run.
- [ ] Exact native status/event/handoff/attachments read back successfully.
- [ ] No unrelated board, repository, config, release, or publication side effect occurred.
