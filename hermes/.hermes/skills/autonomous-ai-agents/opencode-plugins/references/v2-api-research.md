# OpenCode V2 API Research — Plugins, Compaction, Revert, Auto-Handoff Design

Researched 2026-09-02 (sources: opencode.ai/v2/docs/build/plugins, /v2/docs/compaction, /v2/docs/snapshots, /v2/docs/api/session/*, SDK source github.com/anomalyco/opencode, issues #10017/#11314, PR #10123). Session: OpenCode auto-handoff plugin design discussion with 柯楠 (design agreed, implementation deferred).

## V2 plugin system (beta)

- Load: files under `.opencode/plugins/` auto-load; or a `plugins` array in `opencode.json(c)` — package names, paths, or `{"package": ..., "options": {...}}` with options read via `ctx.options` in setup.
- Shape: `import { Plugin } from "@opencode-ai/plugin"; export default Plugin.define({ id, async setup(ctx) { ... return () => cleanup } })`.
- `ctx` is "essentially an OpenCode server client" plus transforms/hooks/storage.
- Capability map (verified from docs):
  - `ctx.session`: `create/get/context/switchAgent/switchModel/prompt/generate/command/synthetic/interrupt/rename/wait`. NO revert in the documented list.
  - `ctx.session.hook("context", event => ...)`: pre-dispatch, mutable `system: SystemPart[]`, `messages: Message[]`, `tools`, `generation` (maxTokens/temperature/…), `providerOptions`. Runs per model call (including tool-driven continuations), NOT for title/compaction requests. Changes affect only the outgoing call.
  - `ctx.session.hook("prompt")`: mutable admission draft (`prompt.text/files/agents/skills`, `metadata`, `delivery` "steer"|"queue"); runs once at admission. Retry-safe caveats apply (not exactly-once).
  - Other hooks: `model.request`, `http.request`, `http.response`, `retry` (mutable `{retry, delay}` decision), `ctx.tool.hook("execute.before"/"execute.after")`, `ctx.shell.hook("create.before")`, `ctx.permission.hook("evaluate")`.
  - `ctx.agent.transform` / `ctx.catalog.transform` / `ctx.command.transform` (+ `reload()`): ordered composable transforms; command executors get sessionID/prompt/delivery.
  - `ctx.event.subscribe({ signal })`: AsyncIterable<OpenCodeEvent> over the public stream.
  - `ctx.storage`: plugin KV store (`set/get/remove/scan`).
  - Publish: package plugin needs `"type": "module"`, `exports` (`.`, optional `./rpc`), dep `@opencode-ai/plugin: "beta"`.

## Built-in compaction (V2)

- Trigger: preflight estimate (JSON-serialized request, ~4 chars/token) > context limit − max(output tokens, buffer=20000). Also one compact+retry on provider overflow per step.
- Summary: session's current model, tools disabled, HARDCODED 4096 output-token cap; framed as historical context, explicitly NOT new instructions. `keep.tokens` (default 15000) keeps a serialized recent tail (tool outputs capped at 2000 chars). Later compactions update the previous summary and carry forward its tail.
- Limits that motivated the custom plugin: triggers near the limit (too late for quality/cost); 4k summary cap loses long-task detail; in-place compaction never resets prompt cache → long sessions stay slow/expensive.
- Custom thresholds: PR #10123 (`token_threshold`, `context_threshold`, `min_messages`, per-model `models` overrides) UNMERGED as of 2026-09. Config keys `threshold`/`strategy`/`preserveRecentMessages`/`preserveSystemPrompt`/`auto`/`prune` (beyond documented V2 keys) do nothing on stable releases.

## Session revert / snapshots (V2)

- `POST /api/session/{id}/revert/stage` — stage/move a revert boundary at a message or part; optionally applies file changes. `POST /api/session/{id}/revert/clear` — unstage. `DELETE /api/session/{id}` deletes session+children (not what we want). TUI `/undo` is built on staged revert; TUI `/clear` = `/new` alias only.
- Source (`packages/*/src/session/revert.ts`): revert computes the boundary, reverts file patches after it (snapshot-backed), publishes diff events; `cleanup` removes messages/parts after the boundary from the projection. Snapshots docs: "Committing a revert removes messages from the active projection, not from durable session history or existing snapshot storage."
- 409 SessionBusyError while the session runs → idle-only. For handoff: skip file restoration (code must survive); only the conversation projection clears.

## Auto-handoff plugin design (agreed with 柯楠, NOT implemented)

Requirements he fixed across two clarifications:
1. Dual trigger: context estimate > threshold (e.g. 50%) AND a work-package boundary just completed (e.g. WP 3/6 done) — threshold is necessary, WP boundary is the timing. WP state from machine-readable markers in `.dev/plan/<slug>-plan.md` (his development-artifacts persistence system). Hard ceiling (~75%) force-triggers with a "wrap up current WP and persist" instruction as backstop (a single WP can otherwise eat the remaining window).
2. Handoff is NOT built-in compaction: custom injected prompt controls exactly what is kept; final artifact = concise state + pointers to persisted files in `.dev`. The CURRENT model writes the handoff as its final turn (full context available, lands in git history); plugin only does timing/injection/verification/continuation.
3. Fully automatic continuation, on the condition that the OpenCode process stays reachable by Hermes (PID unchanged) when Hermes-started (relay contract keys on pid + session_id + events.jsonl).
4. Old session archived (revert satisfies this: durable history retained).

Chosen architecture ("Path A′"): same process, same session_id → wait idle → `revert.stage` clears active projection → inject opener ("read `.dev/handoff.md` + plan, continue from WP N+1"). PID/session_id/events.jsonl/resume.yaml all unaffected.

Rejected ("Path B", real `session.create`+`prompt`): `opencode run` is one-shot per session — new session has no in-process driver; resume.yaml session_id breaks; would need resident server mode + notifying Hermes. Fits TUI use only.

Fallback if plugins can't reach revert ("Path A"): per-call `context`-hook message rewriting + plugin-side token accounting; costs: storage keeps growing (compaction estimator can diverge), every model call needs rewriting.

## Spike checklist (before implementation)
1. Can a V2 plugin call revert at all (ctx method undocumented, HTTP to in-process server, or `--attach`)?
2. After revert: does the next `context` hook see only the new opener, and does auto-compaction accounting reset?
3. Reliable idle/turn-end signal from `ctx.event.subscribe` for boundary timing.
4. Token estimation inside the `context` hook (chars/4 vs provider usage) — accuracy determines threshold calibration.
