---
name: pi-coding-agent
description: "Use when driving Pi CLI or inspecting its extensions."
version: 1.1.0
license: MIT
metadata:
  version: 1.1.0
  hermes:
    related_skills: [pi-delegate, project-taskflow]
---

# Pi CLI Knowledge

Pi is an optional coding-agent CLI, not Kenan's default project workflow. Project development uses `project-taskflow` and native Codex. Use Pi only when the current user/task explicitly selects it. This Skill preserves CLI mechanics and debugging references, not the retired stage harness, custom role pipeline or mandatory review rounds.

## When to Use

- Explicit Pi CLI runs, provider/model discovery, extension development or Pi event debugging.
- Do not choose Pi, install its extensions, rebuild a custom router, or invoke old workflow Skills just because historical examples mention them.

## Preflight and Basic Runs

Use `terminal` to check `command -v pi`, `pi --version`, `pi --help` and `pi --list-models <search>` against the live installation. Select the user-requested provider/model; do not infer models from old implement/review roles. Do not print credentials. Configuration/auth belong to Pi and are outside a workflow-cleanup authorization.

For an explicitly requested one-off run, use `pi -p --mode json --model <provider/model> --thinking high <prompt>` in the confirmed cwd and retain raw stdout/stderr. When spawning from Python, close stdin (`DEVNULL` for a prompt passed as argv, or send the entire piped brief and EOF). An unclosed pipe can look like a hung model before it makes any network call.

Full access is intentional by default. Express read-only scope in the brief; add a tool restriction only when the user explicitly requests that restriction. Tool allowlists are not an OS sandbox and can filter extension tools too. Do not reintroduce stage-based permission policies.

For a run that needs the existing relay artifact contract, read `pi-delegate`; the helper is optional and has explicit Skill-prefix requirements. It is not the default project controller.

## Sessions and Evidence

- A native print/json stream identifies its actual session. `--session-id` may create if missing; therefore verify identity/existence before claiming exact resume. Use the current CLI's supported exact-session option for follow-ups.
- Distinguish process exit, raw agent_end/agent_settled events, final report and artifact acceptance. A successful transport is not human acceptance.
- Before relaunch, check actual process ownership/liveness. Do not let two processes write the same session/events file. Preserve failed attempts and partial repository work; no reset/clean or blind retries.
- Native extensions provide optional subagent behavior. Do not infer any custom router or role definition is installed/approved from these historical references.

## Skills and Extensions

Pi discovers user/project Skill roots at startup, subject to its current trust rules. Hidden Skills can be absent from the visible catalog. When explicitly using a named Skill, verify its real path and supported invocation rather than broadly scanning the user's home. Piped explicit `/skill:<name> <instruction>` syntax requires a same-line space and reliable EOF; inspect the actual CLI when behavior changes.

Use explicit `-e <path>` for task-authorized extensions; `--no-extensions` and `--no-skills` are capability switches, not mandatory workflow stages. A missing extension/tool may fail before inference or silently omit a tool, so verify actual registration or a real call. Extensions run with full host privileges. No implicit extension/router installation is authorized here.

## References and Boundaries

The following retained files are technical/historical evidence, not current workflow policy. Ignore their obsolete model-role defaults, stage names, custom-router approvals, fixed review cycles or automatic retry recipes unless a new task explicitly authorizes that system:

- [Transport/session mechanics](references/delegation-transport.md)
- [Process liveness diagnostics](references/hermes-bg-process-liveness.md)
- [Historical long-run diagnostics](references/long-run-supervision.md)
- [Web extension mechanics](references/web-access.md)
- [Provider interoperability research](references/dsh-credential-migration.md)
- [Historical custom router configuration](references/delegate-agent-config.md)
- [Separate auto-handoff project](references/auto-handoff-extension.md)

Do not modify Pi settings, extension registrations, credentials or another Hermes profile under authority to clean the default Hermes workflow. After an authorized Pi run, verify exact cwd/model/session, actual terminal results and changed-file inventory. Use `project-taskflow` for project-level human gates and completion semantics.
