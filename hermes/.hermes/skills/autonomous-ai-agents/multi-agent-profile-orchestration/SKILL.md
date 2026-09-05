---
name: multi-agent-profile-orchestration
description: "Use when coordinating multiple Hermes agent profiles."
version: 1.0.0
tags: [multi-agent, profiles, orchestration, feishu, bot-to-bot, context-isolation]
---

# Multi-Agent Profile Orchestration

## When to Use

- The user needs a second (or Nth) Hermes identity with its own durable process, profile state, credentials, tools, or messaging bot.
- Work must continue independently of the orchestrator session or must be isolated at the profile/process boundary, not merely at the conversation-context boundary.
- Connecting a new profile to its own messaging bot (especially Feishu) and wiring **bot-to-bot** communication between profiles in a shared group.
- Bootstrapping a fresh profile that inherits tools/credentials but NOT skills or memory from an existing profile.

Do **not** introduce another profile merely to keep one continuous orchestrator's context clean. For bounded evidence collection while the parent session remains alive, prefer `delegate_task`; for deterministic polling, prefer a script-gated Cron owned by the orchestrator profile.

## Core Model

Orchestrator + executor split:
- **Orchestrator** (e.g. `default` profile): owns product intent, decisions, final acceptance, and user rapport.
- **Executor** (dedicated profile): is justified when execution needs an independent durable identity/process or separate credentials and must survive outside the orchestrator's active turn.
- Messaging is a human-visible coordination channel, not proof that another bot's Agent session was created.

### Choose isolation by lifecycle, not by log volume

- **Active continuous parent + bounded reasoning-heavy check:** use a subagent; only its final summary enters the parent context.
- **Mechanical check:** let the parent call tools directly and persist verbose evidence to disk.
- **Long-lived work that must survive parent/session loss:** use Cron, a durable background process, or an explicit executor profile.
- **Project development phase:** monitoring a Cursor/Codex/OpenCode Relay and performing behavior acceptance are separate phases. A polling mechanism may end when the Relay reaches a terminal state; the continuously running acceptance orchestrator can then delegate subagents without requiring a second profile.

This distinction prevents an unnecessary chain of orchestrator → executor → messaging mention → orchestrator when a single fresh/continuous orchestrator plus subagents is sufficient.

## Bootstrapping a Clean Executor Profile (verified workflow)

See `references/executor-profile-bootstrap.md` for the full verified procedure. Key non-obvious facts:

1. `hermes profile create NAME --clone --no-skills` is **mutually exclusive** (CLI refuses). Workaround: `--clone`, then manually strip.
2. `--clone` copies config.yaml, `.env`, SOUL.md, skills, **and memories** — but NOT state.db/sessions. You must truncate `memories/MEMORY.md` and `memories/USER.md` yourself.
3. `rm -rf skills` alone is not enough: `hermes update` re-seeds bundled skills. Place the `.no-bundled-skills` marker file in the profile root (same one `--no-skills` writes).
4. Even with the marker, `sync_skills()` force-seeds the **essential `hermes-agent` skill** (self-knowledge) into every profile — this is by design; do not fight it, and do not report it as a leak.
5. Cloned `.env` carries the SAME messaging-app credentials as the source profile. Two gateways on one Feishu app fight over the WebSocket long connection — each profile needs its own app before its gateway starts.
6. Verify clean state by running a one-shot chat asking about its skills/memory, then `sessions export --session-id <id> --format jsonl -` and parsing the last assistant message (details in the reference).

## Feishu Bot-to-Bot Connectivity

Three independent gates, all off by default; see `references/feishu-bot-to-bot.md` for scopes, commands, and pitfalls:

