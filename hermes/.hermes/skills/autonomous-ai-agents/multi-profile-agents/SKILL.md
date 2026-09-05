---
name: multi-profile-agents
description: "Use when adding extra Hermes profiles as separate agents."
---

# 多 Profile 独立 Agent 配置（含独立飞书机器人）

## 何时使用
- 创建第二个及以后的 Hermes profile 作为独立 agent（独立身份进群、隔离重上下文，如 executor/编排分工）
- 为新 profile 配置**独立的**飞书机器人凭证
- 排查双网关互踢、QR 注册凭证丢失等问题

柯楠的典型动机：让执行代理吃掉监控 coding agent 进度、行为验证等重上下文工作，只向编排代理（default profile 的华生）汇报结论。bot 互听权限按需后补，不是建 bot 的前置条件。

## 已实测验证的工作流（2026-08-31）

### 1. 克隆并清理 profile
```bash
hermes profile create <name> --clone --description "..."
```
- `--clone` 与 `--no-skills` **互斥**；克隆带来 config.yaml、.env、SOUL.md、skills/、memories/（MEMORY.md、USER.md），**不带** state.db/sessions/历史。
- 要干净的记忆与 skills 时手动清理：
```bash
rm -rf <profile>/skills && touch <profile>/.no-bundled-skills   # 标记文件阻止 hermes update 同步捆绑 skills
> <profile>/memories/MEMORY.md; > <profile>/memories/USER.md
```
- 设计行为：即使有 `.no-bundled-skills` 标记，`hermes-agent` skill 仍会被强制种子（essential skill，见 hermes_cli/profiles.py 注释），保留即可。
- 验证：`<name> doctor`；再跑一轮 `<name> chat -q "..."`，用
  `<name> sessions export --session-id <id> --format jsonl -` 读回复（jsonl 必须 `-` 输出到 stdout；输出是单行 JSON：header + messages 数组）。

### 2. 凭证隔离（关键坑）
克隆的 `.env` 带着源 profile 的**同一套** FEISHU_APP_ID/SECRET。两个网关用同一个 app 会互踢 WebSocket 长连接。**必须在启动第二个网关之前替换飞书凭证**。模型 API keys 等其他凭证共用无妨。

### 3. 飞书扫码创建机器人
- 交互式：`hermes gateway setup` → Feishu/Lark → Reconfigure → "Scan QR code to create a new bot automatically"。SSH 远程下 ASCII QR 照常显示；也可把打印出的 URL 直接发给用户手机打开确认。
- 程序化（后台跑，把 QR URL 转发给用户扫）：
```bash
cd ~/.hermes/hermes-agent && HERMES_HOME=<profile目录> ./venv/bin/python -c \
  "from plugins.platforms.feishu.adapter import qr_register; import json; print(json.dumps(qr_register()))"
```
  - 必须用项目 venv 的 python（`~/.hermes/hermes-agent/venv/bin/python`），系统 python3 缺 yaml 等依赖。
  - **大坑：`qr_register()` 只返回凭证、不写盘**。持久化逻辑在 `interactive_setup()` 的 `save_env_value()` 里。直接调用时必须在**同一进程内**用 `hermes_cli.config.save_env_value('FEISHU_APP_ID', ...)` / `('FEISHU_APP_SECRET', ...)` 写入；**绝不要为防泄露而截断打印 secret**——进程退出后完整 secret 即丢失，只能去 open.feishu.cn 开发者后台「凭证与基础信息」重查（个人自建应用 secret 永远可查，这是兜底）。

### 4. 启动与后续
```bash
<name> gateway start && <name> gateway status
```
建群拉入用户与两个机器人。bot 互听（让两个 Hermes 互相看到消息）需要平台权限 + `feishu.allow_bots` 配置，详见 → references/feishu-bot-messaging.md

### 5. 启动后的克隆残留清理（2026-08-31 实测）
启动成功 ≠ 配置干净，克隆还会留下三处残留：
- **克隆的其他平台抢凭证**：QQBot 报 "app ID already in use by the 'default' profile gateway"。用 `platforms.qqbot.enabled: false` 禁用（注意是 `platforms.` 不是 `channels.`，后者无效），并清空 `.env` 里克隆的该平台凭证。
- **home_channel 残留两处**：config.yaml 的 `platforms.feishu.home_channel` + `.env` 的 `FEISHU_HOME_CHANNEL`，两处都要清；症状是每次重启报 `[230002] Bot/User can NOT be out of the chat`。
- **require_mention 被继承**：源 profile 若为 false，新 bot 会抢答群内所有消息；执行代理应设 `platforms.feishu.require_mention: true`（只被 @ 才说话）。
- 验证凭证可用 `probe_bot(app_id, secret, domain)`，无需启动网关。

完整命令与日志签名见姊妹 skill `multi-agent-profile-orchestration` 的 `references/gateway-post-start-cleanup.md`（两 skill 重叠，待 curator 合并）。

## 参考文件
- `references/feishu-bot-messaging.md` — 飞书 bot 消息权限矩阵、Hermes `allow_bots` 配置、bot-to-bot 事件投递的平台限制与已知坑；含直调飞书 OpenAPI 速查（thread 话题投递：thread_id 直投与 hermes send 三段式均 99992402，reply 根消息服务端可达但客户端可见性未解、receive_id_type 合法值、@bot 假提及陷阱、无成员权限时从消息历史提取 ID）
