---
name: project-taskflow
description: "Use for project development via native Codex taskflow."
version: 1.1.0
author: "柯楠, Hermes Agent"
license: MIT
platforms: [macos, linux]
metadata:
  version: 1.1.0
  hermes:
    tags: [development, codex, taskflow, workflow]
    related_skills: [codex-delegate, delegated-development-acceptance]
---

# Project Taskflow

The default project-development workflow for Kenan: Hermes operates the controller and relays decisions; the selected coding backend investigates, plans, implements, tests, repairs and integrates. Codex remains the default; Pi 1.3.0 is an optional per-project backend. This replaces the retired Pi/Harness staged pipeline. It does not authorize a repository, commit, remote operation, or deployment merely because this Skill is loaded.

## When to Use

- Starting or continuing project development, task planning, parallel tasks or version-bound delivery acceptance.
- Recovering an interrupted registered project, inspecting its task DAG, or handing a formal plan to execution.
- Do not enqueue implementation when the user asks only to discuss/explore. Explicitly requested one-off Pi/Cursor/OpenCode work may still use its transport adapter; do not revive a fixed review pipeline.

## Prerequisites and Source of Truth

Source: `~/Secret-Projects/project-taskflow`. Durable artifacts: `~/Secret-Projects/development-artifacts/project-taskflow` or the project's approved `.dev` location. Use `terminal` to inspect actual Node, Git and Codex versions and authentication. The verified MVP uses Node 22 and Codex 0.162.1, with no runtime dependencies.

Before operation, use `read_file` on source `docs/operations.md` and `docs/handoff.md`; for a final tool acceptance use `docs/tool-acceptance.md`. Read the target repository's shared rules. Do not copy personal orchestration rules into its AGENTS.md.

A supported capability is not permission: inspect the actual registration/Git policy. If the installed controller still requires a no-remote fixture, do not forge a fixture marker, strip remotes, or bypass the guard to enroll a real product. Finish the separately approved local-project-support change first. A real project's path, integration branch and permitted local Git scope must be explicitly authorized before registration. Remote presence never authorizes network access, push, PR, tag, release or deploy.

## Operator Procedure

1. **Identify the project.** Use its exact registered artifact directory. Query with `terminal(command="node src/cli.mjs status --project <artifact-dir> --json", workdir="<source-root>")`. For a new project, confirm repository, integration branch and local Git scope, then register through `project init --input <json-file>`. Never guess a project from a task label.
2. **Run one writer.** Keep `node src/cli.mjs run --project <artifact-dir>` in a tracked foreground/background terminal. Do not start a second writer, hand-edit state.json, grab an uncertain lock, or restart healthy work. `status` and `task show --task <id>` are read-only and return current decision templates.
3. **Manage the graph.** Add/update/archive through CLI JSON commands with unique commandId/projectId/taskId. Only completed dependencies unlock planning. Default active development slots are 2, including waiting acceptance/integration; same-project integration is serial. Archive hides completed nodes, not their history. Later changes become new tasks.
4. **Relay native planning.** Use `plan`, preserve task/question identities and exact option labels or free text. Answers must match runner/connection/thread/turn/item and JSON-typed requestId. Expired requests cannot be relabeled; explicitly continue the known original thread. Never fabricate answers or unnecessary questions.
5. **Require each plan choice.** Present the full current native formal plan plus all three choices with no default: `same-context`, `fresh-context`, `stay-plan`. Bind choice to plan version/hash, scope and baseline via `choose`. Each revised plan needs a new choice. Fresh means a distinct native thread receives an independent execution/authorization directive and the byte-identical complete plan, without old dialogue, summaries or compact. Stay grants no execution authorization.
6. **Observe development.** Codex uses independent task worktrees. The model is a project registration field (`model`, default `gpt-6.1-sol`); reasoning effort is controller policy: plan turns run xhigh, default/execution/integration turns run high, explicitly attached to every turn/start (a headless app-server turn whose collaborationMode settings omit reasoning_effort silently falls back to the model-catalog default, NOT the thread setting; verified codex-cli 0.162.1). Observe actual settings in state `run.effective`; null is not proof of high. Hermes does not perform product engineering or invoke the retired stage harness.
7. **Verify under the correct acceptance policy.** Read structured delivery and host Git/check evidence; independently rerun required checks and actual behavior. Kenan delegates code-verifiable, non-UI delivery acceptance to Hermes: after exact-version independent verification passes, record delegated technical acceptance and proceed with authorized local integration without asking him to rubber-stamp it. UI/UX appearance, interaction and subjective experience still require his real decision. Preserve the delegation source, verification report and exact manifest identity; never claim that the user personally tested or accepted a version he has not seen. Advance delegation is not advance passing evidence. On a legacy controller with generic acceptance fields, keep the original delegation and operator evidence explicit in source/feedback; do not hand-edit state or fabricate human approval. Reject only for actual defects. Present the exact delivery, commands, expected results, limitations and unverified items.
8. **Verify integration.** Accepted versions queue for controller-managed serial integration by Codex. Only exact verified integration produces task.completed. A new commit after baseline synchronization needs a new delivery and renewed acceptance under the applicable policy: independent technical re-verification for code-only work, real human acceptance for UI/UX. Read back state and exact integration Git facts; never replay a completed merge.

