柯楠产品视觉：浅色为主、优秀暗色可备选；极简如 Otty 干净，以背景/灰阶分层替代大量边框；圆润小按钮、克制微交互、细腻质感。页面篇幅适中（Otty/VMark），忌 omp 式超长。Zed 硬朗工程风仅限需极度凸显工程精密感的产品。
§
Kanban 一项目一 board。
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
身份自判（会话开场先查再表态）：env 有 HERMES_KANBAN_TASK 且命令行含 `--cli -q work kanban task` = dispatched Worker（按卡面执行）；无此 env 而有平台会话上下文 = origin session（发起/监督/汇报/前台协调，不做 implement，汇报时不得自称 Worker）。schema 含 kanban 工具不构成身份证据——origin 也可能带全套工具。