---
name: coding-agent-harness
description: Run coding-agent Jobs via Pi or Cursor; write Result, not workflow.
license: MIT
compatibility: Requires Node 18+, git, and either the Pi CLI 0.85.1 with the bundled stage-submit extension (adapter pi) or the Cursor Agent CLI with cursor-delegate (adapter cursor).
metadata:
  version: 0.1.0
  hermes:
    related_skills: [pi-delegate, cursor-delegate]
---

# Coding Agent Harness

Execute one `coding-agent.job.v1` through the Pi or Cursor adapter and persist host-authored `coding-agent.result.v1`, canonical Artifacts, and an event stream. This Skill is an execution protocol, not a Workflow, Kanban adapter, or product-acceptance authority. It does not commit, push, open a PR, tag, release, or deploy.

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

## Adapters (pi | cursor)

Dispatch reads `job.agent.adapter`. `"cursor"` runs `runCursorAdapter` via the sibling `cursor-delegate` relay (default `../cursor-delegate/scripts/relay.mjs`; override `CODING_AGENT_CURSOR_RELAY_PATH`). `"pi"` keeps the existing `runPiAdapter` path unchanged. The Result records `adapter` from the Job that actually ran. `resolvedModel` is `null` or the CLI-resolved non-empty model string; new Results always write it (Pi from the relay `resolvedModel`, Cursor from the stream init/model); `validateResult` tolerates absence so pre-change `result.json` files still replay.

### Models and thinking

- Pi: `agent.model` is provider-qualified `provider/model` (SAFE_MODEL charset plus a mandatory slash). `--thinking` is passed through.
- Cursor: `agent.model` is a slug `^[A-Za-z0-9][A-Za-z0-9._:-]*$` (no whitespace, no slash). `agent.thinking` is still validated against the shared thinking levels for both adapters; on Cursor it is audit-only and no thinking flag is passed (effort lives in the slug).

### Skills, subagents, Auto Handoff, compaction

- Pi: explicit Skill mounting from `stage-profiles.json` (`-ns` plus `--skill` per directory) and a `/skill:<inline> ` first-line prefix. Unchanged.
- Cursor: native global/project Skill discovery only. The brief's first line invokes the stage entry token (`/write-plan`, `/review-plan`, `/execute-plan`, `/review-execute-candidate`; `direct_implement` has none). The harness does not pass `--no-skills` or `--skill`, does not apply a whitelist or allowlist, and does not precisely mount Skill paths. That difference is real: Cursor Skill loading is discovery-only, not a filtered mount list.
- Cursor-internal delegation uses Cursor-native Subagents. There is no `delegate_agent` port.
- Auto Handoff is Pi `implement` only (`--auto-handoff-plan`). Cursor runs never load it, including `direct_implement`.
- Cursor long-context relies on native compaction plus persistent artifacts. The harness does not configure, expose, or claim a compaction ratio or threshold.

### Structured output

- Pi: the stage-submit extension tool. Capture is exactly one successful `tool_execution_end` and the tool uses terminate semantics.
- Cursor: a run-scoped Stage Submit Bridge MCP server (zero-dependency stdio, loaded via `--plugin-dir` with the Agent Plugin layout `plugin.json` + `mcp.json`). Exactly one registered tool per stage. Binding `{jobId, jobSha256, stage, expectedTool, runNonce, phase, submitDir}`. O_EXCL attempt receipts (`coding-agent.submit-attempt.v1`) under `<out-dir>/adapter/<phase>/submit/`. Host-side reconciliation precedence: duplicate > invalid > ok > missing. No `terminate:true` — the harness waits for relay exit and receipts are the protocol fact. Host `validatePayload` stays authoritative. Final message / Markdown / YAML / fences are never parsed.

### Transport, sessions, events, resources

