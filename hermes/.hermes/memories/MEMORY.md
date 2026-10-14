柯楠产品视觉：浅色为主、优秀暗色可备选；极简如 Otty 干净，以背景/灰阶分层替代大量边框；圆润小按钮、克制微交互、细腻质感。页面篇幅适中（Otty/VMark），忌 omp 式超长。Zed 硬朗工程风仅限需极度凸显工程精密感的产品。
§
个人项目开发：持久化到 ~/Secret-Projects/development-artifacts；项目根 `.dev` 用相对软链，两个仓库分别 commit/push；`initiatives/` 只读退役。
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
opencode 走本地代理挂死已加直连规则；复发查代理路由。
§
skill_manage 对软链 skill 不可写（patch/write 报 not found，重试一次即止；skill_view 读子文件正常）；自定义/覆盖 Skill 的学习改动走前台编辑 dotfile 仓。
§
Card Workspace 插件仓库为 `~/Secret-Projects/obsidian-card-workspace`；对应 Kanban board slug 是 `obsidian-card-workspace`（不是空的 `card-workspace`）。
§
本机 Wi-Fi DNS 2026-09-28 由 1.1.1.1/8.8.8.8 改为 223.5.5.5/119.29.29.29：旧境外 DNS 经 MonoProxy 代理解析，feishu GeoDNS 返回境外 CDN IP 致直连 RST、收不到消息。排查直连故障先看解析 IP 是否境内。
§
旧开发流程（计划→Pi 委派→独立验收→评审→返工→授权落地的整条流水线）已于 2026-10-14 整体退役，相关记忆约定已清除；新流程待与柯楠从 0 讨论定案。定案前遇到开发任务不自动沿用旧流程/旧 skill（pi-delegate 等），先问柯楠；旧 skill 文件仍在库中，等新流程定型后一并清理替换。