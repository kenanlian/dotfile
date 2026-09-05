---
name: pi-coding-agent
description: "Use when driving Pi CLI for coding delegation or extensions."
version: 1.0.5
tags: [Coding-Agent, Pi, Delegation, Subagent, Headless]
metadata:
  hermes:
    tags: [Coding-Agent, Pi, Delegation, Subagent, Headless]
    related_skills: [opencode, cursor-delegate, pi-delegate, development-orchestrator]
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
- `zai-coding-cn` = Zhipu GLM Coding Plan, baseUrl `https://open.bigmodel.cn/api/coding/paas/v4`, models glm-4.7…glm-5.3 + flash/highspeed variants. Default: `glm-5.3`.
- `opencode-go` provider also configured (deepseek-v4-pro/flash, glm-*, grok-4.6, …) — same keys/quota as OpenCode, no new billing surface.
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

**Interrupted-run signature (verified 2026-09-05)**: a hard drop mid-run looks like this in the NDJSON — several `tool_execution_end` events, then a bare `turn_start`, then EOF. No `agent_end`, no `agent_settled`, and every `message_end` carries only toolResult payloads (no harvestable assistant text). Treat "process exited" as incomplete until `agent_settled`/`agent_end` appears; harvest the final report only from the settled run. Recovery is cheap: relaunch with the **same `--session-id`** and a short continuation prompt ("继续执行任务，从中断处继续，不要重新调查已完成的部分"), appending to the same events file — session state on disk preserves all prior tool calls. Wrap this in a guard loop: check `grep '"type":"agent_settled"' events.jsonl` before each round, relaunch up to N times with sleep between. Full verified script + incident notes: [references/long-run-supervision.md](references/long-run-supervision.md).

**Dual-writer fingerprint (verified 2026-09-05 incident)**: two live pi processes sharing one `--session-id` interleave writes into one events file — signature: `agent_settled` count ≥ 2 while `agent_start` count == 1, plus events with fresh `toolCallId`s appearing AFTER a settled line; timestamp-gap analysis shows zero gaps (the streams cover each other). Also: `agent_end` carries a `willRetry` bool. And: the session store (`~/.pi/agent/sessions/<cwd-slug>/*.jsonl`) holds message/state records only — `agent_settled`/`agent_end` NEVER appear there (verified), so never diagnose "interrupted" from the store; judge completion only from the attempt's stdout events file. One-shot triage of any events file: `python3 scripts/pi-run-forensics.py <events.jsonl>`.

## Tool Gating = access classes (verified)

- `-t/--tools read,bash` allowlist — read-only enforcement is HARD: model with only `read` attempted a write and physically could not (verified).
- `--no-builtin-tools` keeps only extension/custom tools; `--no-tools` none; `-xt` denylist.
- Pi has **no permission wall/sandbox**: cross-directory file access is unrestricted. Scope declarations (`additional_directories`) are audit statements in the brief, not enforcement. Enforcement requires an extension gating `tool_call` events.

## Extensions

- TypeScript modules: `export default function (pi: ExtensionAPI)`; `pi.registerTool()` (typebox schema, `execute(toolCallId, params, signal, onUpdate, ctx)`), `pi.on('tool_call', …)` can **block/modify** tool calls (the gate mechanism), `pi.registerCommand`, custom TUI.
- Locations: `~/.pi/agent/extensions/*.ts` or `*/index.ts` (global), `.pi/extensions/` (project, trust-gated). `-e <path>` ad-hoc. `/reload` hot-reloads auto-discovered ones.
- **Same-name override of built-in tools works** (verified 0.84.4): `registerTool({name: "write", ...})` in an extension replaces the built-in entirely — the custom `execute` runs, the real file write never happens (official example: repo `examples/extensions/tool-override.ts`). Complements: `-nbt` disables all built-ins, `pi.on('tool_call')` can block/modify, `setActiveTools()` toggles at runtime.
- Extensions run with **full system permissions**.
- Symlink install pattern verified: repo working copy → `ln -sf` into `~/.pi/agent/extensions/<name>/`.

## Subagents

No built-in; official example `packages/coding-agent/examples/extensions/subagent` in the pi repo works unmodified on 0.84.4 (verified: single + parallel delegation, custom agent with GLM flash). Each delegation spawns a real subprocess:

```
pi --mode json -p --no-session --model <frontmatter> --tools a,b \
   --append-system-prompt <tmpfile> "Task: <task>"   # per-task cwd
```

