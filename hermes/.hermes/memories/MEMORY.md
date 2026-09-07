柯楠产品视觉：浅色为主、优秀暗色可备选；极简如 Otty 干净，以背景/灰阶分层替代大量边框；圆润小按钮、克制微交互、细腻质感。页面篇幅适中（Otty/VMark），忌 omp 式超长。Zed 硬朗工程风仅限需极度凸显工程精密感的产品。
§
个人项目开发：持久化到 ~/Secret-Projects/development-artifacts；项目根 `.dev` 用相对软链，两个仓库分别 commit/push；`initiatives/` 只读退役，计划放 `.dev/plan/`。Kanban 一项目一 board、一独立功能一卡，验收标准写 card body；UI 由同一 Execution Worker 在真实 renderer 验收，不进 review，`review_dispatch=false`。
§
`write-plan` 默认内含 `review-plan`（仅用户明确针对该计划要求跳过时例外），每 cycle 最多 3 轮；第 3 轮仍 REVISE 时，须用户授权且计划实质修订后另开并链接新 cycle，禁止原 cycle 直接第 4 轮。低风险细节可建议用户 override PASS。
§
Obsidian UI 验收：华生负责 CLI/eval/DOM/截图可判定的功能、刷新、持久化、布局及结构可访问性；柯楠手验 VoiceOver 朗读、瞬时 Hover/菜单、长滚动/拖拽手感、原生感与密度。桌面控制一次常规+一次规定升级仍不可验即停止并交接。
§
Chrome Profile `Hermes` 华生专用；browser_exec 可用。
§
Feishu 发消息/@人：~/.hermes/scripts/feishu.py send --chat 群名 --at 名字 --text；新联系人 contacts --scan。小龙=同机 executor profile（--profile executor），ALLOW_BOTS=mentions、@ 即唤醒。open_id 按应用隔离：我 ou_4c5fa38a012bf260485ed24c499482dd；柯楠 ou_19234927e3331a9e1433c9a81dbf7aa1；小龙 ou_519601a323745f456d944f5c239a831c。@机器人必须用 ou_；话题直投 99992402 走 reply API。
§
Pi 为默认委派宿主（delegate_agent、key 已配）；app 配置本体放 ~/Secret-Projects/dotfile 软链。OpenCode 已降为备选：zhipuai-coding-plan/glm-5.3 variant high（k3 已下线），轻量档 opencode-go/deepseek-v4-pro；dotfile reviewer 允许委派 subagent、勿禁 task。
§
主目录真实工作前确认全局 kanban.max_in_progress_per_profile=1（config.yaml，按 profile 跨所有 board 生效，无 per-board 旋钮）。
§
柯楠偏好自动化先做可运行 MVP：默认信任模型指令遵循，只保留高风险防线，遇到真实问题再增强可靠性；讨论先给最小统一接口，不预演复杂失败矩阵；明确“先讨论”时不实施。
§
柯楠 GitHub 账号 kenanlian（gh 已认证，SSH）。
§
柯楠会并行开别的会话处理问题；他说某事自己在另一会话 debug 时，华生应暂停相关监控/自动化避免撞车。
§
`agent_skills` 仓无 `.agents/skills`，委派散文指向 `skills/<name>/SKILL.md`。
§
opencode 走本地代理挂死已加直连规则；复发查代理路由。
§
评审 artifact 元数据保持最小：reviewer frontmatter 可退化为 unknown；Session/resume 标识仅记入外部 guard 状态。
§
Pi 开发工作流中，Agent Skills 采用全局 Skill；expert 后端不固定为 Cursor，后续按配置灵活选择。
§
Hermes 文本资产入 dotfile hermes/ 包软链回 ~/.hermes；skill_manage patch/delete 不认软链 skill（用 patch/write_file）；新 skill mv 入仓补链，详见该包 README。