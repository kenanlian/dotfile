# Kenan's pi-auto-handoff extension

Kenan's OWN extension: `~/Secret-Projects/pi-auto-handoff` (GitHub `kenanlian/pi-auto-handoff`, git remote SSH). Targets Pi **0.85.x** (peer `@earendil-works/pi-coding-agent`). Sibling trees: `~/Secret-Projects/development-artifacts/pi-auto-handoff` (dev artifacts) and `~/Secret-Projects/opencode-auto-handoff` (OpenCode port).

**Never confuse with third-party handoff packages** — several near-identical names exist and none is his:

| Package | Behavior | Difference from Kenan's |
|---|---|---|
| npm `@ttiimmaahh/pi-handoff` | Writes `.pi/handoff.md` at 80% context (or absolute token threshold); offers to load in a new session; enriches `/compact` | Doc-on-disk approach; no in-place context drop |
| npm `@ssweens/pi-handoff` | `/handoff` command + `handoff` tool + compact hook → `ctx.newSession()` + `session_query` | Creates a NEW session |
| GitHub `danecando/pi-auto-handoff` | Counts assistant turns (default 50), pre-fills `/handoff` | Turn-count proxy; new session |
| oh-my-pi fork (checkout at `~/Source-Code-Learning/oh-my-pi`) | `compaction.strategy: handoff` maintenance pipeline in the harness itself | A Pi fork, not an extension |

## Design

**handoff → drop active LLM context → continue, keeping the same process PID and logical session id.** Durable session JSONL is append-only and never deleted. It never calls `ctx.newSession()` and does not use `ctx.compact()` as the primary reducer — manual compaction from `agent_end` calls `abort()` → `waitForIdle()`, which cannot settle until the handler returns (deadlock or post-exit race in print mode).

The in-place history splice is Pi's `context` event (the messages sent to the next LLM call): one full clear (`messages-cleared`, logged once) replacing the payload with a continuation message, then `filter-since` on later calls keeps post-clear messages so context regrows and the model keeps its own tool results.

Continuation goes through `pi.sendUserMessage(text, {deliverAs: "followUp"})` from `agent_end` — print/JSON mode keeps waiting because `_handlePostAgentRun` continues the original `prompt()` while follow-ups are queued.

## Trigger (v1 — superseded by the v2 design below; src/machine.ts `evaluateTrigger`)

Gates in order: `enabled` → phase not handoff/clearing → debounce (≥ `minTurnsBetweenHandoffs` completed assistant turns since last handoff) → no tool in flight. Then two-sided:

- **threshold-wp**: occupancy ≥ `contextThreshold` (0.5) AND a work-package in the plan file just became done-like;
- **hard-ceiling**: occupancy ≥ `hardCeiling` (0.75) alone, even mid-WP (model is told to finish and persist the current WP first).

Occupancy source: `ctx.getContextUsage().percent`, else last-assistant `Usage` ÷ `ctx.model.contextWindow` (fallback `assumedContextLimit` 200k, warns once). No character-count heuristic of its own — it will not trigger without Pi-reported tokens/percent.

## Flow per handoff

1. `handoff-requested` — assign `handoff-NNN-<timestamp>.md` under `handoffDir`; handoff instructions injected via `before_agent_start` system-prompt append (only when a NEW prompt gets submitted) or idle `sendUserMessage` — in headless single-prompt relay the second is the only delivery point, and the followUp-ignited run carries the instruction in the user-message text itself.
2. Model writes the handoff doc to the exact path; extension verifies required sections. Timeout `handoffTimeoutMs` (90s), ONE retry, then `handoff-give-up` back to monitoring so the task cannot hang.
3. `handoff-written` — plan file gets an HTML-comment marker (`<!-- handoff n=… file=… ts=… -->`), occupancy counters reset.
4. `clearing` / `messages-cleared` (once) — context event returns continuation payload instead of the branch.
5. `continuation-projected` (in-run splice) and/or `continuation-injected` (idle follow-up) — exactly one continuation path runs.

## Run-boundary behavior (verified 0.85.1 source)

**Hard-ceiling mid-run = mark-only.** No instruction channel exists inside a live run (`before_agent_start` already fired for the only prompt), so a ceiling crossing during a run just flips the state machine to `handoff-requested` while the model keeps working, unaware. Until the run ends, checkpoints verify-and-timeout the not-yet-written handoff file: `requested → retry → handoff-give-up → re-request` churn is expected, harmless, and self-healing — occupancy never decreases within a run, so `agent_end` always re-requests and immediately delivers. Never read that churn in `.auto-handoff-events.jsonl` as a malfunction.

**Overflow interplay with pi core.** A run that climbs all the way to the window dies on an overflow `error` BEFORE any handoff doc exists — the run boundary IS the wall. Pi core then reacts first (drop failed assistant message → compact → retry once; threshold compaction at `contextWindow − 16384` ≈ 92%) and only afterwards drains the extension's queued handoff instruction, so the doc gets written from post-compaction (lossy) memory. Deliverability is preserved; fidelity is reduced. Mitigations: lower the threshold to widen the doc-writing margin; split oversized tasks into WP-sized continuations on the same `--session-id`; or the v2 mid-run `context`-event injection (see the v2 design below), which turns "wait for boundary" into "next LLM call". The design principle holds either way: never hard-cut inside the tool loop; deliver at LLM-call gaps (v2) or the run boundary (v1).

