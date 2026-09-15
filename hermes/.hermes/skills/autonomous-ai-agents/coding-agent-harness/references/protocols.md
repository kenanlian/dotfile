# Coding Agent Harness protocols

Runtime validators in `src/contracts.mjs` are authoritative. JSON Schema files document the same field sets. This note mirrors contracts C2–C12.

## C2 Job (`coding-agent.job.v1`)

Every object is `additionalProperties: false`. The caller must supply identity, workspace, adapter/profile/model/thinking/session, permissions, inputs with hashes, expected output, verification, and limits. The Harness does not guess defaults. Stage/profile/permission/output/session/input-cardinality must match the stage matrix in `SKILL.md`. `verification` is allowed only on `implement` (optional) and `direct_implement` (required, non-empty). Reviewer Jobs require `sessionId: null`. SHA-1 or SHA-256 is accepted only for `expectedHead`; content digests are SHA-256. `direct_implement` inputs are exactly one `requirement` and no plan. Do not reuse the `implement` / `implementation.v1` contract for direct mode.

## C3 Stage submit payloads

- `plan.v1` via `submit_plan`: graph uniqueness, acyclic `dependsOn`, coverage, and repo-relative paths. `completed` requires non-empty R/C/WP/V and empty blockers; `blocked` requires blockers.
- `plan-review.v1` via `submit_plan_review`: `approved` has no blocking findings; `request_changes`/`blocked` require at least one.
- `implementation.v1` via `submit_implementation`: work-package ids are checked against the canonical plan. Touched files and checks are host-authored, not part of this payload.
- `direct-implementation.v1` via `submit_direct_implementation`: exact keys `schema`, `outcome`, `summary`, `residualRisks`, `blockingIssues`. `completed` requires `blockingIssues=[]`; `blocked` requires a non-empty list. No Plan artifact.
- `execute-review.v1` via `submit_execute_review`: repo-relative `file` paths, `line >= 0`, same verdict/finding rules.

## C4 Canonical Artifacts

Successful submit tools become `coding-agent.artifact.v1` JSON with host-bound job/session/input/workspace identity wrapping the model payload. Files are written with temp+rename. Plan Markdown is rendered one-way from the canonical payload (`canonical: false`) and is never parsed back into Plan JSON.

## C5 Result (`coding-agent.result.v1`)

Atomic `result.json` is the only terminal truth. `status` is transport/protocol. `error` is `null` or `{kind,message,details}`. Completed Results require identity and structured output. Deterministic check failures do not change `status`.

## C6 Pi relay generic output

Harness transport uses `--structured-output-tool`, `--structured-output-extension`, and `--structured-output-recovery` on `pi-delegate` `relay.mjs`. Legacy `--review-output` remains a compatible wrapper and must not be mixed with the generic flags. Scanner capture is exactly one successful `tool_execution_end.result.details` object. Any error result from the expected tool, including an earlier failed call followed by a later success, returns `structuredOutput: null` plus a typed diagnostic. The extension root is validated as an absolute path on the raw CLI value before resolve.

## C7 Exact session and bounded recovery

Fresh Jobs omit `--session`. Non-null `sessionId` is passed verbatim and a completed relay must explicitly report the same session; a missing or different session is `session_mismatch`. Missing expected-tool output may recover once on the same session with only the submit tool. Duplicate/error/invalid output is not recovered. Failed/timed-out/aborted/unavailable transport is not retried by the Harness.

## C8 Workspace and permission guard

Preflight: git top-level, symbolic branch, HEAD, optional clean tree, input hashes, verification cwd realpath containment, and out-dir outside the repo. Out-dir is created only after lexical plus nearest-existing-parent realpath checks pass; a rejected inside-repo path must not create files in the repository. Snapshots hash dirty/untracked path type/mode/content plus porcelain XY/rename/copy metadata so index-only mutations are visible. Postflight: branch and HEAD must be unchanged; read-only stages require empty `touchedFiles`. Violations leave the tree as-is.

## C9 Deterministic checks

Only after a valid `submit_implementation` or `submit_direct_implementation`. Sequential `spawn(argv, {shell:false})`. Per-check stdout/stderr files. One failure does not skip later checks. Transport `status` stays `completed`.

## C10 Events

`events.jsonl` uses `coding-agent.event.v1` with monotonic `seq`. Allowed types: `run_started`, `agent_session_started`, `heartbeat`, `stage_message`, `agent_tool_started`, `agent_tool_finished`, `artifact_written`, `check_started`, `check_finished`, `agent_settled`, `run_finished`. Heartbeats are host-timed. `run_finished` is written before Result publish. Events are not a workflow driver.

## C11 Idempotency / out-dir ownership

The caller maps `idempotencyKey` to a stable out-dir. First run `O_EXCL`s `run.lock` (`pid`, `startedAt`, `jobId`, `jobSha256`, `outDir`) and stores canonical `job.json` + `job.sha256`. Matching hash + valid Result replays without starting Pi. Different hash is `idempotency_conflict`. Lock without Result is `run_in_progress` (exit 75) and is not silently deleted. Successful publish deletes the lock.

## C12 No prose fallback

The Harness never `JSON.parse`s final messages, extracts JSON/YAML/fences, or reverse-parses `plan.md` into a canonical Plan.
