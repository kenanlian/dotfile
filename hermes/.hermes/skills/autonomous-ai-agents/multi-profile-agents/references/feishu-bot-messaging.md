# 飞书机器人消息权限与 bot-to-bot 通信（2026-08-31 查证：官方文档 + 本机 adapter 源码）

## 平台层（飞书官方 im.message.receive_v1 事件文档）
默认 bot **收不到**其他 bot 发的消息（防死循环）。按需申请权限，**申请后必须发布新应用版本才生效**：

| 需求 | 权限 scope |
|---|---|
| 只收"其他 bot @ 我"（推荐起步） | `im:message.group_at_msg.include_bot:readonly` |
| 收群内所有用户+bot 消息（敏感权限） | `im:message.group_msg.include_bot:read` |
| 群内其他 bot 消息（不要求 @） | `im:message.group_bot_msg:readonly` |

## Hermes 网关层（plugins/platforms/feishu/adapter.py）
- 配置键 `feishu.allow_bots`：`"none"`（默认）/ `"mentions"` / `"all"`；config 加载时桥接到 `FEISHU_ALLOW_BOTS` env。
- `_admit()`（约 L4350）中 bot 发送者在 none 模式直接拒绝（reject reason `bots_disabled`）；mentions 模式还要求消息 @ 到本 bot。
- 配置：`hermes config set feishu.allow_bots mentions`
- 柯楠的 default profile 已是 `require_mention: false`（群内人类消息全可见）。

## 已知平台坑
- **流式卡片 + PATCH 补 @ 不触发事件**：bot A 用流式卡片发送再 PATCH 加 @，被 @ 的 bot 在 WebSocket 上收不到 im.message 事件；改用原生 post 消息创建时携带 @ 则可靠（hermes-feishu-streaming-card issue #162 有完整实测对照，v4.1.0 提供 `chats use-native CHAT_ID` 按群规避）。
- 飞书 bot 之间无法保证全自动接力（平台投递边界），关键接力用真人 @ 驱动更可靠。

## 双 agent 协作速查
执行代理只在关键节点 @ 编排代理发结论；编排代理上下文因此保持干净。互听配置是**可选增强**，在基础链路（各自能收人类消息、能发言）跑通后再补。

---

# 直调飞书 OpenAPI 速查（2026-08-31 实测）

绕过网关直接用 Python 操作飞书（发消息、查历史、定位用户/bot ID）时的已验证事实。

## 环境与认证
- 用项目 venv 的 python：`~/.hermes/hermes-agent/venv/bin/python`（系统 python3 缺 `lark_oapi` 等）。
- 裸调 API：先取 tenant_access_token `POST /open-apis/auth/v3/tenant_access_token/internal`（body 为 app_id/app_secret 的 JSON），再 `Authorization: Bearer <token>`。`.env` 里 `FEISHU_DOMAIN=feishu` 是**非 URL 值**，裸调时要自己用 `https://open.feishu.cn`。

## 发消息（POST /open-apis/im/v1/messages）
- **`receive_id_type` 合法值是 `chat_id`，不是 `chat`**——填 `chat` 一律 99992402 "field validation failed"，且错误信息很长，真正的违规字段在 `field_violations` 里。debug 时先打印完整 `field_violations`。
- 群消息：`receive_id_type=chat_id` + 群的 `oc_...`；payload `{receive_id, msg_type, content, uuid}`，content 是**再包一层 JSON 字符串**（text 类型 `content` 为 `{"text": ...}` 序列化后的字符串）。

## 话题（thread）内投递 —— 直投两条路都不通，可见性另有问题
- ❌ **`receive_id_type=thread_id` 直投话题 → 99992402 被拒**（实测）。之前 cron 线程级投递 `last_status:ok` 但消息不出现的根源就在这类静默/半静默失败。
- ❌ **`hermes send --to feishu:<chat_id>:<omt_thread_id>` 三段式目标同样 99992402**（2026-08-31 实测）——网关把三段式目标转成 thread_id create 路径，踩同一个坑。cron/看门狗**不要**用三段式话题目标，必须在脚本里自己走 reply API。根因：create API 的 `receive_id_type` 只接受 `[open_id,user_id,union_id,email,chat_id]`，`thread_id` 只在**转发**消息和**列表查询**（container_id_type）中合法。
- ⚠️ **reply 话题根消息：服务端落点正确 ≠ 客户端可见（未解决）**。2026-08-31 深度排查：reply 根消息后读回 `thread_id`/`parent_id`/`root_id` 全部正确、消息确实出现在 thread 容器列表里，与网关可见消息字段级 diff 完全同构（仅 ID/时间不同），但用户在客户端**始终看不到**。尝试过的变量：`msg_type` post/text、`reply_in_thread: true`——均不可见。网关自己可见的消息走 streaming-card/stream-consumer 管线，且 reply 锚点是**用户最新 inbound 消息**而非话题根消息；"reply 用户最新消息（纯 text、无 reply_in_thread）"这条复刻网关形态的测试当时发出成功但用户未及确认，**悬而未决**。下次继续时从这条测试的可见性入手，并考虑 streaming-card 管线差异。在解决前，把"reply 根消息"当作*服务端投递成功*的手段，不要向用户承诺客户端可见。

## @ 人与 @ bot
- `<at user_id="..." user_name="...">` 标签：@ 真人填其 `ou_` open_id 可生效；**填 bot 的 `cli_` app_id 会被飞书静默清空 user_id**，消息能发出、显示名字，但 `mentions` 数组为空——是假 @，被 @ 方不会收到通知。bot 没有 open_id（open_id 体系只属于人类用户）。
- @所有人：`user_id: "all"`（注意不是 `@_all`，`@_user_N`/`@_all` 是**收件解析**时的占位符语法，发送时不用）。

## 查群内 ID（当成员读取权限没批时）
- 群成员列表 `im:chat.members:read` 等权限默认没开（错误 99991672 会给出申请链接，可转给用户点开授权）。
- **绕过：翻群消息历史找发送者 ID**。`GET /open-apis/im/v1/messages?container_id_type=chat&container_id=oc_...`（分页 page_token）。`sender.id_type` 区分 `open_id`（人类）/ `app_id`（bot，`cli_...`）。注意：**别只筛 open_id**——另一个 bot 的消息带 app_id，会被漏掉。话题内消息用 `container_id_type=thread` + `omt_...`。
- 人类用户没有公开入口查 open_id；让目标用户在 bot 所在群发一条消息，再从历史提取，是最直接的办法。

## lark SDK 类名（1.6.8，跟直觉不一样）
- 群列表：`imv1.ListChatRequest`（不是 ChatListRequest），`client.im.v1.chat.list(req)`。
- 群成员：`imv1.GetChatMembersRequest`，走 **`client.im.v1.chat_members.get`**（不是 `chat.members_get`）。
- 消息列表：`imv1.ListMessageRequest`，`client.im.v1.message.list(req)`。Sender 对象没有 `.type`，用 `.id_type`/`.sender_type`。
- 遇到 AttributeError 先 `[n for n in dir(module) if 'X' in n]` 列真实类名。
