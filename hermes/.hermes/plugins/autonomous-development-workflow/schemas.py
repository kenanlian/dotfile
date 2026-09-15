"""Model-facing schemas for the autonomous development workflow tools."""

STATUS = {
    "name": "autodev_workflow_status",
    "description": (
        "Read the current external workflow checkpoint for the active Kanban "
        "task. Returns workflowStatus, revision, stageAttempt, activeJobId, "
        "nextAction, inProgress, pendingLifecycle, and lastActivity. Does not "
        "change workflow or Kanban state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Kanban task id. Omit to use the current Worker task.",
            },
            "board": {
                "type": "string",
                "description": "Kanban board slug. Omit to use the current Worker board.",
            },
        },
        "additionalProperties": False,
    },
}

ADVANCE = {
    "name": "autodev_workflow_advance",
    "description": (
        "Advance the external autonomous development workflow by one "
        "controller-computed step. Do not pass a target stage, status, "
        "session, artifact path, or Kanban lifecycle action."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Kanban task id. Omit to use the current Worker task.",
            },
            "board": {
                "type": "string",
                "description": "Kanban board slug. Omit to use the current Worker board.",
            },
            "wait_seconds": {
                "type": "integer",
                "description": "Bounded seconds to wait on an in-progress Harness job.",
                "default": 60,
            },
        },
        "additionalProperties": False,
    },
}

SUBMIT_ACCEPTANCE = {
    "name": "autodev_workflow_submit_acceptance",
    "description": (
        "Submit a typed product-acceptance verdict for a review-lane Worker "
        "This is the only supported way to record product acceptance. The plugin "
        "captures the current candidate fingerprint and writes canonical "
        "product-acceptance-vN.json; do not write that JSON yourself."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Kanban task id. Omit to use the current Worker task.",
            },
            "board": {
                "type": "string",
                "description": "Kanban board slug. Omit to use the current Worker board.",
            },
            "verdict": {
                "type": "string",
                "enum": ["passed", "failed", "needs_human", "blocked"],
                "description": "Typed acceptance verdict.",
            },
            "summary": {
                "type": "string",
                "description": "Short evidence-backed summary of the acceptance attempt.",
            },
            "scenarios": {
                "type": "array",
                "description": "Acceptance scenarios that were actually exercised.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "status": {"type": "string", "enum": ["passed", "failed"]},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "status"],
                    "additionalProperties": False,
                },
            },
            "findings": {
                "type": "array",
                "description": "Blocking or warning findings from product acceptance.",
                "items": {"type": "object"},
            },
            "question": {
                "type": ["string", "null"],
                "description": "Required when verdict is needs_human.",
            },
        },
        "required": ["verdict", "summary", "scenarios"],
        "additionalProperties": False,
    },
}
