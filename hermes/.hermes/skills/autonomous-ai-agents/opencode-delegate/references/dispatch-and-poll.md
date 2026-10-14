# Dispatch and results

`scripts/relay.mjs` wraps `opencode run --format json --auto`, captures the event stream, exports the session through `opencode session export`, and writes `delegate-relay.result.v1` artifacts. Verified CLI shape: OpenCode v2.0.29. It does not depend on a custom backend router or reviewer/worker tiers.

## Permissions and preflight

The relay always passes `--auto` and adds no permission-deny rules. Ordinary read-only tasks are constrained in the brief, then checked against an initial working-tree baseline. Existing application/project denies still apply; auto-approval does not bypass them.

Use `terminal` to check `command -v opencode`, `opencode --version`, `opencode auth list`, and `opencode models`. Pass the selected model explicitly: bare `run` can select the subscription-gated Go provider. Variant is inline (`provider/model#variant`); the relay's convenience `--variant` composes the token. Session export is `opencode session export <id>`.

## Dispatch and exact resume

Use `terminal` with the installed skill path from `skill_view`:

```text
node <skill-dir>/scripts/relay.mjs --brief <brief-file> --cd <repo> --model provider/model --out-dir <artifact-dir>
node <skill-dir>/scripts/relay.mjs --brief <delta-file> --cd <repo> --session <sessionId> --model provider/model --out-dir <new-artifact-dir>
```

The prompt travels through stdin. `--session` and `--resume-last` are mutually exclusive; prefer the exact `sessionId` from a previous result. The latest session is project-scoped, not task-scoped.

Resume for a same-task follow-up; start fresh when scope or context calls for it. There is no development-stage separation requirement. Default primary agent is OpenCode's built-in `build`; ordinary CLI `--agent` selection is not custom backend routing.

Use a unique artifact directory per dispatch, outside the target working tree, under the Hermes scratch workspace or a durable task location. For long runs use `terminal(background=true, notify=true)`; consume the completion notification and read `result.json` with `read_file`.

## Artifacts and result contract

- `brief.txt`: exact prompt.
- `events.jsonl`: raw CLI stdout, including JSON text/step/tool/error events.
- `final.txt`: final assistant message from session export, falling back to the last streamed text event.
- `stderr.txt`: complete stderr.
- `session.json`: parsed session export. On v2, assistant messages contain `type`, text `content`, `model: {id, providerID, variant}`, and agent/token/cost fields.
- `result.json`: atomically published `delegate-relay.result.v1` contract.

Relevant fields:

- `status`: `completed`, `failed`, `timeout`, `aborted`, or `unavailable`; a missing binary has `sourceStatus: opencode_unavailable` and exit 127.
- `exitCode`, `signal`, `opencodeVersion`, `sessionId`: terminal information and exact resume identity.
- `requestedModel`, `requestedVariant`, `requestedAgent`, `resolvedModel`, `resolvedVariant`, `resolvedAgent`, `effectiveAgent`: requested/resolved selections; emitted values can be null if unavailable.
- `permissionMode: full-auto`: relay's requested auto-approval posture, not proof that existing denies are absent.
- `workdir`, `session`, `resumeLast`, `resumed`, `startedAt`, `finishedAt`: transport settings/timing.
- `finalMessage`, `usage`, `touchedFiles`, `exportError`, `stderrTail`, `error`: report and diagnostics when available.
- `briefPath`, `eventsPath`, `finalPath`, `stderrPath`, `exportPath`: artifact paths; optional files may have null paths.

`touchedFiles` is the final `git status --porcelain` snapshot under `--cd`, not attribution of child edits. It includes pre-existing dirty files and excludes committed changes. Capture a baseline and inspect Git diff/history too. Null means Git could not report, not a clean tree.

## Completion, authorization, and recovery

Completion requires process exit and a terminal result. A streamed fragment is not completion; argument/empty-brief errors exit 2 before creating artifacts. `completed` proves transport, not deliverable correctness.

The relay does no Git writes itself. Child Git/external actions require task authorization. There is no special commit-only stage, blanket publication ban, or assigned planning/review/acceptance roles in this adapter.

- `failed`: inspect error, stderr, events, and work. Check provider auth, exact model IDs, and session/project context.
- `timeout` or `aborted`: preserve partial work and artifacts; inspect before choosing resume/retry. Do not clean or start a replacement blindly.
- Empty final message with exit 0: inspect export/events; do not infer a successful deliverable.
- `exportError`: the run may have finished, but exported metadata is unverified. Continuity can remain possible using the emitted session ID.
- A clarifying question can look like transport completion: read the message. Answer via exact-session resume if known; otherwise ask the user.

## Smoke verification

1. Dispatch in an isolated scratch repository, requiring an exact reply token and no file/Git/external writes.
2. Require `completed`, exact final message, a non-empty session ID, and the requested resolved model.
3. Resume that exact session and ask it to recall the prior token; verify identity continuity and the expected reply.
4. Check the workspace stayed unchanged. This validates transport, not acceptance of an unrelated product task.