1. **Platform permissions** on the receiving app (`im:message.group_at_msg.include_bot:readonly` for mention-only, or `im:message.group_msg.include_bot:read` for all group messages) + **publish a new app version** so they take effect.
2. **Hermes adapter admission**: `feishu.allow_bots` config (bridged to `FEISHU_ALLOW_BOTS`), values `none` (default → `bots_disabled`) / `mentions` / `all`.
3. **Mention requirement**: in `mentions` mode the peer bot must explicitly @ the receiving bot. Streaming-card messages that @ via PATCH may NOT deliver an event to the mentioned bot — native post messages carrying the @ at creation are the reliable path (documented platform limitation).

Recommend `mentions` mode for orchestrator/executor: the orchestrator is only interrupted when the executor explicitly reports.

## Project-development boundary（current preference）

The former default—executor intake + shared Relay Watchdog + no-agent digest + bot mention back to the orchestrator—is **retired as a project-development default**. It proved that send success, a visible mention, and Agent wake are separate links, while also adding cross-profile state, routing, and cache-expensive wakeups.

For 柯楠's development workflow, keep the phases separate:

1. **Coding phase:** the orchestrator delegates Cursor/Codex/OpenCode and uses a task-scoped, script-gated Cron for durable progress observation. Healthy checks must not invoke an Agent.
2. **Transition:** when the Relay becomes actionable or terminal, start a fresh orchestrator from compact durable task state; the coding monitor's responsibility ends.
3. **Behavior acceptance:** one continuous orchestrator owns scenario design, final judgment, rework, and user communication. It may directly run mechanical checks and delegate bounded heavy-context scenarios to subagents.
4. **Rework:** only when a Coding Agent is active again should a new development-monitoring Cron exist.

Use an executor profile in this workflow only when explicitly requested or when a validation truly requires independent durable execution beyond the acceptance orchestrator's lifetime.

## Pitfalls

- **Seen ≠ woken** (verified failure 2026-09-01): a no_agent cron's `@华生`
  mention can pass send-receipt validation AND be marked seen by the receiving
  gateway, yet never create an agent session — the receiving side stays silent
  for hours. Send success, gateway-seen, and agent-wake are three independent
  links; do not build a wake path on bot mentions.
- **Same-app credentials across profiles** — see bootstrap fact 5; the failure mode is silent WebSocket connection stealing between gateways.
- **Permissions added but not published** — Feishu scopes only take effect after a new app version is released.
- **Bot-loop risk** — two bots with `allow_bots: all` and no mention requirement can echo-loop; keep at least one side on `mentions`.
- **Assuming the platform relays bot messages by default** — it deliberately does not (anti-loop design); every gate above must be opened explicitly.

## Post-Start Cleanup for a Cloned-Profile Gateway (verified 2026-08-31)

After replacing Feishu credentials and starting the new gateway, the clone still carries the source profile's OTHER platform wiring. Three cleanup items, all hit in one session — details and exact commands in `references/gateway-post-start-cleanup.md`:

1. **Cloned non-Feishu platforms fight over credentials** — e.g. QQBot app ID "already in use by the 'default' profile gateway". Disable per platform via `platforms.<name>.enabled: false` in config.yaml (**not** `channels.<name>.enabled` — wrong key is silently ignored) and clear the cloned creds in `.env`.
2. **Stale home_channel lives in TWO places** — `platforms.feishu.home_channel` in config.yaml AND `FEISHU_HOME_CHANNEL` in `.env` (env wins when non-empty; clearing only one leaves the ghost). Symptom on every restart: `Home-channel startup notification failed ... [230002] Bot/User can NOT be out of the chat.`
3. **`require_mention` is inherited from the clone source** — if the source had `require_mention: false`, the new bot answers EVERY group message and competes with the orchestrator bot. Set `platforms.feishu.require_mention: true` on an executor bot so it only speaks when @-mentioned.

Also: `probe_bot(app_id, app_secret, domain)` from the Feishu adapter verifies credentials without starting the gateway.

## References

- `references/executor-profile-bootstrap.md` — full clean-profile bootstrap procedure.
- `references/gateway-post-start-cleanup.md` — cloned-gateway platform cleanup.
- `references/feishu-bot-to-bot.md` — bot-to-bot scopes, adapter gates, mention quirks.
