# Feishu Bot-to-Bot Connectivity (verified 2026-08-31)

Scenario: two Hermes profiles, each behind its own Feishu app/bot, share a
group with the user; bot A must see (and optionally react to) bot B's
messages.

## The three gates (all default OFF)

### Gate 1 — Feishu platform permissions (per receiving app)
Default: bots do NOT receive other bots' messages via `im.message.receive_v1`
(anti-loop design). Scopes that open it (pick one):

| Scope | Receives |
|---|---|
| `im:message.group_at_msg.include_bot:readonly` | group messages from users AND other bots that @ this bot |
| `im:message.group_msg.include_bot:read` | ALL group messages from users and other bots (no @ needed; more sensitive) |
| `im:message.group_bot_msg:readonly` | messages from other bots in the group |

Add the scope in the Feishu Open Platform console → Permissions, then
**publish a new app version** — scopes do nothing until released.

### Gate 2 — Hermes adapter admission
`plugins/platforms/feishu/adapter.py` `_admit()`: bot senders are rejected
with `bots_disabled` unless `feishu.allow_bots` is `mentions` or `all`
(env bridge: `FEISHU_ALLOW_BOTS`).

```bash
hermes config set feishu.allow_bots mentions   # peer must @ us
hermes config set feishu.allow_bots all        # every peer bot message
```

### Gate 3 — the mention itself
In `mentions` mode (and whenever the group's `require_mention` is on), the
peer bot must actually @ the receiving bot in the message text. Hermes also
provides `self_echo` protection (own messages never re-enter).

## Known platform pitfall: streaming-card @-mentions

A Feishu streaming-card message that adds `@bot` via PATCH may deliver ZERO
`im.message.receive_v1` events to the mentioned bot; the same content sent
as a native post message with the @ at creation delivers reliably
(github.com/baileyh8/hermes-feishu-streaming-card issue #162, tested
2026-07). If bot-to-bot pings silently fail, check whether the sender's
gateway uses streaming cards, and switch that chat to native messages.

## Recommended orchestrator/executor wiring

- Executor → orchestrator: executor @-mentions the orchestrator bot at
  milestones only; orchestrator side runs `allow_bots: mentions`.
- User → both: normal user messages always reach both bots (subject to each
  bot's group policy / `require_mention` settings).
- Keep at least one side on `mentions` to make an echo loop impossible.

## Setup checklist

1. Create a NEW Feishu self-built app per profile (never share credentials
   between profile gateways).
2. Enable bot capability; subscribe `im.message.receive_v1`; use the
   WebSocket (persistent connection) mode.
3. Add `im:message.group_at_msg.include_bot:readonly` (+ optionally
   `im:message.group_msg.include_bot:read`); publish a new version.
4. Put the new app's ID/secret into the new profile's `.env`
   (FEISHU_APP_ID / FEISHU_APP_SECRET), replacing the cloned values.
5. `executor gateway start`; verify the bot joins and receives user DMs.
6. Create the shared group (user + both bots); set
   `hermes config set feishu.allow_bots mentions` on the RECEIVING side.
7. End-to-end test: have the executor post a message @-mentioning the
   orchestrator bot and confirm the orchestrator session wakes.
