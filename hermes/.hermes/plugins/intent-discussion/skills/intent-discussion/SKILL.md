---
name: intent-discussion
description: Use when 用户想讨论新功能/需求并收敛为 requirement 文档。
---

# Intent discussion

在 default profile 普通会话中，把用户的新功能/需求想法收敛为结构化 requirement 文档，供 `autodev enqueue --requirement` 消费。讨论结束于「需求是什么、为什么、做成什么样、哪些决策已锁定」；**不做实施规划**。实施规划属于 autodev Plan 阶段，且 Plan 必须完全自包含。

## 触发与定位

在以下情况启用本 skill：

- 用户提出新功能、新需求或产品想法，需要先讨论清楚再进入开发流水线；
- 用户明确说「讨论」、要对齐意图、或要把想法写成 requirement。

本阶段只做三件事：

1. **明确需求 WHAT / WHY**：用户要达成什么、为什么现在做。
2. **暴露并收敛决策项**：功能/行为决策，以及极少数关键技术决策候选。
3. **可行性判断**：对照现有代码，判断能否做、卡在哪里、风险是什么。

不要做：拆工作包、写施工步骤、选定常规技术方案、编写具体验收 argv。那些由后续 Plan（`--flow full`）或 direct 实施自己完成。

## 流程

按顺序执行。未过收敛 checklist 之前，不得调用 `intent_requirement_write`。

### 1. 澄清意图与范围

先和用户对齐：

- 目标用户与要改变的体验；
- 目标仓库的绝对路径（当面确认；工具要求绝对路径且目录存在）；
- 范围边界：做什么、明确不做什么；
- 是否可拆成多个**独立功能**（各自一份 requirement、各自 enqueue）。能独立验收、独立交付的拆开；强耦合的留在同一功能里。

拆分结论要告诉用户，再进入探索。

### 2. 每功能派一个只读探索 relay

每个功能一次只读 grounding。传输细节（preflight、`--out-dir` 默认值、thinking、result 契约、失败语义）**加载 `pi-delegate` skill 获取**，不要把该 skill 的选项表或内部契约复制进 brief 或本流程。

派发形式（多功能各自独立 `--out-dir`，无依赖时可并行）：

```bash
node <pi-delegate-skill>/scripts/relay.mjs \
  --brief <brief-file> \
  --cd <repo> \
  --read-only \
  --model zai-coding-cn/glm-5.3 \
  --out-dir <per-feature-out-dir>
```

`<pi-delegate-skill>` 解析为已加载的 pi-delegate skill 根目录。本档位无 fallback：quota 或可用性失败即该次 relay 失败，向用户报告，不得静默换模型。真实模型调用需当次授权。

**Brief 必须包含：**

- 目标代码库**绝对路径**；
- 本功能描述（范围与排除项）；
- **只读禁令**：parent 及任何 `delegate_agent` child 均禁止写、改、建、删文件，也不得派有写权限的 child。`--read-only` 仍可能留下 `delegate_agent`；这是指令边界，不是 OS 沙箱；
- 要求返回（结论，不要原始探索笔记）：
  1. 涉及模块 / 文件 / 符号；
  2. 现有相关行为；
  3. 可行性结论；
  4. **决策项清单**：需要用户拍板的功能/行为决策，以及极少数关键技术决策候选；**常规技术决策不列入**（留给 Plan）；
  5. 风险点。

**消费：**

1. 等待 relay **进程退出**，不要把进度输出或 `finalMessage` 片段当成完成。
2. 读该次 `--out-dir` 下的 `result.json`。
3. 仅当 `status=completed` 才采用该次产出；其他状态向用户报告失败原因，不把半成品当证据。
4. `touchedFiles` **必须为空**。非空 = 越界：向用户报告路径清单，**丢弃该次产出**，不得写入 requirement。
5. 探索结论取自 `finalMessage`。把其中的模块/行为/可行性/决策项/风险提炼进讨论，不要把笔记原文堆进 `context`。

### 3. 汇总并与用户分批收敛

汇总各功能的探索结论。决策项分批提问：每批少量，每项给出推荐项与简短理由，等用户拍板后再下一批。

规则：

- 不替用户做意图决策；只提问、给推荐、记录理由。
- 常规技术选型不拿来讨论，除非它会改变用户可见行为或可行性。
- 用户未决的问题记入 `open_questions`，不得假装已决。

### 4. 收敛 checklist（全过才可落盘）

每个功能在调用工具前自检。任一项未过则继续讨论，或明确产出 draft 并告知用户不得 enqueue。

- [ ] 每条自动验收都能用「存在一条命令能判定」来描述（只写判定意图，**不写 argv**；argv 是 Plan 的职责）。
- [ ] 每条人工验收是「操作 + 预期 + 证据载体」的场景化句子（证据载体 = 截图 / 录屏 / 日志的落盘路径约定）。
- [ ] 开放问题已清空。否则工具会标 `status: draft`，必须告知用户**不得 enqueue**。
- [ ] 非目标明确（写清这次故意不做的事）。
- [ ] 已决决策每条带理由（`decision` + `rationale`）。

另：`auto_acceptance` 与 `manual_acceptance` 合计至少 1 条（工具硬校验）。`goal` 非空。

### 5. 每个功能调用一次 `intent_requirement_write`