## v2 design — mid-run context-event injection (agreed direction; supersedes the v1 trigger)

Scope (Kenan's framing): the ONLY case that matters is occupancy over threshold while the run is STILL in progress. Normally-ended runs are out of scope — the final report is the natural handoff and relay harvest proceeds as usual. Consequence: ONE threshold (`contextThreshold`, 0.5); delete `hardCeiling`, WP-boundary detection (the whole plan-markdown parser), and `minTurnsBetweenHandoffs` (freshly-cleared context cannot immediately re-trip).

Delivery: append a strong synthetic user instruction at the END of the `context` event messages array — the next LLM call sees it; no text-only boundary is needed. Wording is the success factor: context near the limit; forbidden to continue the original task; only the minimal tool calls needed to write the doc; exact output path; required-section list; end with a short text immediately after writing.

Persistent re-injection: the `context` array is rebuilt from session state for every LLM call — mutations are one-shot projections, never persisted (this is why v1's clear needs `filter-since` on every later call). While ratio ≥ threshold and the doc is unverified, re-inject the SAME instruction at EVERY `context` event so it stays in-context and the model cannot forget it. Use a FIXED message key (`handoff-inject:<n>`) — a `Date.now()`-minted key differs every call and corrupts `preClearIds` accounting.

Channels: the `before_agent_start` system-prompt delivery path is deleted (system-prompt overrides are reset by pi core at run end anyway — `_runAgentPrompt`'s `finally` clears `_systemPromptOverride`). `agent_end` + `sendUserMessage` survives ONLY as the relight path when the doc is verified but the model already stopped (no further `context` event will come). Exactly one of {context first-clear, agent_end relight} runs per handoff — the v1 single-continuation invariant extends to delivery.

Continuation payload = FIRST USER MESSAGE, not system prompt: inline the FULL handoff doc text (a few KB; saves a read call, the model sees everything on wake) plus the plan path, and embed the machine marker `<!-- pi-auto-handoff-continuation n=… -->` for restart recovery.

session_start recovery: a mid-continuation process death followed by a same-`--session-id` restart rebuilds the FULL history from JSONL into a fresh extension instance (no filter state) → ratio is still over threshold → re-inject → the model re-writes a doc (self-healing, one wasted round). To skip the waste: on `session_start`, scan the branch for the continuation marker and pre-seed `preClearIds` with every earlier message key, restoring the projection immediately.

Kept from v1 unchanged: the verification chain (`tool_execution_end` as primary checkpoint; exact path + six-section regex + ≥40 chars — a STRUCTURE gate only; content quality surfaces in the continuation and belongs to outer supervision), the first-clear/filter-since machinery, event JSONL logging, append-only durable JSONL. Backstops for model non-compliance stay outside the extension: pi core compaction (≈92%) and the outer supervision loop; at most add a relaxed warn-log (injected for N minutes, still no doc), never a block.

Economics: above threshold, every LLM call bills the full history — verify at the earliest point (`tool_execution_end`) and clear on the very next `context` event; each turn earlier is one full-context call saved.

Workflow note: scoped as a DIRECT card on the `pi-auto-handoff` board (no write-plan/execute-plan split) — justified because it reuses the already-tested clear/continue machinery and shrinks net code.

## Config

Layers (low → high): `.pi/auto-handoff.json` → `.pi/auto-handoff.local.json` → `PI_AUTO_HANDOFF_*` env. Keys: `enabled` (true), `contextThreshold` (0.5), `hardCeiling` (0.75), `assumedContextLimit` (200000), `handoffDir` (`.pi/handoff`), `planFile` (`.pi/plan/active-plan.md`), `handoffPromptFile` (bundled template), `continuationPromptFile` (bundled), `continuationPrompt` (inline override, wins over file), `minTurnsBetweenHandoffs` (3), `logging` (true), `handoffTimeoutMs` (90000), `logFile`. Thresholds clamp to 0–1 and `hardCeiling` is forced ≥ `contextThreshold`. `/auto-handoff` prints a JSON status snapshot (phase, cycle, ratio, pending, sessionID).

## Work-package (plan) file format

Markdown: checklists (`- [x] **WP-1** …`) or status tables (`| WP-01 | verified | … |`). Done-like: `done`, `verified`, `complete`, `[x]`. A WP boundary is a WP whose status BECAME done-like since the extension's last snapshot — stale-done WPs do not re-trigger.

## Ops

- Load: `pi --no-extensions -e ~/Secret-Projects/pi-auto-handoff/src/index.ts`, or project `.pi/settings.json` `extensions`/`packages` lists. Copying `src/index.ts` into `.pi/extensions/` auto-discovers but file options are then empty — prefer `-e` + `.pi/auto-handoff.json`.
- Verify: `npm test` (unit), `npx tsc --noEmit`, `npm run smoke` (real headless Pi end-to-end; removes `.smoke/` unless `SMOKE_KEEP=1`; never writes `~/.pi/agent/settings.json`).
- Events: JSON lines on stderr + `<handoffDir>/.auto-handoff-events.jsonl`. Debugging invariant: per handoff the events fire once in the order listed above; `messages-cleared` repeating on every model call means the one-clear-then-filter cycle broke.
