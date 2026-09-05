# OpenCode 1.18.25 Installed-Version Spike (2026-09-03)

Verified against the machine-local install (Homebrew `/opt/homebrew/Cellar/opencode/1.18.25`,
`@opencode-ai/plugin` 1.18.25, `@opencode-ai/sdk` 1.18.25) plus upstream GitHub tag `v1.18.25`
sources: `packages/core/src/plugin/promise.ts`, `packages/core/src/config/plugin/external.ts`,
`packages/opencode/src/plugin/index.ts`, `packages/schema/src/session-event.ts`.
Full write-up lives in `~/Secret-Projects/opencode-exit-guard/docs/spike-notes.md`.

## Plugin.define / default export

- Docs show `import { Plugin } from "@opencode-ai/plugin"` then `Plugin.define({ id, setup })`.
- **1.18.25 main export has no `Plugin` value**: `dist/index.js` only re-exports `./tool.js`;
  `Plugin` in `dist/index.d.ts` is the **V1 function type** `(input, options?) => Promise<Hooks>`.
- V2 identity helper is at `@opencode-ai/plugin/v2/promise`: `define(plugin) { return plugin }`.
  Shipping your own identity wrapper is ABI-identical and avoids the dependency.
- V2 PluginContext fields: `options`, `agent`, `aisdk`, `catalog`, `command`, `integration`,
  `plugin`, `reference`, `skill` — **no `event`, no `session`, no `storage`**.
- Runtime V2 loader accepts only `{ id, setup }` or `{ id, effect }`, wraps Promise plugins with
  `PluginPromise.fromPromise`, which **ignores a cleanup function returned from `setup`**
  (cleanup is documented, not wired). V1 `dispose()` IS called on unload.

## How events actually reach plugins on 1.18.25

Two loaders coexist:

1. **V2** (`packages/core`) — `plugins` array / `{plugin,plugins}/*.{ts,js}` under config dirs.
   Promise `setup(ctx)` as above. **Cannot subscribe to the public event stream.**
2. **V1** (`packages/opencode/src/plugin/index.ts`) — `plugin` / `plugin_origins`, same glob.
   Loads `{ id, server(input, options) }` and delivers EventV2 through `hooks.event`:
   `hook.event({ event: { id, type: event.type, properties: event.data } })`.
   `PluginInput.client` is a real `@opencode-ai/sdk` client (`session.get`, `session.status`,
   `event.subscribe` SSE).

`fromPromise` + Effect `Schema.Struct` ignore extra keys, so a single default export of
`{ id, setup, server }` satisfies both loaders — the dual-shape pattern to use for any
event-driven plugin until V2 gains `ctx.event`.

## Event names and fields (there is NO `step_finish`)

`step_finish` is only (a) the CLI `--format json` stdout label in `run.ts` and (b) the internal
LLM processor event `case "step-finish"` (`publish-llm-event.ts`), which copies `event.reason`
into the public event's `finish` field.

| Role | Event `type` | Payload path | Notes |
| --- | --- | --- | --- |
| Step end (authoritative terminal signal) | `session.next.step.ended` | `properties.finish` or `data.finish` | `finish`: `"stop"` (terminal) / `"tool-calls"` (agent continues) / `"unknown"` |
| Partial/legacy equivalent | `message.part.updated` with `part.type === "step-finish"` | `part.reason` | Same semantics, part-level |
| Step start (activity, cancels grace) | `session.next.step.started` | `properties.sessionID` | |
| Idle | `session.idle` | `properties.sessionID` | No status enum; idle implied |
| Status | `session.status` | `status.type`: `"idle"` / `"busy"` / `"retry"` | |
| Child (subagent) session marker | `session.created` | `info.parentID` | Absent/null = primary session |

Envelope variants a plugin must normalize: `{ type, properties }` (V1 hook),
`{ type, data }` (V2 public), and wrapped `{ event }`.

## Lesson for the exit-guard class of plugins

- Env-var gating (`OPENCODE_RELAY_RUN=1`) at `setup`/`server` entry = only reliable run-vs-TUI gate.
- Make `process.exit` an injected dependency for testability.
- Requirements written from docs (`ctx.event.subscribe`, `step_finish`+`reason`) must be re-spiked
  per installed version before implementation — the docs track a newer API than the stable release.