requirement **只能经该工具落盘**。禁止 `write_file` / 手工写 `.dev/requirements/`。

每个功能一次调用；参数填齐 schema 的 12 个 required 字段（见附录）。目标已存在且要覆盖时才传 `overwrite: true`。

工具返回 `path` / `sha256` / `status` / `bytes`。`open_questions` 非空 → `draft`；空 → `ready`。

### 6. 向用户展示产出

对每个功能展示：绝对路径、`status`（`ready` 或 `draft`）、`slug`。`draft` 再次强调不得 enqueue，直到开放问题清空并重写为 `ready`。

## 交接

仅在用户确认、且该功能 `status=ready` 之后，给出 enqueue 命令。**禁止自动执行 enqueue**。真实模型调用需当次授权。

每功能一条：

```bash
hermes autodev enqueue --board <board> --repo <repo> --title "<title>" --requirement <path> --profile autodev
```

补上 `--flow full` 或 `--flow direct`，并写明选择理由：

- **`--flow full`（默认）**：需要 Plan → Plan Review → Implement → Verify → Execute Review → Product Acceptance。implement 阶段只读 plan、不读 requirement；Plan 必须自包含。适合有行为决策、跨模块、或需要产品验收的功能。
- **`--flow direct`**：跳过 planner / 评审 / 产品验收，requirement 是实施的**唯一输入**，必须自包含。autodev CLI 还要求 `--verification <绝对路径>`（Harness checks）；本 skill 不代写 verification 文件。适合范围小、行为已锁死、用户明确要直达实施的改动。

有顺序依赖时：仍各写各的 requirement、各 enqueue 一次；说明必须进**同一 board**，利用已有前驱串行（后卡会等到前卡结束），不要发明新的编排机制。

## 边界

- **不替用户做意图决策**：只提问、给推荐、记录已决理由。用户没拍板的不写进 `decisions`。
- **探索只读**：`--read-only` + brief 写禁令 + `touchedFiles` 必须为空。越界产出丢弃。
- **requirement 只能经 `intent_requirement_write` 落盘**，不得用 `write_file` 或其它写工具手写。
- **不自动 enqueue、不 git commit**。enqueue 命令展示给用户，确认后再由用户或当次授权执行。
- **不做实施规划**，不把本阶段做成 Plan 草稿。

## 附录：字段写法规范

工具签名即模板 schema。模型只填字段；frontmatter 与 markdown 结构由工具渲染。字段名与工具参数一致。

### slug

文件名（不含 `.md`），写入 `<repo>/.dev/requirements/<slug>.md`。必须匹配 `^[a-z0-9][a-z0-9-]{0,63}$`（小写字母或数字开头，仅小写、数字、连字符）。按功能语义取名，不要用日期或会话 id。

### title

人类可读标题，与 enqueue `--title` 对齐。一句说清功能，不要口号。

### goal

一句话：用户要达成什么。写 WHAT / WHY，不写怎么做。非空。

### context

**讨论结论记录**，不是探索笔记堆砌。只保留：

- 可行性判断（能做 / 有条件能做 / 做不了，以及依据）；
- 与已决决策相关的**现状事实**，并带文件 / 符号出处。

不要粘贴 relay 原文、搜索清单或大段代码。implement 阶段**不读** requirement（只读 plan），因此 context **不要求施工级完备**（不必列出每个改动文件或实现步骤）。但在 **`--flow direct`** 下 requirement 是唯一输入，context 必须让未参加讨论的实施者理解现状与约束——把决策相关事实写全，仍不要写成施工清单。

### behaviors

每条：`触发 → 行为 → 结果`，含关键边界（空状态、权限、失败、与旧行为的兼容）。写用户可见行为，不写函数名级实现。

### decisions

每项 `{decision, rationale}`。只放已与用户锁定的决策；下游不得推翻，只能执行。理由写清「为什么这样选」。常规技术决策不要塞进来。

### non_goals

这次明确不做的事。防止 Plan / 实施扩 scope。空数组表示没有额外排除（仍应尽量写几条，避免默认为「什么都做」）。

### constraints

必须遵守的约束（兼容、平台、性能、安全、既有接口）。没有则空数组（工具会写成「无」）。

### auto_acceptance

每条描述一种**可用一条命令判定**的结果（存在性、退出码、输出契约、测试文件覆盖的行为）。**不写具体 argv**——argv 由 Plan / verification 决定。不要写「代码里有某某函数」这类无法当命令门禁的句子。

### manual_acceptance

每项 `{scenario, expected, evidence}`，合成一句场景化验收：操作 + 预期 + 证据载体。`evidence` 是截图 / 录屏 / 日志的落盘路径约定，不是「看起来没问题」。产品验收要场景化、可留证。

### open_questions

尚未收敛的问题。**非空 → `status: draft`，不得 enqueue**；空数组 → `ready`。checklist 未过就不要硬写成空数组。

### 完备程度（重复强调）

1. **Context = 讨论结论**（可行性 + 决策相关现状，带出处），不是探索笔记。
2. **full flow 的 implement 不读 requirement**（只读 plan），所以 requirement 不要求施工级完备。
3. **direct flow 下 requirement 是唯一输入**，必须自包含：未参加讨论的人只凭这一份也能实施与验收。