Cursor relay flags the harness sets: `--brief`, `--cd`, `--out-dir`, `--read-only` or `--force`, `--model`, `--session` (maps to `agent --resume`), `--plugin-dir` (repeatable), `--timeout`. Status mapping: relay `timeout` → `timed_out`; `completed` / `failed` / `aborted` / `unavailable` 1:1. `CURSOR_AGENT_BIN` is a test/CI hook. Spawn audit `{argv, envKeys}` (names only). `--sandbox` is never set by the harness.

Session and recovery rules match Pi: exact-session resume; reviewer stages fresh; missing (0 attempts) on a completed run with a session → exactly one same-session output-only recovery (`--read-only` regardless of stage, fresh nonce and submit dir); duplicate/invalid never recovered; timeout/abort/unavailable/failed never retried.

Events: `createCursorEventNormalizer` projects stream-json (`agent_session_started` once, `stage_message`, `agent_tool_started` / `agent_tool_finished`, `agent_settled`; unknown/malformed lines increment `diagnostics.ignored`). Raw `events.jsonl` is preserved verbatim.

Run-scoped plugin dir, config, and receipts live under the harness out-dir (already repo-external by containment). Nothing writes user-global Cursor config.

Real-CLI smoke (scenarios A/B/C PASS on Cursor CLI 2026.09.15) used a `SMOKE_SUPPRESS` marker file in the primary submit dir because the CLI sanitizes MCP-server child environments. That marker is a smoke-only note, not production protocol.

## Stage matrix

| stage | agent profile | stage profile | permission | output | session |
|---|---|---|---|---|---|
| `plan` | planner | `plan` | read-only | `plan.v1` via `submit_plan` | fresh or exact resume |
| `plan_review` | plan-reviewer | `plan-review` | read-only | `plan-review.v1` via `submit_plan_review` | Job must be fresh |
| `implement` | implementer | `implement-plan` | write | `implementation.v1` via `submit_implementation` | fresh or exact resume |
| `direct_implement` | implementer | `implement-direct` | write | `direct-implementation.v1` via `submit_direct_implementation` | fresh or exact resume |
| `execute_review` | execute-reviewer | `execute-review` | read-only | `execute-review.v1` via `submit_execute_review` | Job must be fresh |

Each run exposes exactly one submit tool. Semantic results come only from that tool: Pi captures exactly one successful `tool_execution_end` `details` object; Cursor records Stage Submit Bridge receipts and classifies them host-side. Final message text is diagnostic only. The `plan` / `plan-review` / `implement-plan` / `execute-review` / `implement-direct` names are stage-profile ids from `stage-profiles.json` (Pi); they are not the Job `agent.profile` field. Cursor briefs invoke a first-line entry token instead of those Pi profile flags (`/write-plan`, `/review-plan`, `/execute-plan`, `/review-execute-candidate`; `direct_implement` has none).

## Stage profiles

This section applies to `adapter: pi`. Cursor does not use `stage-profiles.json` for Skill mounting, extension roots, or tool allowlists.

Pi extensions, Skill invocation, tool allowlists, and child env are assembled from declarative data in [`stage-profiles.json`](stage-profiles.json) (`schema: coding-agent.stage-profiles.v1`). The Harness does not branch on stage names when building relay argv: `src/stage-profiles.mjs` (`loadProfiles`, `resolveStageProfile`) returns a normalized `{extensionRoots, skills, env, toolsExtra, disabledEntries, expectedExtensionIds}`.

