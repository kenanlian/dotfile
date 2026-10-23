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
柯楠已确认默认项目开发入口为 project-taskflow（用户级 Skill 已安装）：Hermes 编排/转接，Codex 原生规划与实施。旧 Pi/Harness 固定流水线已拆除；Pi/Cursor/OpenCode 保留为显式选用的通用工具。真实项目须先明确登记仓库、集成分支与本地 Git 授权；不因启用流程自动接入产品、提交或发布。
§
委派 CLI coding agent（opencode/codex/cursor）默认全权限：不做 permission deny、不设只读沙箱；只读任务靠 brief 文字约束模型，事后用 touchedFiles/git diff 核查。2026-10 柯楠明确确认。SKILL.md 的 description 含冒号时必须加引号，否则 YAML 解析回退成行解析、platforms 变字符串、skill 被判 unsupported（已实证）。
§
project-taskflow 源码/运行现场为 `~/Secret-Projects/project-taskflow` 主工作区 main；固定入口 `~/.local/bin/project-taskflow` 指向主工作区 `scripts/taskflow.mjs`；start 管 runner 复用与身份。自身注册目录是 `~/Secret-Projects/development-artifacts/project-taskflow/self-hosted/project`。Codex 默认，Pi 1.3.0 可选（新登记 backend:"pi"，无迁移）；统一 Controller/direct，无 Kanban。主工作区集成需 primaryWorktreeIntegration 授权；其他项目可兼容既有 _integration。development-artifacts 有用户遗留 stash@{0} 与 `.git/search-benchmark-untracked-draft-v1.md.bak`，不要清理。