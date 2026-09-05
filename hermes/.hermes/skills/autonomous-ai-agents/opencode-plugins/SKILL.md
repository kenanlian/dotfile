---
name: opencode-plugins
description: "Use when building OpenCode V2 plugins or context hooks."
version: 0.1.1
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [OpenCode, Plugin, Extension, Context-Management]
    related_skills: [opencode, development-orchestrator]
---

# OpenCode V2 Plugin Development

Build plugins and extensions for OpenCode V2: custom tools, hooks, slash commands, context-management automation (auto-handoff, compaction control), or anything that must observe/modify OpenCode behavior mid-session.

**Read `references/v2-api-research.md` before designing** — it condenses the V2 plugin API surface, compaction internals, and session-revert semantics verified from official docs and SDK source on 2026-09-02, plus the auto-handoff plugin design agreed with 柯楠 (unimplemented; includes a spike checklist).

## When to Use

- Building or debugging an OpenCode V2 plugin (`.opencode/plugins/` or npm package)
- Automating session continuation / context handoff for long delegated OpenCode runs
- Writing tools/hooks that must inspect or rewrite model context mid-session

## Verified ground truth (2026-09-02)

- **V1 ≠ V2 plugin shapes.** V2: `Plugin.define({ id, setup(ctx) })` default export from `@opencode-ai/plugin`. V1-era docs (`opencode.ai/docs/...`) show hook-string exports (`"tool.execute.before"`) — mixing them produces broken plugins. V2 docs: `opencode.ai/v2/docs/build/plugins`.
- **`ctx.session.hook("context")`** fires immediately before EVERY model dispatch with mutable `event.messages` / `event.system` / `event.tools` / `event.generation` / `event.providerOptions`. Edits affect only the outgoing call, not persisted history. This is the natural checkpoint for token monitoring and per-call context rewriting. Does not fire for title or compaction requests.
- **TUI `/clear` is an alias for `/new`** — it starts a NEW session; there is no literal clear-current-session command. Clearing the current session in place is the V2 `revert/stage` API.
- **`revert.stage`** (`POST /api/session/{id}/revert/stage`) removes messages after a boundary from the ACTIVE PROJECTION (what model context is assembled from) while durable session history is retained (archive preserved by design). Idle-only (409 SessionBusyError while running). Can optionally restore file changes after the boundary — skip that when code must be kept. UNVERIFIED: whether a plugin ctx can call it (absent from documented ctx.session method list; HTTP/JS SDK have it).
- **Built-in compaction**: on by default, triggers only near the context limit, summary capped at a hardcoded 4096 output tokens and framed as historical context (not instructions). Custom-threshold config keys (`compaction.threshold`, `token_threshold`, `context_threshold`, `strategy`, …) are NOT in any stable release — PR #10123 unmerged as of 2026-09. Never write configs relying on them.
- **`ctx.session.generate()`** = one-shot text generation that does NOT pollute session history (good for bystander summaries/evals).
- **`ctx.event.subscribe({ signal })`** = AsyncIterable over the server's public event stream; abort it in plugin cleanup. **NOT present on installed 1.18.25** (see below).
- **Installed 1.18.25 contradicts the docs (spike-verified 2026-09-03, `references/opencode-1.18.25-spike.md`):** the V2 `PluginContext` has **no `event`, no `session`**; `Plugin.define` is **not** in the `@opencode-ai/plugin` main export (identity helper lives at `/v2/promise`); `fromPromise` **drops** the cleanup returned from `setup`. Events actually reach plugins via the **V1 loader's `hooks.event`** (`{ id, server(input, options) }` shape, `properties` = EventV2 `data`; real SDK client on `input.client`; `dispose()` honored). There is **no public `step_finish` event** — terminal step = `session.next.step.ended` with `finish` field (`stop`/`tool-calls`); idle = `session.idle`; child sessions carry `parentID` on `session.created`. Ship dual-shape entries (`setup` + `server`) for event-driven plugins.

## Cross-host delegation boundary

When a custom tool selects between OpenCode-native and external Cursor execution, treat it as an **OpenCode-host adapter**, not a universal cross-host orchestration service:

- An Agent currently running in OpenCode may call the custom delegation tool; the tool may route that direct child to an OpenCode child session or an external Cursor relay according to user-level configuration.
- Once the current Agent is Cursor — whether it is the outer parent or a first-level Agent started through relay — further delegation uses Cursor's native Task/subagent mechanism. Do not callback into the OpenCode plugin or introduce an MCP/session bridge merely to make the physical mechanism uniform.
- Keep semantic policy uniform across hosts (allowed roles, access mode, nesting depth, task contract), while allowing each host to use its native subagent implementation.
- Backend/model selection belongs to the OpenCode tool's configuration, not its task-facing input. Persist actual execution metadata for diagnostics, and bind resumed logical sessions to the backend/session selected at creation rather than rerouting from changed configuration.

This boundary prevents an OpenCode convenience tool from expanding into a bidirectional delegation service. Broaden it only when cross-host callbacks are an explicit product requirement.

## Design constraints for Hermes-relayed sessions

Any auto-continuation mechanism must keep the OpenCode **process PID and session_id unchanged** — Hermes relay monitoring (resume.yaml, events.jsonl liveness) keys on both. Prefer logical in-place continuation (revert + injected opener prompt) over `session.create()` + `prompt()`: `opencode run` is one-shot per session, so a new session has no in-process driver and breaks the resume contract. See the Path A′ vs Path B analysis in the reference.

## Pitfalls

- Plugin API is beta: contracts change between releases; test against the installed package, not a workspace-linked copy.
- `revert` during an active run returns 409 — treat idle-only as a feature (trigger at turn/work-package boundaries).
- After a revert, whether auto-compaction accounting resets and what the next `context` hook sees is UNVERIFIED — spike before relying on it.
- OpenCode loads plugins/config once at startup; editing plugin files mid-session requires a restart.
