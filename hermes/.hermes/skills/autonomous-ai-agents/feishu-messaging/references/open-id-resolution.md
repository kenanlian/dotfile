# @-Mention Resolution in Feishu Groups — session-verified notes (2026-08-31)

Task: 柯楠 asked 华生 to @-mention "小龙" in the 工作流优化 group.
Outcome: mention was not deliverable because the target had never posted in
any bot-visible chat (no open_id obtainable); the resolution *workflow* below
was fully validated.

## Why plain text fails

Feishu mentions require a `post`-type message whose content JSON contains
`{"tag": "at", "user_id": "ou_...", "user_name": "..."}` elements. The Hermes
adapter's `send()` path builds post payloads from markdown only, so a raw
`@name` in text is never converted to an at element. Verified in
`plugins/platforms/feishu/adapter.py` (`_build_outbound_payload`,
`_send_raw_message`): to mention someone you must call the message API
directly with a hand-built post payload containing the at element.

## Open_id resolution paths, in order

1. **Chat member list** — `client.im.v1.chat_members.get(GetChatMembersRequest
   with member_id_type='open_id')`. FAILED for this app: error 99991672,
   requires one of `im:chat:readonly`, `im:chat`, `im:chat.group_info:readonly`,
   `im:chat.members:read`. Fix when needed: open the auth link in the error
   message (open.feishu.cn/app/<app_id>/auth?q=...) and grant one scope.
2. **Message history scan** — `client.im.v1.message.list` WORKS with existing
   scopes. Scan `container_id_type='chat'` for the group plus
   `container_id_type='thread'` for each `omt_...` topic; collect
   `sender.id` where `sender.id_type == 'open_id'`. System events (group
   created / renamed / invited) carry a `template` field and an empty sender —
   skip them. Bot messages have `id_type='app_id'` — skip.
3. **Ask the user** — if the target has never posted, the cheapest path is to
   have them send one message in any bot-visible chat, then rescan.

## Verified API shapes (lark-oapi 1.6.8, Hermes venv)

- Chats the bot belongs to: `imv1.ListChatRequest.builder().page_size(50)` →
  `client.im.v1.chat.list(req)`; items have `.chat_id` and `.name`.
- History: see `scripts/resolve_open_ids.py`.
- Sender object fields: `id`, `id_type`, `sender_type`, `tenant_key`,
  `sender_name` (often None). No `.type` attribute.

## Groups and IDs discovered this session

- 工作流优化: `oc_6d6d03fbfaf0f2225e3634da59b8fcd2`
- Card Workspace 开发: `oc_ea22a023a1ce3c13071f808350dafaeb`
- MISC: `oc_92b4d0a3dca4b797cb6383da79c2cc00`
- 柯楠's open_id: `ou_19234927e3331a9e1433c9a81dbf7aa1`
