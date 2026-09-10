柯楠产品视觉：浅色为主、优秀暗色可备选；极简如 Otty 干净，以背景/灰阶分层替代大量边框；圆润小按钮、克制微交互、细腻质感。页面篇幅适中（Otty/VMark），忌 omp 式超长。Zed 硬朗工程风仅限需极度凸显工程精密感的产品。
§
个人项目开发：持久化到 ~/Secret-Projects/development-artifacts；项目根 `.dev` 用相对软链，两个仓库分别 commit/push；`initiatives/` 只读退役，计划放 `.dev/plan/`。Kanban 一项目一 board；简单功能一张 direct 卡，复杂功能拆 write-plan→execute-plan 两张阶段卡。
§
managed 开发用 development-stage.v2 + devflow_* Harness；两阶段卡 write-plan 用 review-plan，execute 用单个 review-execute-candidate（独立 Patch/Conformance Gate），最多 3 轮，第 4 轮须柯楠授权且 candidate 有实质修订；Pi 内部 final gate 跳过。
§
Obsidian UI 验收：华生负责 CLI/eval/DOM/截图可判定的功能、刷新、持久化、布局及结构可访问性；柯楠手验 VoiceOver 朗读、瞬时 Hover/菜单、长滚动/拖拽手感、原生感与密度。桌面控制一次常规+一次规定升级仍不可验即停止并交接。
§
Chrome Profile `Hermes` 华生专用；browser_exec 可用。
§
Feishu 发消息/@人：~/.hermes/scripts/feishu.py send --chat 群名 --at 名字 --text；新联系人 contacts --scan。小龙=同机 executor profile（--profile executor），ALLOW_BOTS=mentions、@ 即唤醒。open_id 按应用隔离：我 ou_4c5fa38a012bf260485ed24c499482dd；柯楠 ou_19234927e3331a9e1433c9a81dbf7aa1；小龙 ou_519601a323745f456d944f5c239a831c。@机器人必须用 ou_；话题直投 99992402 走 reply API。
§
review/direct/grounding 固定 glm-5.3 无 fallback
§
真实工作前确认 `kanban.max_in_progress=1`（跨 board 主机级）且 `kanban.max_in_progress_per_profile=1`（board 内按 profile）；两者配合才全局串行。
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
评审 artifact 元数据最小：reviewer frontmatter 可 unknown；session/resume 标识仅记外部 guard 状态。
§
Pi 工作流用全局 Agent Skills；expert 后端按配置灵活选。
§
skill_manage 对软链 skill 不可写（patch/write 报 not found，重试一次即止；skill_view 读子文件正常）；自定义/覆盖 Skill 的学习改动走前台编辑 dotfile 仓。
§
Guard uncertain 无自动 reset；仅柯楠按单 Card 授权 Origin 在证明零副作用后按 execution-recovery 狭窄规程恢复，Worker/non-owning 会话不得处理。
§
身份自判（会话开场先查再表态）：env 有 HERMES_KANBAN_TASK 且命令行含 `--cli -q work kanban task` = dispatched Worker（按卡面执行）；无此 env 而有平台会话上下文 = origin session（发起/监督/汇报/前台协调，不做 implement，汇报时不得自称 Worker）。schema 含 kanban 工具不构成身份证据——origin 也可能带全套工具。