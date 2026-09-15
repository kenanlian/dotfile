---
name: coding-agent-harness
description: Run coding-agent Jobs via Pi; write Result, not workflow.
license: MIT
compatibility: Requires Node 18+, git, and the Pi CLI 0.85.1 with the bundled stage-submit extension.
metadata:
  version: 0.1.0
  hermes:
    related_skills: [pi-delegate]
---

# Coding Agent Harness

Execute one `coding-agent.job.v1` through the Pi adapter and persist host-authored `coding-agent.result.v1`, canonical Artifacts, and an event stream. This Skill is an execution protocol, not a Workflow, Kanban adapter, or product-acceptance authority. It does not commit, push, open a PR, tag, release, or deploy.

## When to Use

Load when a caller already has a fully explicit Job file (absolute paths, hashes, profile, permissions, expected output) and needs a terminal Result. Do not use this Skill to decide the next Kanban state, retry budget, or whether to rework.

## CLI

```bash
node <this-skill>/scripts/harness.mjs \
  run \
  --job /absolute/job.json \
  --out-dir /absolute/run-dir
```

`run`, `--job`, and `--out-dir` are required. Both paths must be absolute. `--out-dir` must not be inside `workspace.repoRoot`; the Harness checks containment before creating the directory. stdout is a one-line summary plus the Result path; consumers read `result.json`, never stdout.

Exit codes: `0` completed, `1` other failure, `2` CLI/ownership conflict, `75` run in progress, `124` timed out, `127` unavailable, `130` aborted.

## Stage matrix

| stage | profile | permission | output | session |
|---|---|---|---|---|
| `plan` | planner | read-only | `plan.v1` via `submit_plan` | fresh or exact resume |
| `plan_review` | plan-reviewer | read-only | `plan-review.v1` via `submit_plan_review` | Job must be fresh |
| `implement` | implementer | write | `implementation.v1` via `submit_implementation` | fresh or exact resume |
| `execute_review` | execute-reviewer | read-only | `execute-review.v1` via `submit_execute_review` | Job must be fresh |

Each run exposes exactly one submit tool. Semantic results come only from that tool's native `details`. Final message text is diagnostic only.

## Artifact tree

```text
<out-dir>/
  job.json
  job.sha256
  result.json
  events.jsonl
  artifacts/plan-attempt-<N>.json
  artifacts/plan-attempt-<N>.md          # human-readable; not canonical
  artifacts/plan-review-attempt-<N>.json
  artifacts/implementation-attempt-<N>.json
  artifacts/execute-review-attempt-<N>.json
  adapter/primary/
  adapter/output-recovery/               # at most one missing-output recovery
```

## Status and errors

`status` is transport/protocol terminal state: `completed | failed | timed_out | aborted | unavailable`. Review verdicts and plan/implementation outcomes live in `structuredOutput.payload`. Deterministic check failures stay in `checks` and do not flip transport status.

Typed `error.kind` values include `invalid_job`, `idempotency_conflict`, `run_in_progress`, `workspace_mismatch`, `input_hash_mismatch`, `permission_mismatch`, `adapter_unavailable`, `adapter_failed`, `agent_not_settled`, `session_mismatch`, `structured_output_missing`, `structured_output_duplicate`, `structured_output_invalid`, `read_only_violation`, `artifact_write_failed`, `aborted`, and `timed_out`.

## Resume and recovery

Planner/Implementer Jobs may set `agent.sessionId` to resume one exact Pi session. A mismatched session fails closed. Reviewer Jobs must be fresh (`sessionId: null`). If the first completed relay never called the expected submit tool, the Harness issues at most one same-session output-only recovery. Duplicate, error, or invalid payloads are not recovered.

## Permissions

Read-only stages use the relay read-only allowlist plus the stage submit tool. Implementer runs `--write`. Read-only is not an OS sandbox: delegated children might still write. The Harness fail-closes on net workspace change, HEAD/branch drift, and never stash/reset/revert.

## Boundary

See [references/protocols.md](references/protocols.md) for Job/Result/Artifact contracts. Do not parse `final.txt`, Markdown, or YAML as protocol.