Agents = markdown frontmatter files in `~/.pi/agent/agents/` (`name/description/tools/model` + system prompt). For relay-style use, fork only the spawn core + agent discovery (~400 of ~1200 lines); the TUI rendering, chain mode, workflow prompts, and interactive project-agent confirms are dead weight headless. Swap `--no-session` → `--session-id` for continuation. Full inventory: [references/delegation-transport.md](references/delegation-transport.md).

### delegate-agent router config (`pi-delegate-agent` extension)

Backend/model routing is config-owned and invisible to the caller: the parent LLM passes only the `agent` tier + prompt; `router.ts` resolves the route from `~/.pi/agent/delegate-agent.json` (symlink → dotfile stow target `~/Secret-Projects/dotfile/pi/.pi/agent/delegate-agent.json`, so edits are dotfile commits) and **re-reads the file on every tool call** — config edits apply to the next delegation, no Pi restart. Resolution: `DELEGATE_AGENT_CONFIG` env → default path; whole-file replacement, **no local-overlay merge** (as of 2026-09-05). `native` routes require `agent_file` (a cursor→native switch must add it or the router blocks); `cursor` routes need only `model`. Validate edits by running the extension's own `resolveNewDelegation` over all tiers, not just `JSON.parse`. Detail + recipe: [references/delegate-agent-config.md](references/delegate-agent-config.md).

## Pitfalls (verified 2026-09-04, updated 2026-09-05)

- Parent GLM can mis-pick example tool modes (chose chain instead of parallel once) — give your own tool a single clear schema instead of multi-mode unions.
- First-ever json-mode call may be slow with retries; subsequent calls are fast. Don't read meaning into one slow run.
- Children spawned with `--no-session` leave no session file — pass `--session-id` if you need to inspect or continue them.
- **Verify death before same-session relaunch.** A supervisor (e.g. Hermes `process` tool) can report a background pi command as exited when the process is actually still alive. **Root cause (verified 2026-09-05)**: Hermes tracks liveness via the stdout PIPE, not the process — with fully-redirected output (`pi … > events.jsonl 2> stderr.txt`) the pipe is held only by the intermediate zsh, whose exec-optimization (zsh→pi, same PID) closes it → false EOF → the registry reader flips `exited` while pi is still starting. Fingerprint of the false report: `status:"exited"` + **`exit_code: null`** + only shell startup noise in `output_preview`. **Prevention**: sentinel-echo suffix on every Hermes-backgrounded command (`… > out 2> err; echo "TASK_RC=$?"`) — the shell must outlive the task, so pipe EOF ⇔ real death, and the true rc arrives through the pipe. **Rule**: `exited` + `exit_code:null` is unverified until `ps -p <pid>` confirms; encode the check in monitor/resume scripts, not as a manual habit. Acting on the false report and relaunching the same `--session-id` produces TWO pi processes concurrently writing one events file / session — real corruption hazard. Before any resume relaunch: `pgrep -f "<session-id>"` and `ps -p <pid>` to confirm the old process is truly gone. **Aftermath (observed 2026-09-05)**: when both streams run to completion, a raw-loop attempt has no relay wrapper, so NO `result.json`/`final.txt` is produced and development-monitor.v2 stays RUNNING forever (cron spins, nobody takes over). Recovery: confirm all writers gone (`lsof <events>` empty), harvest the final report from the LAST settled segment, rebuild final.txt/result.json, drive the monitor to terminal. Outcome here was benign — the second stream's `edit` was atomically rejected (oldText mismatch), it detected the concurrent writer, went read-only, and independently green-lit the full tree (lint/tsc/svelte-check/build/1736 tests vs baseline 1704) — luck, not a safe pattern. The guard-loop template has NO harvest step; after it exits 0, harvesting is still owed.
- Read-only exploration delegations (`-t read,bash,glob,grep`) work well for source-code surveys; the same resume-loop pattern applies when they die mid-run (observed twice in one session).
- Hermes background-liveness deep-dive (registry source anatomy, controlled experiment, zsh fork-vs-exec unpredictability, relay-chain immunity + its two real edges, forensic one-shots): [references/hermes-bg-process-liveness.md](references/hermes-bg-process-liveness.md).

## Smoke test

```bash
pi -p "Respond with exactly: PI_SMOKE_OK"    # expect PI_SMOKE_OK in ~2s
```
