---
name: pi-delegate
description: "Use when explicitly delegating a task to Pi CLI."
license: MIT
metadata:
  version: 0.6.0
  hermes:
    related_skills: [pi-coding-agent, project-taskflow]
---

# Optional Pi Transport

The existing Pi relay is an explicit opt-in transport, not a development workflow. Kenan's default project work uses `project-taskflow` and native Codex. No automatic planner/reviewer/implementer roles, stage mounting, model-by-stage selection, fixed review rounds or custom router setup is prescribed here.

## Preflight

Use `terminal` to check `command -v pi`, `pi --version`, `pi --list-models <search>` and the helper's `--help`. Record the confirmed cwd, model and allowed side effects. An explicit user model wins. Do not substitute historical role-model tables or quota fallbacks for a current decision.

## Relay

The retained helper is `scripts/relay.mjs` in this Skill's real directory. Invoke through `terminal`:

```text
node <skill-dir>/scripts/relay.mjs --brief <file> --cd <repo> --write --model <provider/model> --thinking high --out-dir <artifact-dir>
```

Full tool access is the default commissioning policy; pass `--write` explicitly because this legacy helper otherwise defaults to a read-tool allowlist. State read-only scope in the brief and inspect the diff. Use `--read-only` only when a restriction was explicitly requested. No brief grants commit/push/PR/publication unless the user authorized those actions.

The helper has an existing structural requirement: its brief begins with `/skill:<existing-skill-name> ` followed by the task. Verify the selected Skill exists and is appropriate; do not resurrect deleted workflow entries to satisfy the prefix. For a one-off run with no selected Skill, use native Pi via `pi-coding-agent` instead. Do not silently patch the helper at runtime.

Use a unique repo-external artifact directory. Preserve result.json, final.txt, raw events and stderr. `--session <exact-id>` continues an existing known session; verify it belongs to the task. Resume the same task with delta evidence, never blindly replace its failed session. Watchdog is optional; do not invent short duration bounds.

## Completion and Recovery

Success requires actual terminal exit plus a completed structured result, correct session and agent_settled evidence. The result is transport completion, not human acceptance. Record model/effort/permissions, exact session and touched-file inventory, including index, untracked and committed changes where applicable.

On failure, preserve work and evidence, confirm the previous writer is dead, and inspect the cause before continuation. No blind retry loop, automatic role fallback, cleanup, commit or publication. Unknown outcomes are not permission to replay.

## Retained Legacy Features

Scripts still support advanced extension/structured-output switches for explicitly commissioned compatibility work. Their historical tests and [reference](references/dispatch-and-poll.md) document mechanisms, not current orchestration policy. Do not auto-load auto-handoff/review-submit/stage-submit extensions or output-only recovery just because options exist. Old custom-router/model defaults and stage recipes in retained references are non-authoritative.

Project orchestration, native plan choices, version-bound human acceptance and serial integration belong to `project-taskflow`. This change retires prescriptions without changing executable helper behavior or Pi configuration.
