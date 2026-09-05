---
name: feishu-messaging
description: Use when @-mentioning Feishu users or looking up open_ids.
---

# Feishu Messaging Operations

Programmatic Feishu messaging beyond `hermes send`: @-mentioning users,
resolving user IDs, and inspecting chats/threads via the lark-oapi SDK.

## Sending messages

- Simple text/markdown to a chat or thread: `hermes send -t feishu:<chat_id>[:<thread_id>] "..."`
  (no LLM, no gateway needed). Thread delivery has known platform bugs —
  verify receipt before trusting `last_status:ok`.
- Quick scripted send with @-mentions (session-verified): `~/.hermes/scripts/feishu.py send --chat <群名|oc_...> [--at 名字|ou_...] --text "..."`.
  `--chat` fuzzy-matches names against `~/.hermes/channel_directory.json`; `--at`
  resolves names from `scripts/feishu_contacts.json` (open_id per app, so IDs are
  profile-scoped; `--profile <name>` or `$HERMES_HOME` picks the sending identity).
  The receipt prints the real `chat=` and a `mentions:` array — verify the target's
  `ou_` id appears there; a plain name in text does NOT mention anyone.
  **Caveat:** the receipt's `thread:` field is just the cached directory match, NOT
  the actual landing thread — ignore it. In topic-mode groups (`chat_mode: "topic"`, e.g.
  工作流优化) a root post auto-creates a new thread. To verify the true landing of a
  sent message, `GET /im/v1/messages/{message_id}` and read `chat_id` + `thread_id`.
- Message routing rule: coordination messages for a task (handoffs, digests,
  status) go to the group where that task's conversation lives, not a fixed ops group.

## @-mentioning a user in a group

Plain text like `@小龙` does NOT trigger a mention — you need the target's
**open_id**, embedded as `<at user_id="ou_..."></at>` in the message body.

Two message formats both work (session-verified via raw REST):

- **`msg_type: "text"`** (simplest): the `text` field may contain inline
  `<at user_id="ou_..."></at>` tags. Sent via
  `POST /open-apis/im/v1/messages?receive_id_type=chat_id` with a
  tenant_access_token, the response `mentions` array confirms real mentions
  (look for the target's `ou_` id there — that is the acceptance check).
- Structured `post` messages with `<at>` elements in rich-text paragraphs.

Multiple `<at>` tags in one text message are fine (e.g. mention the target
plus the bot itself). Bots and humans are mentioned identically via open_id.

### Resolving open_id (no member-list scope needed)

The bot app currently lacks `im:chat.members:read` (chat member list returns
error 99991672). The working path is **scanning group message history** with
`im.v1.message.list` (scope already granted):

1. Run the script `scripts/resolve_open_ids.py` (see below) against a chat.
2. It prints every human sender's open_id plus their recent message previews
   so you can identify the person by name/content.
3. If the target has never posted in a bot-visible chat, try the **local
   session-DB fallback** before asking anyone (see below).
4. Last resort: ask them to send one message, or ask 柯楠 to grant
   `im:chat:readonly` / `im:chat.members:read` for direct member lookup.

### Local session-DB fallback (no API call, works for never-posted targets)

Inbound Feishu messages land in `~/.hermes/state.db` with mention metadata
inlined into the text as `[Mentioned: Name (open_id=ou_...)]`. If 柯楠 (or
anyone) ever @-mentioned the target in any chat this bot saw, a plain SQL
search finds their open_id even when they never posted themselves:

```sql
SELECT s.chat_id, s.display_name, m.timestamp, substr(m.content,1,300)
FROM messages m JOIN sessions s ON m.session_id = s.id
WHERE m.content LIKE '%<name>%' ORDER BY m.timestamp DESC;
```

Parse the `open_id=ou_...` out of the `[Mentioned: ...]` marker. This is how
小龙's open_id was recovered after the member-list API was denied.

### The bot's own open_id

`GET https://open.feishu.cn/open-apis/bot/v3/info` with the
tenant_access_token returns the bot's `open_id` (needed when telling other
bots how to @ us). Raw REST via urllib works fine — the lark-oapi SDK is
not required for token/send/info calls.

### Known IDs (session-verified)

See `references/known-ids.md` — bot 华生, bot 小龙, and common group chat_ids.

```
~/.hermes/hermes-agent/venv/bin/python <skill-dir>/scripts/resolve_open_ids.py <chat_id> [--thread <thread_id>]
```

Credentials are read from `~/.hermes/.env` (`FEISHU_APP_ID`/`FEISHU_APP_SECRET`).

## lark-oapi SDK quirks (version pinned 1.6.8 in the Hermes venv)

- The SDK is only importable from `~/.hermes/hermes-agent/venv/bin/python`
  (system python3 lacks it).
- Class names: `ListChatRequest` (chats the bot is in), `GetChatMembersRequest`
  (members), `ListMessageRequest` (history). There is NO `ChatListRequest`.
- Resources live flat on `client.im.v1`: `chat.list`, `chat_members.get`
  (NOT `chat.members_get`), `message.list`.
- History listing: `container_id_type` is `'chat'` or `'thread'`; `thread_id`
  looks like `omt_...` and works as a container_id to read one topic thread.
- `Sender` fields are `id`, `id_type`, `sender_type` (bots: `id_type='app_id'`,
  humans: `id_type='open_id'`); there is no `.type` attribute.
- System events (group created / renamed / invite) arrive as `text` messages
  with a `template` field and empty sender — filter them out when scanning.
- Builders paginate via `page_token` + `has_more` on `resp.data`.

## References

- `references/open-id-resolution.md` — full session-verified transcript of the
  @-mention resolution workflow and API responses.
- `references/known-ids.md` — verified open_ids (华生 bot, 小龙 bot) and chat_ids.