- **Location**: `<this-skill>/stage-profiles.json`.
- **Fields**: `profiles.<id>.extensions[]` (`id`, `enabled`, optional `root` / `rootEnv` / `rootDefault` / `channel` / `note`), `profiles.<id>.skills` (`mode`, `paths`, optional `inline`), `profiles.<id>.toolsExtra` (optional string array), and `profiles.<id>.env` (string values). `stageToProfile` maps each Job stage to a profile id.
- **`skills.mode`**: `explicit` (built-in profiles) is all-or-nothing — relay emits `-ns` plus one `--skill` per resolved directory. `auto` is a compatibility value: neither flag is added and Pi's default discovery stays on. Unknown mode, a missing path, or a directory without `SKILL.md` fail-fast (same typed-error shape as a missing extension root).
- **`skills.paths`**: relative to the agent_skills repo root (`PI_AGENT_SKILLS_ROOT`, else realpath of `~/.pi/agent/skills` then its parent, else `~/Secret-Projects/agent_skills`). Entries look like `skills/write-plan` (the directory that contains `SKILL.md`). Resolved to absolute paths before they reach the relay.
- **`skills.inline`**: optional basename of one `paths` entry. The Harness brief's first line becomes `/skill:<inline> ` (name, same-line trailing space, then newline — the shape Pi and the relay `validateSkillPrefix` require). Pi inlines that one Skill into the first user message. Only one Skill is inlined per run; the others stay mounted via `--skill` (visible in `<available_skills>` unless they carry `disable-model-invocation: true`). A name that is not in `paths` fail-fasts. Omit `inline` when there is no hidden primary workflow Skill — `direct_implement` only mounts `delegate-work`, which has no hide flag and is already in the available list.
- **`toolsExtra`**: optional extra names the relay appends onto the child `--tools` allowlist via `--extra-tools`. Every built-in Pi stage loads `pi-web-access` and lists `web_search` plus `fetch_content`; `implement-direct` additionally lists `todo` for `todos-tool`. **Extension-registered tools must be listed here or Pi's `-t` whitelist silently drops them.** `-t` applies to extension tools the same as builtins; Pi 0.85.1 ignores unknown names with no error, and the relay `WRITE_TOOLS` / `READ_ONLY_TOOLS` lists do not include third-party names. Recovery turns ignore `toolsExtra` (allowlist is the submit tool only). Invalid names fail-fast. Listing a name on `-t` is still not a load proof — that requires a successful tool call or an attestation event.
- **pi-web-access** is explicitly mounted in every built-in Pi stage from `PI_WEB_ACCESS_ROOT`, falling back to `~/.pi/agent/npm/node_modules/pi-web-access`; installation in Pi's package list alone is insufficient because relay children run with `--no-extensions`.
- **stage-submit** is inherent (every run loads `extensions/stage-submit` via `--structured-output-extension`) and is not listed in the JSON.
- **`enabled: false`**: not mounted, root not existence-checked, but recorded in `adapter/<phase>/spawn-record.json` `disabledEntries` as a forward placeholder.
- **auto-handoff** uses relay `--auto-handoff-plan` (plan-file semantics) rather than generic `--extension`. Generic enabled roots use `--extension`.
- **Fail-fast**: unknown stage, unknown profile id, an enabled extension whose resolved root does not exist, or an explicit Skill path that is missing / has no `SKILL.md` — typed error, no silent fallback. Process-level differences do **not** use `PI_CODING_AGENT_DIR`.

Built-in Skill assignment (`skills.paths` names under `skills/`):

| stage | profile | Skills | inline |
|---|---|---|---|
| `plan` | `plan` | write-plan, delegate-work | write-plan |
| `plan_review` | `plan-review` | review-plan, delegate-work | review-plan |
| `implement` | `implement-plan` | execute-plan, delegate-work, audit-persistence | execute-plan |
| `execute_review` | `execute-review` | review-execute-candidate, delegate-work | review-execute-candidate |
| `direct_implement` | `implement-direct` | delegate-work | — |

Harness briefs name each mounted Skill with its SKILL.md **absolute path** (the path source for hidden `disable-model-invocation` Skills that never appear in `<available_skills>` — a bare name otherwise degrades to path-guessing). The submit-tool schema remains the report channel. When `skills.inline` is set, `compileBrief` prepends `/skill:<inline> ` so Pi expands that Skill into the first message. Skills with `disable-model-invocation: true` stay hidden from `<available_skills>` even when `--skill`-mounted; the inline first line is how those primary workflow Skills actually load.

### Adding a profile

1. Add a record under `profiles` and a `stageToProfile` mapping.
2. Add or extend a golden assertion in `tests/stage-profiles.test.mjs` (the file already walks every stage; a new enabled extension or Skill path is picked up from the JSON). Builder/validator code does not need a stage branch.