## Events and Recovery

Use `events --project <artifact-dir> --cursor <seq> --follow --json`. Retain the last processed sequence and deduplicate by project/task/run/seq and delivery version. `turn.finished` is reasoning completion; `delivery.ready` is an evidence-validated candidate; `task.completed` is accepted exact-version integration. Runner exit is separate. Do not send repeated user-facing updates for delayed duplicate notifications. Hermes terminal watch patterns can expire after a notification lifetime cap; stop only the reader and renew from the retained cursor, not the runner.

`resume --input <json>` reconciles accurate history and Git without starting reasoning. Continue an unchanged authorized failed/interrupted task through the documented explicit feedback continuation in the same exact execution thread; do not replay choose or seek the same approval again. Dirty recovery requires current connection, exact terminated history, valid authorization/baseline, and unchanged file/mode/index fingerprint. Unknown outcomes remain uncertain; inspect receipts and raw protocol before action. Preserve worktrees, partial files and old failed attempts; no reset/clean/automatic rollback.

## Verification and Boundaries

- Read back the exact command receipt/state after every mutation; successful submission alone is insufficient.
- Verify source identity, exact thread continuity, real check results and Git facts; inventory untracked/index changes too.
- Keep automatic checks, live proven paths, delegated technical acceptance, actual human acceptance, deferred paths and failed attempts separate. Pure-code tools do not need an extra ceremonial human walkthrough after independent verification. A recovered thread is not a clean fresh-thread success.
- No automatic Kanban/multi-profile setup, fixed review rounds, mandatory execute-plan stage, publication or product deployment. Use optional reviews only when the current task calls for them.
- Scope activation to the active Hermes profile. Skill installation never authorizes unrelated profiles, applications, repository migration or old evidence deletion.

## Optional Pi Backend and Integrated Source

- Resolve the actual integrated CLI source with `git worktree list --porcelain` and exact HEAD checks. The original repository worktree may remain on older `dev` while `main` lives in a managed integration worktree. Run the CLI and read docs from the integrated checkout, not stale root code; do not silently switch or merge the original workspace. For this controller's self-hosted registration, inspect `~/Secret-Projects/development-artifacts/project-taskflow/self-hosted/project/state.json` read-only to locate worktreeRoot and its `_integration` checkout.
- Read the integrated `docs/backends.md`, `docs/pi-1.3.0.md` and `docs/pi-acceptance.md`. New projects can select `backend:"pi"` and `pi:{packageRoot,provider,model,thinking:{plan:"high",execution:"high"}}`; omission stays Codex. Provider/model are independent exact Pi identifiers. There is no existing-project or active-run backend migration. Codex has no runtime dependencies; Pi lazily loads the installed SDK. Verify actual binaries and versions.
- For Pi, the backend-specific procedure here supersedes Codex-only thread/mode details above. Formal plans/questions are Taskflow extensions; preserve the exact sessionRef/runId/toolCallId/entryId from templates rather than fabricating Codex identities. Fresh requires an independent native session and byte-identical full plan. Unsupported thinking fails explicitly, without clamping. The adapter pins the investigated 1.3.0 source fingerprint; future Pi upgrades require compatibility validation, not bypasses or automatic downgrades.
- Keep native termination, structured delivery, delegated technical acceptance and exact integration distinct. A real-model fixture passing after explicit same-session manifest repair is recovered success, not first-pass reliability. Preserve prior failures, actual source identities and SYNTHETIC decision labels.
- When self-hosting, finish and verify exact-version integration before gracefully stopping the idle old runner; the next runner must load integrated code. Never hot-reload healthy work or delete its evidence/worktrees.
