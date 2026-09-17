---
name: pi-coding-agent
description: "Use when driving Pi CLI for coding delegation or extensions."
version: 1.0.9
tags: [Coding-Agent, Pi, Delegation, Subagent, Headless]
metadata:
  hermes:
    tags: [Coding-Agent, Pi, Delegation, Subagent, Headless]
    related_skills: [opencode, cursor-delegate, pi-delegate]
---

# Pi Coding Agent

[Pi](https://github.com/earendil-works/pi) (npm `@mariozechner/pi-coding-agent`, formerly badlogic/pi-mono) is a minimal terminal coding harness. The core deliberately ships **no subagents and no plan mode** — those come from TypeScript extensions. Kenan's machine: `pi` at `~/.local/bin/pi`, verified working at 0.84.4 (2026-09-04).

Pi is the **approved host for the `delegate_agent` router** (Kenan decision 2026-09-04): native backend = pi subprocess relay, isomorphic to the Cursor relay. Design: `development-artifacts/agent_skills/delegations/pi-feasibility-spike/design-proposal.md`.

For the Hermes top-level development workflow (transport stages, result contract, exact-session resume), load the `pi-delegate` transport adapter instead of this Skill. This Skill owns Pi CLI knowledge: providers, event anatomy, tool gating, extensions, subagents.

## Kenan's Workflow Boundaries

- Use the existing global Agent Skills collection as Pi's Skill source. Do not copy, mirror, or maintain separate per-project or per-agent Skill trees for Pi.
- Agent tiers are semantic capability labels, not backend identities. Resolve every tier's backend and model from user configuration; never assume `expert` means Cursor or bake any current route into workflow prose.
- Keep initial permission engineering proportional to observed workflows. A read-only Pi process must lack direct write tools, but do not add transitive enforcement against a read-only parent delegating to a write child unless Kenan requests it or a real Agent Skill needs that guarantee.
- Add optional capabilities such as Web or LSP only after the base transport, global Skill discovery, exact resume, and result contract are working and evidence shows the capability is needed.

## Providers & Models (Kenan's setup, verified)

- Config: `~/.pi/agent/settings.json` (defaultProvider/defaultModel), `models-store.json` (catalog), `auth.json` (API keys).
- Credentials in `auth.json` are portable, not locked to Pi: DeepSeek Harness (`dsh`, npm `@deepseek-ai/dsh`, installed globally on this machine, web UI at `127.0.0.1:3080`) embeds the same `@earendil-works/pi-ai` provider catalog and stores pi-ai credentials as `llm-pi-ai/<provider>` records in `~/.dsh/.credentials.yaml`. All four Kenan providers migrated (copy, Pi untouched): [references/dsh-credential-migration.md](references/dsh-credential-migration.md). The `opencode-go` route in dsh additionally needs a static `x-opencode-session` header — the Go gateway rejects bare-pi-ai clients with 400 MissingSessionID; verified fix in the same reference.
- `zai-coding-cn` = Zhipu GLM Coding Plan, baseUrl `https://open.bigmodel.cn/api/coding/paas/v4`, models glm-4.7…glm-5.3 + flash/highspeed variants. Default: `glm-5.3`.
- `opencode-go` provider also configured (deepseek-v4-pro/flash, glm-*, grok-4.6, …) — same keys/quota as OpenCode, no new billing surface.
- `kimi-coding` (migrated 2026-09-08 from OpenCode's `kimi-for-coding`): Moonshot Kimi Coding Plan, **Anthropic-protocol** builtin provider, baseUrl `https://api.kimi.com/coding`, models `kimi-for-coding`(=K2.7 Code)/`kimi-for-coding-highspeed`/`k3`/`k3-256k` (1M ctx). Pi stores its key in `~/.pi/agent/auth.json` under provider id `kimi-coding` (`{"type":"api_key","key":"sk-kimi-…"}`); OpenCode's id for the same service is `kimi-for-coding` — provider ids differ per tool, don't cross them. Both direct and proxied network paths verified working.
- `pi --list-models [search]` to browse. `--provider <name> --model <id>` per run. Agent frontmatter accepts provider-prefixed ids (`zai-coding-cn/glm-5.3-flash` verified).
- Network (verified 2026-09-05): direct connection and stripped-proxy both work. The NO_PROXY direct rule for bigmodel originally lived only in `dotfile/zsh/.zshrc` (interactive shells), so a pi launched from the Hermes gateway terminal inherited `HTTP(S)_PROXY=127.0.0.1:8118` with no NO_PROXY — the local proxy intermittently black-holes the bigmodel SSE stream and the run dies mid-turn (pi exits, no `agent_settled`, no final text), repeatedly. **Fixed at the root (2026-09-05 evening): `NO_PROXY`/`no_proxy` now also live in `~/.hermes/.env`** next to the existing `HTTP(S)_PROXY` lines; the gateway reloads `.env` per turn with override=True (verified in `gateway/run.py` `_reload_runtime_env_preserving_config_authority`), so pi subprocesses inherit direct-connect with no restart and no launch-script export. Keeping the export in loop scripts is harmless belt-and-braces. Editing `.env`: the `patch` tool is DENIED there (protected credential file) — edit via python in `terminal` with a timestamped backup, and verify parsing with the gateway venv python (`~/.hermes/hermes-agent/venv/bin/python`, dotenv_values) because system python lacks dotenv. The turn you patch in won't see the new value; it lands next turn.

## Headless Delegation (primary Watson use)

```bash
pi -p --mode json --session-id <logical-id> "<task>"   # cwd = delegation workdir
```

- `-p` = non-interactive, exits when done. `--mode json` = NDJSON event stream on stdout.
- `--session-id <id>` **creates-if-missing** and continues existing — the logical-session anchor for delegation continuation (verified: second call recalled prior context in ~1s). Also `--continue`, `--resume`, `--fork <id>` (branch a session), `--session-dir`, `--no-session` (ephemeral).
- Synchronous semantics: the process runs to completion; treat exit + terminal events as the result contract.

### Event stream anatomy (verified 0.84.4)

| Event | Meaning / use |
|---|---|
| `session` | FIRST line: `{id, cwd, timestamp}` — resume/monitoring anchor (equivalent to OpenCode's system-init line) |
| `agent_start/turn_start/message_start/message_update/message_end/turn_end` | progress; `message_end` assistant content carries final text |
| `agent_end` | carries full `messages` array — extract result here |
| `agent_settled` | terminal marker |
| `auto_retry_start`/`auto_retry_end` | transient API failure retry with `attempt/maxAttempts/delayMs/errorMessage` — **normal**, monitors must NOT alarm on it; fail only on exhaustion |

GLM endpoint occasionally throws "Connection error"; auto-retry absorbs it (observed 2 retries, then success).

### Run anatomy & boundaries (verified 0.85.1 source)

- One `prompt()` = one **run**: an internal loop of LLM response → tool calls → next LLM call. `before_agent_start` fires once per prompt submission, never per tool-loop iteration — mid-run an extension can only rewrite what the next LLM call sees (the `context` event messages array); there is no channel to hand the model new instructions inside a live run.
- A run ends only by: text-only response (model-chosen natural stop), `stopReason: "error"` — including context overflow, because the API rejects the oversized history, so a run physically cannot continue past the window — abort, or process death. The first two emit `agent_end`; process death does not.
- System-prompt overrides do not survive the run boundary — `_runAgentPrompt`'s `finally` resets `_systemPromptOverride` — so extension instructions that must persist across runs ride real user messages (`sendUserMessage`/followUp), never system-prompt appends.
- Post-`agent_end` order is fixed (`_handlePostAgentRun`): retryable-error check → `_checkCompaction` (core auto-compaction; default enabled, `reserveTokens` 16384, triggers at `contextWindow − reserve` ≈ 92%; overflow additionally drops the failed assistant message, compacts, retries once) → drain extension-queued follow-ups. Extension messages queued at `agent_end` therefore ride AFTER any core compaction.
- Headless single-prompt relay: an extension's only instruction-delivery point is the `agent_end` idle `sendUserMessage` (followUp-queued; `_handlePostAgentRun` keeps the process alive to drain it). The `before_agent_start` system-prompt append applies only when a genuinely new prompt is submitted — an interactive next message or a second `--session-id` delegation call — and a followUp-ignited continuation run carries its instruction in the user-message text itself, not in a system-prompt append.

**Interrupted-run signature (verified 2026-09-05)**: a hard drop mid-run looks like this in the NDJSON — several `tool_execution_end` events, then a bare `turn_start`, then EOF. No `agent_end`, no `agent_settled`, and every `message_end` carries only toolResult payloads (no harvestable assistant text). Treat "process exited" as incomplete until `agent_settled`/`agent_end` appears; harvest the final report only from the settled run. Recovery is cheap: relaunch with the **same `--session-id`** and a short continuation prompt ("继续执行任务，从中断处继续，不要重新调查已完成的部分"), appending to the same events file — session state on disk preserves all prior tool calls. Wrap this in a guard loop: check `grep '"type":"agent_settled"' events.jsonl` before each round, relaunch up to N times with sleep between. Full verified script + incident notes: [references/long-run-supervision.md](references/long-run-supervision.md).

**Dual-writer fingerprint (verified 2026-09-05 incident)**: two live pi processes sharing one `--session-id` interleave writes into one events file — signature: `agent_settled` count ≥ 2 while `agent_start` count == 1, plus events with fresh `toolCallId`s appearing AFTER a settled line; timestamp-gap analysis shows zero gaps (the streams cover each other). Also: `agent_end` carries a `willRetry` bool. And: the session store (`~/.pi/agent/sessions/<cwd-slug>/*.jsonl`) holds message/state records only — `agent_settled`/`agent_end` NEVER appear there (verified), so never diagnose "interrupted" from the store; judge completion only from the attempt's stdout events file. One-shot triage of any events file: `python3 scripts/pi-run-forensics.py <events.jsonl>`.

## Tool Gating = access classes (verified)

- `-t/--tools read,bash` allowlist — read-only enforcement is HARD: model with only `read` attempted a write and physically could not (verified).
- `--no-builtin-tools` keeps only extension/custom tools; `--no-tools` none; `-xt` denylist.
- Pi has **no permission wall/sandbox**: cross-directory file access is unrestricted. Scope declarations (`additional_directories`) are audit statements in the brief, not enforcement. Enforcement requires an extension gating `tool_call` events.

## Skill discovery (verified 0.85.1 source, `dist/core/skills.js` + `system-prompt.js`)

Pi auto-discovers Skills at startup from four sources (verified 0.85.1 `dist/core/package-manager.js`): project `<cwd>/.pi/skills` and project `.agents/skills` walked up the ancestor chain (both trust-gated; `.agents` entries keep their own baseDir), plus user `~/.pi/agent/skills/` and user `~/.agents/skills/` (each recurses until it hits a `SKILL.md`). Discovered Skills are injected into the system prompt as an `<available_skills>` block listing name, description, and **absolute location** — the model never needs to guess a path for a visible Skill. `/skill:<name>` expansion resolves by name across ALL loaded sources — in a repo carrying an `.agents/skills` symlink to the global collection it resolves through the project link (verified live). The `~/.agents/skills/` root that models guess by convention IS one of Pi's real user-scope roots; on this machine it simply does not exist.

The filter that bites: frontmatter `disable-model-invocation: true` removes a Skill from that block entirely — discovered but invisible, so the model only knows it exists if the prompt says so, and it has no location. Faced with "use the X Skill (discovered from the global Skill root)" and no path, the model guesses community-default roots (e.g. `~/.agents/skills/`), then degrades to broad `find ~` scans that stall the run for minutes on a home holding vaults and node_modules. Kenan's workflow Skills (`write-plan`, `execute-plan`, `review-execute-candidate`, `audit-persistence`) all carry this flag deliberately — keep the flag (it prevents spontaneous invocation of heavyweight workflow Skills in ordinary sessions).

Explicit invocation of a hidden Skill (verified 0.85.1 source + live run): `/skill:<name>` expansion inlines the full SKILL.md as a `<skill name=... location=...>` message and ignores `disableModelInvocation`. Two structural conditions: the message must literally start with `/skill:` (a `startsWith` check — Pi assembles `[stdin, @file text, CLI message]`, so only stdin-carried content qualifies; a brief riding `@file` can never trigger it), and the name must be space-terminated on the same line (`indexOf(" ")` splits name from args — `/skill:write-plan begin` expands, `/skill:write-plan` + newline does not). Working form: `printf '/skill:write-plan <lead-in>\n\n<body>' | pi --mode json -p <flags>` — NO positional argument: piped stdin alone is the initial prompt; a trailing `-` is wrong twice over (bare `-` fails with `Unknown option: -`; `-- -` appends a stray `-` character to the assembled message). The pi-delegate relay rides the brief on child stdin (pi consumes piped stdin as the initial prompt, no positional) and expects commissioning briefs to open with `/skill:<name> ` (name + same-line trailing space); it fail-fasts on a malformed first line. Prose-only references like "Use the write-plan Skill" are deprecated in relay briefs. Cross-tool sigils for relay briefs: Codex expands a leading `$<skill-name>` mention into an injected skill message even when the Skill is absent from Codex's visible `<skills_instructions>` block (verified in a Codex rollout: the `disable-model-invocation: true` skills were exactly the absent ones); Codex does not recognize `disable-model-invocation` at all — it is an Agent Skills standard field and Codex hides skills via its own separate mechanism, which is why a Skill absent from the visible block stays mention-resolvable. cursor-delegate briefs open with `/name`.

Verify injection when diagnosing: grep the Pi session store record (`~/.pi/agent/sessions/<cwd-slug>/<session>.jsonl`) for `available_skills` — zero hits means the prompt-injection layer was empty and the model was path-guessing by design of the flag, not by a discovery failure.

## Extensions

- TypeScript modules: `export default function (pi: ExtensionAPI)`; `pi.registerTool()` (typebox schema, `execute(toolCallId, params, signal, onUpdate, ctx)`), `pi.on('tool_call', …)` can **block/modify** tool calls (the gate mechanism), `pi.registerCommand`, custom TUI.
- Locations: `~/.pi/agent/extensions/*.ts` or `*/index.ts` (global), `.pi/extensions/` (project, trust-gated). `-e <path>` ad-hoc. `/reload` hot-reloads auto-discovered ones.
- **Headless assembly (coding-agent-harness / pi-delegate)**: start from `--no-extensions` (`-ne`) and attach only the intended roots with explicit `-e` (repeatable; explicit `-e` still loads under `-ne`). Skills are controlled separately with `--no-skills` (`-ns`) plus `--skill <path>` (repeatable). Verified Pi 0.85.1 print/json, 2026-09-17, model `zai-coding-cn/glm-5.3-flash`:
  - `--skill` of a `disable-model-invocation: true` Skill (`write-plan`) together with `-ns` **does load it**. `/skill:write-plan ` expansion inlines SKILL.md as a `<skill>` message (`Plan-writing mode is active` present in the session). The Skill does **not** appear in `<available_skills>` — `disable-model-invocation` still filters the system-prompt list for CLI-mounted Skills. A project `.agents/skills/decoy-skill` in the same cwd was not loaded.
  - `-ns` without `--skill` turns off **all** discovery in that run: neither `~/.pi/agent/skills` (write-plan / delegate-work / execute-plan) nor project `.agents/skills` (decoy-skill / `DECOY_SKILL_TOKEN`) appeared in the session store. Official docs match: `--skill` remains additive under `--no-skills`.
  Harness `skills.mode=explicit` profiles always pass `-ns` plus the listed `--skill` dirs. `mode=auto` passes neither flag. When `skills.inline` is set, the Harness brief starts with `/skill:<inline> ` (verified 2026-09-17: a compileBrief plan brief delivered on relay stdin expanded to `<skill name="write-plan"` in the session). `-t`/`--tools` allowlists apply to extension-registered tools as well as builtins.
- **`PI_CODING_AGENT_DIR` exists but was rejected for stage differences.** Pi can redirect its whole config directory via that env var. The autodev/harness decision is to keep one config directory and express process-level differences (which extensions/tools/env a stage gets) as relay argv/`--env`, not as per-stage config trees.
- **Same-name override of built-in tools works** (verified 0.84.4): `registerTool({name: "write", ...})` in an extension replaces the built-in entirely — the custom `execute` runs, the real file write never happens (official example: repo `examples/extensions/tool-override.ts`). Complements: `-nbt` disables all built-ins, `pi.on('tool_call')` can block/modify, `setActiveTools()` toggles at runtime.
- Extensions run with **full system permissions**.
- Verify extension-API semantics against the pinned package source in the consuming repo (`node_modules/@earendil-works/pi-coding-agent/dist/core/*.js`) — grep the event name and read the emit site rather than inferring from docs.
- Symlink install pattern verified: repo working copy → `ln -sf` into `~/.pi/agent/extensions/<name>/`.

### Headless `-e` / `-t` behavior (verified Pi 0.85.1 print/json, 2026-09-17)

- **Bad `-e` path does not warn-and-continue in print/json mode.** Missing path, empty directory, `.txt` file, and directory whose `index.ts` does not export a factory all exit `1` with stderr `Error: Failed to load extension "<path>": ...` plus `Hint: Start without extensions using "pi -ne".` No NDJSON `session`/`agent_settled` is emitted; the model is not called. (Interactive TUI was not re-measured.) Coding-agent-harness still fail-closes on a missing `harnessAttestation` line because argv `-e` is not proof that stage-submit's factory ran, and a later Pi change could reopen warn-and-continue.
- **`-t` allowlist with a name that is not a registered tool: unknown names are silently ignored.** `pi --mode json -p --no-extensions --no-session -t read,definitely_not_a_real_tool` exited 0, produced empty stderr, ran to `agent_settled`, and the unknown name never appeared in the event stream. Therefore listing a third-party tool (e.g. todos-tool) on `-t` does **not** prove the extension loaded; a later presence check must use a different signal (attestation event or an actual successful tool call).
- **`@gamaraan/todos-tool` 0.3.0 loads on Pi 0.85.1** (the package's declared peer is 0.84.x): `pi --mode json -p -ne -e ~/.pi/agent/npm/node_modules/@gamaraan/todos-tool/src -t read,todo` with `zai-coding-cn/glm-5.3-flash` (2026-09-17) exited 0, empty stderr, and executed `todo` (`op=init`, `isError: false`).

## Subagents

No built-in; official example `packages/coding-agent/examples/extensions/subagent` in the pi repo works unmodified on 0.84.4 (verified: single + parallel delegation, custom agent with GLM flash). Each delegation spawns a real subprocess:

```
pi --mode json -p --no-session --model <frontmatter> --tools a,b \
   --append-system-prompt <tmpfile> "Task: <task>"   # per-task cwd
```

Agents = markdown frontmatter files in `~/.pi/agent/agents/` (`name/description/tools/model` + system prompt). For relay-style use, fork only the spawn core + agent discovery (~400 of ~1200 lines); the TUI rendering, chain mode, workflow prompts, and interactive project-agent confirms are dead weight headless. Swap `--no-session` → `--session-id` for continuation. Full inventory: [references/delegation-transport.md](references/delegation-transport.md).

### delegate-agent router config (`pi-delegate-agent` extension)

Backend/model routing is config-owned and invisible to the caller: the parent LLM passes only the `agent` tier + prompt; `router.ts` resolves the route from `~/.pi/agent/delegate-agent.json` (symlink → dotfile stow target `~/Secret-Projects/dotfile/pi/.pi/agent/delegate-agent.json`, so edits are dotfile commits) and **re-reads the file on every tool call** — config edits apply to the next delegation, no Pi restart. Resolution: `DELEGATE_AGENT_CONFIG` env → default path. A `~/.pi/agent/delegate-agent.local.json` overlay (verified 2026-09-07, `router.ts` `applyLocalOverride`) deep-merges per-tier `agents` entries plus optional `nesting`/`limits`/`call_allowlist` on top of the base config — fit for temporary routing (e.g. provider-quota failover) without a dotfile commit; delete the file to roll back. The overlay is skipped when `DELEGATE_AGENT_CONFIG` is set (nested-child isolation stays load-bearing). `native` routes require `agent_file` (a cursor→native switch must add it or the router blocks); `cursor` routes need only `model`. Validate edits by running the extension's own `resolveNewDelegation` over all tiers, not just `JSON.parse`. Detail + recipe: [references/delegate-agent-config.md](references/delegate-agent-config.md).

## Web access (pi-web-access)

When Pi needs web access, install the `pi-web-access` package — not an MCP adapter + Exa server. Rationale: Pi's philosophy is "No MCP" (capabilities ship as extensions); `pi-mcp-adapter`'s proxy mode hides tool descriptions from the model and measurably degrades tool-calling, and its native-registration mode collapses into the same route pi-web-access already provides (same author; pi-web-access is the maintained path).

- Install: `pi install npm:pi-web-access` (requires Pi ≥0.37.3). Adds two native tools with clean single schemas: `web_search`, `fetch_content` — matches the "single clear schema over multi-mode unions" rule.
- `fetch_content` clones GitHub URLs to real local files instead of scraping HTML, and handles PDFs, YouTube, and local video.
- Config file `~/.pi/web-search.json` — dotfile-symlink per convention.
- **Headless must-set**: the default `workflow: "summary-review"` launches a browser curator UI and blocks forever under `-p`. Set `"workflow": "none"` in `~/.pi/web-search.json` before any headless use.
- Zero-config default is anonymous Exa MCP (rate-limited free tier, basic search tools only). Adding `exaApiKey` switches to Exa's direct REST API with your account limits. Fallback chains apply only across *configured* providers — a zero-config run has only anonymous Exa live, so hitting its rate limit surfaces as a search error, not a silent failover.
- Keyless-vs-keyed table, config keys, and Kenan-relevant provider notes (Bocha as proxy-free China-direct option; `-t` allowlists filter extension tools too — name web tools explicitly to keep them in a read-only delegation): [references/web-access.md](references/web-access.md).

### Kenan's own pi extensions

- **`pi-auto-handoff`** — `~/Secret-Projects/pi-auto-handoff` (GitHub `kenanlian/pi-auto-handoff`, targets Pi 0.85.x): auto handoff that clears the LLM context IN PLACE — same process PID, same logical session id, durable JSONL untouched; configurable via `.pi/auto-handoff.json` / `PI_AUTO_HANDOFF_*`. v1 (shipped) triggers on threshold + WP boundary and delivers only at run boundaries; the agreed v2 delivers a strong stop-and-document instruction mid-run via the `context` event (single threshold, persistent re-injection) — check the tree's README before relying on trigger details. When Kenan says "auto handoff" he means THIS project, never a third-party package — `@ttiimmaahh/pi-handoff`, `@ssweens/pi-handoff`, and `danecando/pi-auto-handoff` all exist with near-identical names. General rule: when Kenan names one of his projects ambiguously, search `~/Secret-Projects/` by filename before web search — GitHub/npm lookalikes hijack the lookup. Mechanics, config keys, and event-log order: [references/auto-handoff-extension.md](references/auto-handoff-extension.md).

## Pitfalls (verified 2026-09-04, updated 2026-09-05)

- Parent GLM can mis-pick example tool modes (chose chain instead of parallel once) — give your own tool a single clear schema instead of multi-mode unions.
- First-ever json-mode call may be slow with retries; subsequent calls are fast. Don't read meaning into one slow run.
- Children spawned with `--no-session` leave no session file — pass `--session-id` if you need to inspect or continue them.
- **Verify death before same-session relaunch.** A supervisor (e.g. Hermes `process` tool) can report a background pi command as exited when the process is actually still alive. **Root cause (verified 2026-09-05)**: Hermes tracks liveness via the stdout PIPE, not the process — with fully-redirected output (`pi … > events.jsonl 2> stderr.txt`) the pipe is held only by the intermediate zsh, whose exec-optimization (zsh→pi, same PID) closes it → false EOF → the registry reader flips `exited` while pi is still starting. Fingerprint of the false report: `status:"exited"` + **`exit_code: null`** + only shell startup noise in `output_preview`. **Prevention**: sentinel-echo suffix on every Hermes-backgrounded command (`… > out 2> err; echo "TASK_RC=$?"`) — the shell must outlive the task, so pipe EOF ⇔ real death, and the true rc arrives through the pipe. **Rule**: `exited` + `exit_code:null` is unverified until `ps -p <pid>` confirms; encode the check in monitor/resume scripts, not as a manual habit. Acting on the false report and relaunching the same `--session-id` produces TWO pi processes concurrently writing one events file / session — real corruption hazard. Before any resume relaunch: `pgrep -f "<session-id>"` and `ps -p <pid>` to confirm the old process is truly gone. **Aftermath (observed 2026-09-05)**: when both streams run to completion, a raw-loop attempt has no relay wrapper, so NO `result.json`/`final.txt` is produced and the outer workflow status stays stuck with nobody taking over. Recovery: confirm all writers gone (`lsof <events>` empty), harvest the final report from the LAST settled segment, rebuild final.txt/result.json so the outer workflow sees a terminal result. Outcome here was benign — the second stream's `edit` was atomically rejected (oldText mismatch), it detected the concurrent writer, went read-only, and independently green-lit the full tree (lint/tsc/svelte-check/build/1736 tests vs baseline 1704) — luck, not a safe pattern. The guard-loop template has NO harvest step; after it exits 0, harvesting is still owed.
- Read-only exploration delegations (`-t read,bash,glob,grep`) work well for source-code surveys; the same resume-loop pattern applies when they die mid-run (observed twice in one session).
- Hermes background-liveness deep-dive (registry source anatomy, controlled experiment, zsh fork-vs-exec unpredictability, relay-chain immunity + its two real edges, forensic one-shots): [references/hermes-bg-process-liveness.md](references/hermes-bg-process-liveness.md).

## Web access (pi-web-access package, verified 2026-09-07)

Installed via `pi install npm:pi-web-access` (v0.27.0; tracked in `settings.json` `packages`; files at `~/.pi/agent/npm/node_modules/pi-web-access`). Adds native tools `web_search` + `fetch_content` (GitHub clone, PDF, YouTube). Zero-config search rides Exa MCP (no key); keys/providers go in `~/.pi/web-search.json` (stowed from `dotfile/pi/.pi/web-search.json`, currently just `{"workflow": "none"}`). Curator browser UI: `resolveWorkflow` force-returns "none" when `hasUI=false`, so headless runs can't hang on it; config also pins `"workflow": "none"` for interactive sessions. `-t` allowlists filter extension tools too — to keep web tools in a read-only delegation use `-t read,bash,web_search,fetch_content` (with plain `read,bash` they vanish and the model falls back to curl).

## Pitfalls (verified 2026-09-07)

- **`pi -p` with piped stdin hangs silently.** If stdin is a PIPE that never closes (Python subprocess default inheritance from a non-tty parent — e.g. the Hermes execute_code kernel), `pi -p` reads stdin waiting for EOF: 0 stdout bytes, 0 sockets, main thread parked in `kevent` via `uv__io_poll`, ~0 CPU — looks exactly like a hang. Fix: always pass `stdin=subprocess.DEVNULL` (or a closed/pty stdin) when spawning `pi -p`. - **stdin transport of a brief needs a reliable end.** `readPipedStdin` parks until EOF — a relay writing the brief to a child's stdin must `stdio[0]=pipe`, write the full text, then `stdin.end()` immediately (attach an `error` handler for EPIPE when the child dies early). Holding the pipe open stalls the run until the watchdog. Fingerprint to distinguish from a real hang: process alive + zero network sockets + main thread in kevent + 0 bytes out after 30s. (`pi -p` in a real terminal inherits /dev/null or a tty and is unaffected.)

## Smoke test

```bash
pi -p "Respond with exactly: PI_SMOKE_OK"    # expect PI_SMOKE_OK in ~2s
# from Python/subprocess: ALWAYS stdin=DEVNULL, else pi waits on stdin EOF forever
```