### Three-layer validation

1. **Golden test (static)**: `tests/stage-profiles.test.mjs` composes `buildRelayArgs()` with relay `assembleChildInvocation()` / `buildArgv()` and asserts the final pi argv/env against the manifest, including `-ns` and the exact `--skill` path set for every explicit profile. Every built-in Pi stage must mount `pi-web-access` and expose `web_search` plus `fetch_content`; `direct_implement` must not contain auto-handoff traces and additionally exposes `todo`; `implement` must mount auto-handoff. `mode=auto` must emit neither Skill flag.
2. **Runtime attestation (fail-closed)**: stage-submit writes a grep-stable JSON line on `session_start` (`"harnessAttestation": {"expected":[...],"version":"coding-agent.attestation.v1"}`). After a completed relay (`agent_settled`), the Harness checks that the record exists in `adapter/<phase>/events.jsonl` and matches the profile, and that pi argv is consistent. Missing or mismatched → Job fails with typed error `extension_manifest_mismatch` and does not continue to artifacts/checks/recovery. v1 only proves stage-submit ran plus argv consistency; it does **not** attest Skills (argv golden tests cover Skill flags) or that a `toolsExtra` name actually registered. Pi 0.85.1 silently ignores unknown `-t` names, so allowlist membership is not a load proof.
3. **Audit**: relay `result.json` `spawn: { argv, envKeys }` (env **values** are never persisted). The Harness copies the same facts plus profile identity to `adapter/<phase>/spawn-record.json`.

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
  artifacts/direct-implementation-attempt-<N>.json
  artifacts/execute-review-attempt-<N>.json
  adapter/primary/
    spawn-record.json                # argv + injected env key names (no values)
    submit-bridge/                   # Cursor: plugin.json + mcp.json + config.json
    submit/                          # Cursor: O_EXCL attempt receipts
  adapter/output-recovery/               # at most one missing-output recovery
    submit-bridge/
    submit/
```

## Status and errors

`status` is transport/protocol terminal state: `completed | failed | timed_out | aborted | unavailable`. Review verdicts and plan/implementation outcomes live in `structuredOutput.payload`. Deterministic check failures stay in `checks` and do not flip transport status.

Typed `error.kind` values include `invalid_job`, `idempotency_conflict`, `run_in_progress`, `workspace_mismatch`, `input_hash_mismatch`, `permission_mismatch`, `adapter_unavailable`, `adapter_failed`, `agent_not_settled`, `session_mismatch`, `structured_output_missing`, `structured_output_duplicate`, `structured_output_invalid`, `read_only_violation`, `artifact_write_failed`, `extension_manifest_mismatch`, `aborted`, and `timed_out`.

## Resume and recovery

Planner/Implementer Jobs may set `agent.sessionId` to resume one exact adapter session. A completed resume must report that same session; a missing or different session is `session_mismatch`. Reviewer Jobs must be fresh (`sessionId: null`). If the first completed relay never produced expected submit output (Pi: no successful `tool_execution_end`; Cursor: 0 attempt receipts), the Harness issues at most one same-session output-only recovery (`--read-only` regardless of stage; Cursor uses a fresh nonce and submit dir). Duplicate, error, or invalid payloads are not recovered. `run.lock` records `pid`, `startedAt`, `jobId`, `jobSha256`, and `outDir` so a supervisor can distinguish a live process from an orphan lock; the Harness does not delete an orphan lock and retry in place.

## Permissions

Read-only stages use the relay read-only posture (Pi: tool allowlist plus the stage submit tool; Cursor: `--read-only` / plan mode). Implementer runs `--write` on Pi and `--force` on Cursor. Read-only is not an OS sandbox: delegated children might still write. The Harness fail-closes on net workspace change, HEAD/branch drift, and never stash/reset/revert.

## Boundary

See [references/protocols.md](references/protocols.md) for Job/Result/Artifact contracts. Do not parse `final.txt`, Markdown, or YAML as protocol.
