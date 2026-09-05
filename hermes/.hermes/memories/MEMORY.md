柯楠产品视觉：浅色为主、优秀暗色可备选；极简如 Otty 干净，以背景/灰阶分层替代大量边框；圆润小按钮、克制微交互、细腻质感。页面篇幅适中（Otty/VMark），忌 omp 式超长。Zed 硬朗工程风仅限需极度凸显工程精密感的产品。
§
个人项目开发：持久化到 ~/Secret-Projects/development-artifacts；项目根 `.dev` 用相对软链，两个仓库分别 commit/push；`initiatives/` 只读退役，计划放 `.dev/plan/`。Kanban 一项目一 board、一独立功能一卡，验收标准写 card body；review 仅作华生 UI 行为验收，`review_dispatch=false`。
§
`write-plan` 默认内含 `review-plan`（仅用户明确针对该计划要求跳过时例外），每 cycle 最多 3 轮；第 3 轮仍 REVISE 时，须用户授权且计划实质修订后另开并链接新 cycle，禁止原 cycle 直接第 4 轮。低风险细节可建议用户 override PASS。
§
Obsidian UI 验收：华生负责 CLI/eval/DOM/截图可判定的功能、刷新、持久化、布局及结构可访问性；柯楠手验 VoiceOver 朗读、瞬时 Hover/菜单、长滚动/拖拽手感、原生感与密度。桌面控制一次常规+一次规定升级仍不可验即停止并交接。
§
Chrome 默认 Profile `Hermes` 华生专用（日常 Vivaldi）；browser-harness + 远程调试已授权，`browser_exec` 可用。
§
Feishu 发消息/@人：~/.hermes/scripts/feishu.py send --chat 群名 --at 名字 --text；新联系人 contacts --scan。小龙=同机 executor profile（--profile executor），ALLOW_BOTS=mentions、@ 即唤醒。open_id 按应用隔离：我 ou_4c5fa38a012bf260485ed24c499482dd；柯楠 ou_19234927e3331a9e1433c9a81dbf7aa1；小龙 ou_519601a323745f456d944f5c239a831c。@机器人必须用 ou_；话题直投 99992402 走 reply API。
§
OpenCode：默认 zhipuai-coding-plan/glm-5.3 variant high（k3 已下线），轻量档 opencode-go/deepseek-v4-pro；dotfile reviewer 允许委派 subagent、勿禁 task。Pi 为 delegate_agent 宿主、key 已配；app 配置本体放 ~/Secret-Projects/dotfile 软链。2026-09-05 起 Card Workspace 开发指定 Pi。
§
开发 Relay：每卡一个 `development-monitor.v2` state+wrapper+10 分钟 Cron；schedule 必须写 `every 10m`；新 Relay 只 `generation+=1` 换 `out_dir`。state 手写严格用枚举 closed/idle/relay_running（大写 RUNNING 非法→BAD_STATE 永久静默）且 attempt 必含 process_identity；故障先跑 classify_monitor_state()。卡 done 后非 source 删 Cron/wrapper。
§
柯楠偏好自动化先做可运行 MVP：默认信任模型指令遵循，只保留高风险防线，遇到真实问题再增强可靠性；讨论先给最小统一接口，不预演复杂失败矩阵；明确“先讨论”时不实施。
§
柯楠 GitHub 账号 kenanlian（gh 已认证，SSH）。
§
柯楠会并行开别的会话处理问题；他说某事自己在另一会话 debug 时，华生应暂停相关监控/自动化避免撞车。
§
`agent_skills` 仓自身无 `.agents/skills`，委派时以散文指向 `skills/<name>/SKILL.md`；`development_relay_gate.py` 需 `sys.path.insert` 后 import，spec 加载会因 dataclass 崩溃。
§
opencode 经本地代理走智谱会挂死（僵在收尾），柯楠已加直连规则，pi 同代理正常；复发先查代理路由。
§
评审 artifact 元数据保持最小：wrapper 不注入 provenance；reviewer frontmatter 可退化为 unknown；Session/resume 标识仅写 receipt。
§
Pi 开发工作流中，Agent Skills 采用全局 Skill；expert 后端不固定为 Cursor，后续按配置灵活选择。