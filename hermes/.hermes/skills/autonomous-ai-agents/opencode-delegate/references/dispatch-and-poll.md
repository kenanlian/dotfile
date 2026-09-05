# Dispatch and poll

`scripts/relay.mjs` wraps `opencode run --format json`, captures the event stream, exports the finished session, and writes `delegate-relay.result.v1` artifacts.

## Before the first run

Use `terminal` to verify:

```text
command -v opencode
opencode --version
opencode auth list
opencode models
opencode agent list
```

OpenCode may list built-in free models even when `auth list` reports no provider credentials. Always select model IDs from the live `opencode models` output.

## Dispatching

```text
node "<skill-dir>/scripts/relay.mjs" --brief brief.txt --cd /path/to/repo
```

| Flag | Effect |
| --- | --- |
| `--brief <file>` | Brief path; omit to read stdin. |
| `--cd <dir>` | Working root and child cwd. |
| `--read-only` | Default: `plan` Agent and injected deny rules for edit, bash, and external-directory access. |
| `--write` | `build` Agent and `--auto`; explicit writable transition. |
| `--model <provider/model>` | Outer model. Validate through `opencode models`. |
| `--variant <level>` | Provider-specific reasoning variant. |
| `--agent <name>` | Primary Agent override. Permission mode still controls injected denies and `--auto`. |
| `--session <id>` | Resume the exact `sessionId` from a prior result. |
| `--resume-last` | Resume the latest OpenCode session; exact ID is safer. |
| `--timeout <dur>` | Optional Relay watchdog, off by default. |
| `--out-dir <dir>` | Artifact directory; defaults under system temp. |

The prompt travels through stdin. `--session` and `--resume-last` are mutually exclusive.

## Permission modes

### Read-only

The Relay selects the `plan` Agent unless `--agent` overrides it, then merges these process-level OpenCode permissions after inherited `OPENCODE_PERMISSION` values:

```json
{
  "edit": "deny",
  "bash": "deny",
  "external_directory": "deny"
}
```

This blocks OpenCode's edit and shell tools during repository discussion. OpenCode may still retain narrowly scoped internal access to its own tool-output directory. Note: relay runs no longer pass `--pure` — curated OpenCode plugins may load; keep the plugin set minimal and reviewed.

### Writable

`--write` selects `build` unless overridden and passes `--auto`. Existing explicit deny rules remain denials, while permission requests that are not denied can be approved automatically. Treat this as full trusted-repository write authority, not as an OS sandbox.

OpenCode has no generic CLI sandbox equivalent to Codex's `workspace-write`. Do not claim otherwise. The Relay itself never commits, but it cannot technically prevent every command spelling that an authorized OpenCode shell could run; the brief and controlling workflow must prohibit commit, push, PR, release, publish, and deploy actions.

## Artifacts and result fields

Artifacts default outside the repository:

- `brief.txt` — exact prompt.
- `events.jsonl` — raw `opencode run --format json` stdout.
- `final.txt` — newest assistant turn's text.
- `stderr.txt` — complete stderr.
- `session.json` — parsed `opencode export <sessionId>` output when export succeeds.
- `result.json` — atomically published result contract.

Important result fields:

- `status`: `completed` | `failed` | `timeout` | `aborted` | `opencode_unavailable`.
- `exitCode`, `signal`, `opencodeVersion`, timestamps, and artifact paths.
- `sessionId`: exact session for `--session` resume.
- `requestedModel`, `requestedVariant`, `requestedAgent` and exported `resolvedModel`, `resolvedVariant`, `resolvedAgent`.
- `readOnly`, `permissionMode` (`read-only` or `writable-auto`), `effectiveAgent`, and `pure` (always `false` since 2026-09: relay no longer passes `--pure`, so curated plugins can load).
- `usage`: exported token and cost data, falling back to the last `step_finish` event.
- `finalMessage`: newest assistant turn from the session export, falling back to the newest streamed text event.
- `touchedFiles`: final `git status --porcelain` under `--cd`; it includes pre-existing dirt and is not attribution.
- `exportError`: present when the run completed but session export failed.
- `stderrTail` and `error`: failure diagnostics.

## Waiting for completion

The Relay blocks. Run it as a background process for long tasks. Completion requires both child-process exit and a terminal `result.json` status. A text event alone is not completion.

A usage error exits `2` before artifact creation. A missing binary exits `127` and writes `status: opencode_unavailable` after the brief has validated and the output directory exists.

## Failure handling

- `opencode_unavailable`: install OpenCode and verify PATH.
- `failed`: inspect `error`, `stderrTail`, and `events.jsonl`; common causes are provider/auth errors, invalid model or variant, a missing session, or a permission denial.
- `timeout`: the Relay sent SIGTERM and then SIGKILL after a grace period. Preserve and inspect the working tree.
- `aborted`: the Relay received SIGTERM, SIGINT, or SIGHUP and forwarded termination to OpenCode. Preserve artifacts and inspect before resuming.
- Empty `finalMessage`: inspect `session.json` and events; do not treat a zero exit with no requested deliverable as behavior acceptance.
- `exportError`: continuity may still be possible from `sessionId`; verify with `opencode export <id>` before claiming the exported metadata.

## Exact resume

Resume with only the delta prompt:

```text
node relay.mjs --brief delta.txt --cd /path/to/repo --session <sessionId> --read-only
```

Do not pass `--resume-last` together with `--session`. Preserve the discussion/planning session separately from the fresh execution session.

## Verification

For a read-only smoke test:

1. Create a clean temporary Git repository.
2. Dispatch a brief requesting one exact response with `--read-only` and a model from `opencode models`.
3. Require exit `0`, `status: completed`, expected `finalMessage`, non-empty `sessionId`, matching `resolvedModel`, and `touchedFiles: []`.
4. Resume the exact session and require the second expected response.
5. Ask the read-only session to modify a file; require the working tree to remain clean even if OpenCode explains the denial.

For writable verification, use a disposable Git repository and an explicit `--write` run. Confirm the requested file change appears in `touchedFiles`, then delete the disposable repository. Never use a real project as the first writable smoke test.
