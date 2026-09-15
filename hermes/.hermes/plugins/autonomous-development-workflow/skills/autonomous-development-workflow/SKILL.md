---
name: autonomous-development-workflow
description: Worker rules for Manifest-bound autonomous development cards. Call typed workflow tools only.
---

# Autonomous development workflow

Use this skill only for Kanban cards that already have an `autonomous-development.v1` Manifest. Natural-language labels in the card body are not an enablement signal.

## Behavior rules

1. Call `autodev_workflow_status` first, then repeatedly call `autodev_workflow_advance`. Do not guess the next stage, session, artifact, or Kanban lifecycle action.
2. While the controller returns `in_progress`, call `autodev_workflow_advance` again. Do not emit a completion summary or stop the Worker.
3. Exercise real browser, Obsidian, CLI, or application paths only after the controller returns `acceptance_required`. Deterministic tests, lint, or code review are not product acceptance.
4. Submit product acceptance only through `autodev_workflow_submit_acceptance`. Do not write `product-acceptance-vN.json` yourself and do not ask the controller to parse a model-authored JSON file.
5. If you cannot reliably verify the real product behavior, submit `needs_human` with one explicit, answerable question.
6. Do not call native `kanban_complete`, `kanban_request_review`, `kanban_request_changes`, or `kanban_block`. Do not shell out to the equivalent `hermes kanban complete|request-review|request-changes|block` commands. Status, comment, and heartbeat remain available.

## Acceptance verdicts

- `passed`: at least one exercised scenario, every scenario passed, no blocking finding.
- `failed`: a reproducible failed scenario or blocking finding; the controller returns the card to the Implementer.
- `needs_human`: one concrete question the operator can answer.
- `blocked`: a named external blocker the Worker cannot clear.
