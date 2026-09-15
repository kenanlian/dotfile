"""Model-facing schemas for intent-discussion tools."""

REQUIREMENT_WRITE = {
    "name": "intent_requirement_write",
    "description": (
        "这是持久化 requirement 的唯一方式；先完成讨论收敛再调用；"
        "open_questions 非空时产出为 draft，不得 enqueue。"
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "repo",
            "slug",
            "title",
            "goal",
            "context",
            "behaviors",
            "decisions",
            "non_goals",
            "constraints",
            "auto_acceptance",
            "manual_acceptance",
            "open_questions",
        ],
        "properties": {
            "repo": {
                "type": "string",
                "description": "目标项目仓的绝对路径。",
            },
            "slug": {
                "type": "string",
                "description": (
                    "requirement 文件名（不含扩展名），须匹配 "
                    "^[a-z0-9][a-z0-9-]{0,63}$。"
                ),
            },
            "title": {
                "type": "string",
                "description": "需求标题。",
            },
            "goal": {
                "type": "string",
                "description": "一句话目标：用户要达成什么。",
            },
            "context": {
                "type": "string",
                "description": (
                    "讨论结论：可行性判断与决策相关现状（带文件/符号出处），"
                    "非探索笔记。"
                ),
            },
            "behaviors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "行为规格，每条「触发 → 行为 → 结果」，含关键边界。",
            },
            "decisions": {
                "type": "array",
                "description": "已决决策；下游不得推翻，只能执行。",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["decision", "rationale"],
                    "properties": {
                        "decision": {
                            "type": "string",
                            "description": "已锁定的决策内容。",
                        },
                        "rationale": {
                            "type": "string",
                            "description": "该决策的理由。",
                        },
                    },
                },
            },
            "non_goals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "明确不做的事项。",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "必须遵守的约束；无则空数组。",
            },
            "auto_acceptance": {
                "type": "array",
                "items": {"type": "string"},
                "description": "自动验收：每条须存在一条命令能判定；不写具体 argv。",
            },
            "manual_acceptance": {
                "type": "array",
                "description": "人工验收场景：操作 + 预期 + 证据载体路径约定。",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["scenario", "expected", "evidence"],
                    "properties": {
                        "scenario": {
                            "type": "string",
                            "description": "要执行的操作场景。",
                        },
                        "expected": {
                            "type": "string",
                            "description": "该场景的预期结果。",
                        },
                        "evidence": {
                            "type": "string",
                            "description": "证据落盘路径约定（截图/录屏/日志）。",
                        },
                    },
                },
            },
            "open_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "尚未收敛的问题。非空则 status=draft，不得 enqueue；空则 ready。"
                ),
            },
            "overwrite": {
                "type": "boolean",
                "default": False,
                "description": "目标文件已存在时是否覆盖。默认 false。",
            },
        },
    },
}
