# Known Feishu IDs (session-verified)

Open_ids are stable per tenant; verify with a real mention (check the
response `mentions` array) before relying on one for the first time.

## Bots

| Name | open_id | Notes |
|---|---|---|
| 华生 (this Hermes bot, app `cli_aafc044f1238dd2e`) | `ou_4c5fa38a012bf260485ed24c499482dd` | via `GET /bot/v3/info` |
| 小龙 (another agent bot, receives mentions via `FEISHU_ALLOW_BOTS=mentions`) | `ou_519601a323745f456d944f5c239a831c` | recovered from历史消息 `[Mentioned:]` markers |

## Group chats

| Name | chat_id |
|---|---|
| MISC | `oc_92b4d0a3dca4b797cb6383da79c2cc00` |
| 工作流优化 | `oc_6d6d03fbfaf0f2225e3634da59b8fcd2` |
| Card Workspace 开发 | `oc_ea22a023a1ce3c13071f808350dafaeb` |
| Card-Workspace项目 | `oc_f22f1e02dfa1409f0e9d5fad4594b46c` |
| Home (DM, 柯楠) | `oc_85b79ea7ce882e146d0682321350455d` |

## Human users

| Name | open_id |
|---|---|
| 柯楠 | `ou_19234927e3331a9e1433c9a81dbf7aa1` |

## Notes

- Bot-to-bot mention: both sides need `FEISHU_ALLOW_BOTS=mentions` (or
  equivalent) or the receiving gateway silently drops the message.
- The app lacks `im:chat.members:read`; member lookup returns 99991672.
  Use `scripts/resolve_open_ids.py` (API history) or the state.db SQL
  fallback described in SKILL.md.
