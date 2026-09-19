柯楠产品视觉：浅色为主、优秀暗色可备选；极简如 Otty 干净，以背景/灰阶分层替代大量边框；圆润小按钮、克制微交互、细腻质感。页面篇幅适中（Otty/VMark），忌 omp 式超长。Zed 硬朗工程风仅限需极度凸显工程精密感的产品。
§
个人项目开发：持久化到 ~/Secret-Projects/development-artifacts；项目根 `.dev` 用相对软链，两个仓库分别 commit/push；`initiatives/` 只读退役，计划放 `.dev/plan/`。Kanban 一项目一 board。
§
Chrome Profile `Hermes` 华生专用；browser_exec 可用。
§
Feishu 发消息/@人：~/.hermes/scripts/feishu.py send --chat 群名 --at 名字 --text；新联系人 contacts --scan。小龙=同机 executor profile（--profile executor），ALLOW_BOTS=mentions、@ 即唤醒。open_id 按应用隔离：我 ou_4c5fa38a012bf260485ed24c499482dd；柯楠 ou_19234927e3331a9e1433c9a81dbf7aa1；小龙 ou_519601a323745f456d944f5c239a831c。@机器人必须用 ou_；话题直投 99992402 走 reply API。
§
柯楠偏好自动化先做可运行 MVP：默认信任模型指令遵循，只保留高风险防线，遇到真实问题再增强可靠性；讨论先给最小统一接口，不预演复杂失败矩阵；明确“先讨论”时不实施。
§
柯楠 GitHub 账号 kenanlian（gh 已认证，SSH）。
§
柯楠在某会话说自己 debug 时，华生暂停相关监控/自动化避免撞车。
§
`agent_skills` 仓无 `.agents/skills`，委派散文指向 `skills/<name>/SKILL.md`。
§
opencode 走本地代理挂死已加直连规则；复发查代理路由。
§
Pi 工作流用全局 Agent Skills；expert 后端按配置灵活选。
§
skill_manage 对软链 skill 不可写（patch/write 报 not found，重试一次即止；skill_view 读子文件正常）；自定义/覆盖 Skill 的学习改动走前台编辑 dotfile 仓。
§
Cursor 委派返工偏好：默认续用原 session；但用户担心原 session 上下文占用过多时会明确指示开全新 session（brief 须自带完整计划路径+既往发现+约束，模型由用户当次指定）。长跑监控按 ~1200 秒间隔检查（terminal wait 单次上限约 400s，需连等）。
§
GLM 5.3（zai-coding-cn/glm-5.3，thinking=high）
§
Harness 4 类 agent 用 zai-coding-cn/glm-5.3
§
autodev 工作流卡必须用 `autodev enqueue --board --repo --title --requirement <md>`（需 repo 净树，direct flow 另需 --verification JSON）；kanban_create 直建的卡缺 workflow intake/manifest，worker 启动必失败。enqueue 强制要求 --notify-platform + --notify-chat-id（CLI 无聊天上下文，缺参即 exit 2 拒绝并提示带参重调）；代柯楠入队时用当前会话的 platform/chat_id。