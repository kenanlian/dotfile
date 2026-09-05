---
name: feishu-messaging
description: Use when sending Feishu messages/@-mentions via feishu.py.
---

# Feishu messaging via feishu.py

`~/.hermes/scripts/feishu.py` is the local CLI for sending Feishu messages and
@-mentions as this machine's bot identity (Hermes "小龙"). Credentials are read
automatically from `~/.hermes/.env` (FEISHU_APP_ID / FEISHU_APP_SECRET) — no
code changes needed.

## Commands

```bash
# Discover contacts (mines this profile's session DB for mention records)
python3 ~/.hermes/scripts/feishu.py contacts --scan            # auto: $HERMES_HOME or default
python3 ~/.hermes/scripts/feishu.py contacts --scan --profile executor

# Send a message with @-mention (contact name or raw ou_ id)
python3 ~/.hermes/scripts/feishu.py send --chat MISC --at 华生 --text "你好"
python3 ~/.hermes/scripts/feishu.py send --profile executor --chat MISC --at 华生 --text "你好"
```

- `--chat` accepts a fuzzy group name, an `oc_` chat_id, or an `omt_` thread id.
- `--at` may repeat; accepts names from the profile's `feishu_contacts.json` or `ou_` open_ids.
- Success output: `send: 0 message_id=om_...` plus an `identity: cli_...` line and resolved mentions.

## Multi-profile (since 2026-08-31)

Sending identity follows the profile: `--profile <name>` (highest priority) or
`$HERMES_HOME` auto-detected inside a profile's own session (just omit --profile
there). Credentials and `feishu_contacts.json` are read from the resolved
profile root, so each profile has its OWN contact list and open_id view.

Known contacts per profile (as of 2026-08-31, MISC group):

- default profile: 小龙 (self), 华生 `ou_4c5fa...`, 柯楠 `ou_1923...`
- executor profile (小龙's own identity, `cli_aa1ff7618cf99beb`):
  华生 `ou_e4e81f9f3ce308da4b0464b596ed3048`, 柯楠 `ou_19234927e3331a9e1433c9a81dbf7aa1`

Don't hardcode these — run `contacts --scan` per profile and trust each
profile's own result.

## Pitfalls

- **回复进话题需根消息 om_ id**：`omt_` thread id 不能直接传给 reply API（报 invalid open_message_id）。若 channel_directory.json 没收录该 thread，需从消息历史 API 找根消息 —— 但它需要 `im:message.group_msg` 权限，当前应用没有。兜底：直接 send 到群的 oc_ id（话题群内会落为新话题，@ 提及仍生效），或依赖会话自身回复。
- **send 的 payload 从不使用 thread_id**：feishu.py 里 thread_id 仅用于打印，`--chat omt_...` 只是查目录拿 chat_id，不会真的回复进话题。
- **open_id is per-app**: the same user/bot has DIFFERENT open_ids under
  different Feishu apps. An ID quoted by a remote bot about itself refers to
  its own app's view and may differ from the ID valid for our app. Never
  conclude an ID is "wrong" just because mention metadata shows another one.
  IDs in `feishu_contacts.json` are the ones valid for our app — trust those.
- Bot-to-bot mentions only wake the other bot if it opted in (e.g.
  FEISHU_ALLOW_BOTS=mentions). Waking is not guaranteed by sending alone.
- `contacts --scan` only adds names with exactly one distinct ou_ across the
  session DB (ambiguity guard); re-run it after new group activity.
- **Never copy contacts between profiles**: each profile's `feishu_contacts.json`
  holds IDs valid only for that profile's app. A name resolving in one profile
  may be absent (or map to a different ou_) in another — re-scan inside that
  profile.

See references/openid-per-app.md for the concrete two-ID case observed in the
  MISC group.