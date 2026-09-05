用户叫柯楠。
§
用户希望称呼助手为“华生”，并期待像福尔摩斯与华生一样默契协作；偏好友好、有搭档感的互动。
§
用户的 Obsidian 知识库为 ~/Obsidian/Self-Notes；用户偏好所有 Obsidian 知识库操作通过官方 Obsidian CLI 完成，并在需要同步时通过 CLI 触发 Remotely Save。
§
用户不希望将探索性的产品理念讨论自动固化为 Skill；只有形成经过实践验证的成熟流程或方法论，并经用户明确确认后，才创建相关 Skill。
§
用户长期开发 Obsidian 插件 Card Workspace，已有少量真实用户和反馈；享受独立软件开发与产品细节打磨，并将其视为可能的职业第二曲线乃至未来事业。
§
用户最重要的三个工作目录：~/Obsidian 存放不同的 Obsidian 仓库；~/Secret-Projects 存放所有个人项目；~/Source-Code-Learning 集中存放需要学习研究的开源代码。
§
用户不希望把个人的 Cursor/Codex 委派契约写入项目仓库的 AGENTS.md；个人编排偏好应保留在用户级 Skill/Memory，仓库 AGENTS.md 仅承载项目共享的工程事实与约束。
§
验收后可常驻授权 commit，并自动 push 插件仓 main（仅触发 CI）；官网仓 main（push=生产部署）、tag、PR、发布均逐次授权。
§
开发流程：每个独立任务一卡，内部 Agent 阶段不另建卡；Secret-Projects 各用专属 board，其余用 default。简单任务直接委派并由 coding agent 验证；结构化任务运行 `write-plan`（内部 review-plan）和 fresh `execute-plan`（内部 patch/conformance review）。华生不做内部 review；仅 UI 任务进 Kanban review 做真实行为验收，非 UI 无例外；无 brainstorm Skill。
§
前端/Obsidian UI 必须由华生在真实浏览器或 Obsidian 走关键路径，不能用测试、lint 或代码审查代替；无法可靠自动验时说明阻碍、已验范围和风险，并交由用户手验必要项。
§
Cursor/Codex 默认无超时；仅需会话内监控时按 3 分钟切片，简单任务每片检查，复杂任务每 15–30 分钟结合进程、result/events 与计划状态判断；健康运行不结束或重启。
§
开发委派默认用 OpenCode；Cursor/Codex 仅在柯楠明确指定时使用。