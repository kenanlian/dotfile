# Dispatch and poll

`scripts/relay.mjs` wraps `opencode run --format json --auto`, captures the event stream, exports the finished session via `opencode session export`, and writes `delegate-relay.result.v1` artifacts. Verified against OpenCode v2.0.29.

## Permission posture

Full permissions by design: the relay always passes `--auto` and injects no deny rules, for read-only and writing tasks alike. Read-only-ness lives in the brief ("do not modify files") and relies on model instruction-following; `touchedFiles` + git diff review is the post-hoc check. This is not an OS sandbox — OpenCode has none on this machine. If a task cannot tolerate a stray write, do not route it through this relay.

## Before the first run

```text
command -v opencode
opencode --version
opencode auth list
opencode models
```

v2 model facts:

- A bare `opencode run` without `--model` resolves to the opencode-go default and **403s without an active Go subscription** — pass `--model` explicitly every time.
- Variant is inline (`--model provider/model#variant`); the standalone `--variant` CLI flag no longer exists, so the relay composes `--model` + `--variant` into one token.
- `opencode export` is gone → `opencode session export <id>`.

## Dispatching

```text
node "<skill-dir>/scripts/relay.mjs" --brief brief.txt --cd /path/to/repo --model provider/model
```

The prompt travels through stdin. `--session` and `--resume-last` are mutually exclusive; prefer the exact `sessionId` from a prior `result.json` over `--resume-last` ("last" is scoped to the project context, not to your dispatch).

## Artifacts

- `brief.txt` — exact prompt.
- `events.jsonl` — raw `opencode run --format json` stdout (JSONL; `text`, `step_start`, `step_finish`, `tool_use`, `error` events).
- `final.txt` — final assistant message (from the session export, falling back to the last streamed text event).
- `stderr.txt` — complete stderr.
- `session.json` — parsed `opencode session export` output; v2 assistant messages carry `type: 'assistant'`, `content: [{type:'text',text}]`, `model: {id, providerID, variant}`, `agent`, `tokens`, `cost` directly on the message.
- `result.json` — atomically published result contract.

## Result fields that matter

- `status`: `completed` | `failed` | `timeout` | `aborted` | `unavailable` (missing binary; `sourceStatus: opencode_unavailable`).
- `sessionId`: exact resume key.
- `requestedModel`/`requestedVariant` vs `resolvedModel`/`resolvedVariant`/`resolvedAgent` (from the export).
- `permissionMode: full-auto`, `effectiveAgent` (default `build`).
- `finalMessage`, `usage`, `touchedFiles`, `exportError`, `stderrTail`, `error`.

## Waiting for completion

The relay blocks. For long tasks run it via `terminal(background=true)` and poll `result.json`'s existence plus terminal `status`. Completion requires child exit AND `result.json`; a streamed text fragment or an idle-looking event is not completion.

A usage error exits 2 before artifact creation. A missing binary exits 127 with `status: unavailable`.

## Failure handling

- `failed`: inspect `error`, `stderrTail`, `events.jsonl`. Common v2 causes: provider auth (Go subscription 403), invalid model id, resuming a session created in a different project context.
- `timeout`: watchdog SIGTERM → SIGKILL after grace. Preserve the working tree and inspect.
- `aborted`: relay killed (SIGTERM/INT/HUP); OpenCode was terminated with it.
- Empty `finalMessage` with exit 0: inspect `session.json`/`events.jsonl`; do not treat a zero exit as behavior acceptance.
- `exportError`: the run itself may be fine; continuity is still possible from `sessionId`.
- **Question masquerading as completion**: a clarifying question lands in `finalMessage` with `status: completed`, exit 0. Read `finalMessage` before treating a run as done; answer via `--session` resume or escalate to the user.

## Exact resume

```text
node relay.mjs --brief delta.txt --cd /path/to/repo --session <sessionId> --model provider/model
```

Send only the delta prompt — the child retains full prior context. Preserve discussion sessions separately from execution sessions.

## Smoke verification (executed 2026-10-14, OpenCode v2.0.29, glm-5.3)

1. Fresh run expecting exact token → `completed`, exact `finalMessage`, non-empty `sessionId`, matching `resolvedModel`. ✓
2. Resume the exact session asking what it replied last time → recalled the prior token. ✓
3. Read-only via brief wording only → no writes occurred. ✓
4. Write task → file created with exact content under `--auto`. ✓
