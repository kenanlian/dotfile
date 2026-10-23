---
name: project-taskflow
description: "Use for project analysis and development via Taskflow."
version: 1.5.2
author: "柯楠, Hermes Agent"
license: MIT
platforms: [macos, linux]
metadata:
  version: 1.5.2
  hermes:
    tags: [development, codex, taskflow, workflow]
    related_skills: [delegated-development-acceptance]
---

# Project Taskflow

Use the Controller for all Kenan project development, including small fixes. Hermes operates it and independently verifies deliveries; the configured backend implements. Codex is the default; Pi 1.3.0 is optional per new registration. A user may explicitly ask Hermes to maintain the workflow itself directly; that bounded exception never becomes a product-development fallback.

## When to Use

- Start or continue independent functional analysis, project tasks, direct fixes, planning, acceptance, integration or recovery.
- Keep workflow-design discussion read-only; do not create work or edit Skills until authorized. An explicit request for agent-led functional analysis uses the independent analysis channel, not development.
- No Hermes Kanban calls, heartbeat, board comments or mirrored task state in this workflow. Controller tasks are not Kanban cards.
- Do not switch to standalone Brief/relay when blocked, regardless of task size. Explain and resolve the blocker on the original task. Explicit one-off use of another coding tool requires the user's actual request, not an operator workaround.

## Prerequisites and Entry

- Versioned source and current Controller main checkout: `~/Secret-Projects/project-taskflow`; durable artifacts under `~/Secret-Projects/development-artifacts/`. The fixed entry points to this primary checkout's `scripts/taskflow.mjs`; confirm live Git/runtime identity rather than inferring it from cwd. The former self-hosted `_integration` has been migrated and removed; historical dev/task references do not identify current runtime sources, and their branches or worktrees may already have been separately cleaned. Query live Git inventory rather than assuming an old site still exists.
- Use `terminal(command="project-taskflow status --project <exact-artifacts-dir> --json")`. Installed entry: `~/.local/bin/project-taskflow`, backed by `scripts/taskflow.mjs`. It resolves the actual controller `main` checkout. If not installed, locate that checkout through `git worktree list` and invoke its absolute `scripts/taskflow.mjs` path. Never fall back to `node src/cli.mjs` in an uncertain cwd.
- Read `docs/workflow.md` and `docs/operations.md` from `status.runtime.sourceRoot`, plus the target project's AGENTS.md. `docs/handoff.md` and old acceptance reports are history, not the current operating contract.
- Inspect actual Node/Git/backend versions. Node >=22; no Controller runtime dependencies. Verify Codex authentication only when using Codex. Do not infer version/effort from old evidence.
- Inspect `permissionStatus`, exact registration path/commonDir/branch and genuine authorization evidence. A remote never grants network, push, PR, tag, release or deployment permission.
- Explicitly requested runtime-layout migrations follow [primary-worktree migration](references/primary-worktree-migration.md): move Git checkout, entry and all affected idle runners as one verified operation, then retire the old site. Never assume enabling primary-worktree support already migrated an existing project.

## Independent Analysis Channel

Use this when Kenan requests agent-led feasibility/risk/complexity analysis. Read current `docs/analysis.md`. Reuse the identified runner and project backend; do not launch a standalone agent.

Delegate the user's requirement and necessary constraints, not a prescribed analysis method or report template. Trust Codex/Pi to choose how to investigate and fulfill the requirement; provide a specific method only when the user explicitly requests it. Retain workflow authorization, read-only scope and exact session/question routing as constraints, not an analysis recipe.

1. Record the user's analysis question with `task add`, `kind:"analysis"`, no dependencies. This is a discussion topic, not a settled development requirement. Use existing project registration; do not register new repositories or broaden Git authorization implicitly. Analysis does not require a clean integration site; do not treat its integration-only permissionStatus blocker as a reason to create a worktree.
2. Copy current `templates.analyze`, replace commandId, and invoke `analyze --wait` through `terminal(background=true,notify=true)`. Analysis runs in config.repo with only prompt-based read-only constraints: no worktree/branch/commit, sandbox, role-tool matrix or file-fingerprint guard. Preserve the user's existing workspace. Controller recording evidence outside the repo is expected.
3. Relay full formal questions and actual answers via current `templates.answer` and `answer --wait`. Prompts to the agent say “需要澄清时向我提问”, not “ask the user/Kenan” or an explanation of Hermes relaying.
4. `wait.kind=analysis` contains the full Markdown result and version/run/session identity. Show the conclusion and uncertainties. A round's report is not the end of discussion or development permission. For the user's follow-up, copy current `templates.feedback`, keep previousRunId and submit actual feedback with a new commandId using `feedback --wait`; preserve the exact analysis session. Do not translate feedback into formal planning.
5. Only on the user's explicit finish use `templates.close` with genuine source/reason and outcome:analysis-completed. Read back closed/resolution; no accept, integration or cleanup. Active/uncertain runs need stop/resume reconciliation first. A cancelled topic is explicitly cancelled, not a completed analysis report.
6. Later development starts only from the user's newly supplied feature requirement in a separate planning/direct task. Do not automatically cite, link, inject or bind the analysis report, create dependencies, or infer execution authorization from feasibility approval.

Codex uses Plan mode + custom analysis developer instructions (xhigh) to retain structured questions, not formal-plan choice. Pi uses configured planning thinking and native assistant text. Reports are human-facing Markdown, saved from exact native final text with host-owned identity; do not parse prose verdicts into decisions. Missing final text and failed runs are failures, not reports. Native completion can precede report persistence: wait for analysis.ready or an explicit failure; do not restart reasoning in that gap. No true-service smoke is implied by SYNTHETIC fixtures.

## Development Procedure

1. **Identify and preflight.** Query the exact registered project. Read `permissionStatus`, `directEligibility.reason/next`, runner identity and task state before starting reasoning. Empty templates do not authorize an alternate workflow. New repositories require explicit registration/local Git scope.
2. **One identified runner.** Use `project-taskflow start --project <dir> --json`. It starts an exclusive runner with a unique log or confirms/reuses the exact healthy instance. Read back `runner.runtime` (source root/commit/fingerprint, Node), PID, instance and logFile. Legacy/mismatching runner or uncertain lock: inspect; explicitly stop only a confirmed idle old runner, then start. Never steal locks or restart active healthy work.
3. **Store the full requirement.** `task add --input <json>`. Each mutation has new commandId/projectId/taskId. Read the receipt and exact target after submission. Only actual completed dependencies unlock downstream work; `closed` does not mean completed.
4. **Select the lane inside Controller.** For a user-authorized, plan-exempt small fix, copy `templates.choose`, retain requirementHash/scopeRevision/baseline, use a fresh UUID and `choice:"direct"`. No formal plan or Brief relay. For other work, use `plan`; present the full native plan and `same-context`, `fresh-context`, `stay-plan` with no default. Revised plans need a new choice. Never fabricate a user's formal-plan choice.
5. **Develop in the task worktree.** The backend implements, tests and commits there, not in the primary worktree. Default Codex model `gpt-6.1-sol`; Controller explicitly sets plan xhigh and execution/integration high. Verify `run.effective`; null is not proof. Preserve exact thread/session identities for rework.
6. **Independent technical verification.** Load delegated-development-acceptance. Verify the exact commit/tree and complete file inventory. Re-run real checks, preferably `project-taskflow verify --project <dir> --input <checks.json> --json`: explicit cwd/commit and nonempty direct argv commands, full stdout/stderr, actual exits and before/after Git identity. No shell-pipeline summaries as evidence. Real behavioral fixtures need meaningful positive assertions, not print-only or tautological tests. A technical pass is not yet permission to submit Controller accept when user-operable acceptance remains.
7. **User operational acceptance, then record the real decision.** After technical verification, give Kenan concrete operations and expected results against the exact candidate: prepared environment/build identity, entry point, numbered actions, relevant edge cases, and how to report pass/failure. Leave the task awaiting acceptance and do not submit `accept` or integrate until his actual pass. This gate covers user-operable CLI/backend behavior as well as UI; objective testability or Hermes's successful host smoke does not waive it. Skip only when there genuinely are no meaningful operations for Kenan to verify; record why and use delegated technical acceptance. His pass authorizes immediate already-scoped local main integration and task-worktree cleanup without another confirmation, not push/tag/release. Use current accept/reject templates with exact version/commit/tree/manifest and genuine source/feedback; a changed candidate requires renewed checks and relevant operational acceptance. Preserve technical and user evidence separately. A plausible diagnosis is not a confirmed root cause; test-vault fixtures are not production exports. Byte equality needs content comparison, not length comparison.
8. **Controller integrates and cleans.** Accepted exact versions queue for serial ff-only integration. Primary worktree may stay on main: registered-local requires genuine authorization with `primaryWorktreeIntegration:true`. Controller uses that primary worktree only for clean exact integration, never task development. If main already lives in the managed `_integration`, retain that layout. No automatic checkout/detach/stash/reset/clean. Verify task.completed, integration evidence and cleanup separately. After the acceptance gate, follow through on local integration and removal of the task worktree and task branch; do not request another routine integration/cleanup approval. Cleanup is automatic and conservative; failure preserves sites and does not undo the Controller's existing completed status, but means workflow closeout remains incomplete and must be reported proactively with the precise blocker. Verify Git worktree/branch absence before claiming cleanup. Normal generated dependencies/build artifacts are not source edits; resolve their cleanup blocker safely, never blanket-delete unknown ignored files or use force as a shortcut. Do not repeat merges or manually push refs to bypass integration.
9. **Publish only when authorized.** Push/tag/release each need explicit user authorization. Operate in the actual integration location reported by Controller, whether primary or managed; do not switch the primary branch merely for release. Verify remote refs, CI result and exact release assets after writes. Publication is not external-plugin-review success.

## Recovery and Exceptional Closure

- `resume` reconciles exact native history and Git without starting reasoning. Continue the same execution thread through explicit feedback using the current authorization, previousRunId and, if needed, unchanged recoveryWorktreeHash. Preserve failed attempts and dirty scenes.
- After fixing a rejected command's condition, use a new UUID; reusing commandId returns the old receipt. An unknown launch/transport outcome is different: inspect and reuse the exact identity, never blindly resend reasoning.
- Outside-Controller work needs explicit exception provenance. Use `task close --input <json>` with `outcome:"external-completed"`, genuine source/reason and an already-integrated full commit. This produces `closed`, never fabricated runs/deliveries/task.completed, and never unlocks dependents. `cancelled` is also explicit. Archive only after reading back closure.
- Historical evidence defects: append `task note` with real findings/source, preserving original acceptance. Do not rewrite history or invent missing consent. New/renewed authorization goes through `project authorize`, on an idle project with exact binding and genuine source/statement. Old evidence remains preserved; no hand edits to state or registry.

## Acceptance Policy Boundary

The current user policy is technical verification → user operational acceptance when applicable → local main integration → task-worktree cleanup. The generic Controller `accept` operation currently queues integration immediately, so enforce the operational gate by withholding that command; save the technical report without pretending it is a separate Controller acceptance state. Existing repository docs may describe the older non-UI delegation default: use them for command mechanics, not to waive this newer explicit user gate. This Skill change does not itself change Controller state enums, cleanup code, past acceptances or legacy integration layouts.

## Monitoring

Use the integrated single-command wait contract in `docs/notifications.md`. For `analyze/plan/choose/answer/feedback/reject/accept/integrate/resume`, call `terminal(command="project-taskflow <operation> --project <dir> --input <file> --wait --timeout-ms 600000 --json", background=true, notify=true)`. The CLI rejects missing wait/no-wait before dispatch; do not add a second shell polling loop or long-lived output-pattern monitor. `--no-wait` is intentionally silent and only for an explicit diagnostic/automation need, never an unnoticed default. Keep the terminal notification attached to the actual invoking session, not a fixed home chat. The CLI cannot enforce the Hermes tool's notify flag or prove platform delivery.

The result contains the exact `receipt` and a live `wait` projection. Preserve and read both. `wait` failure/timeout does not invalidate a successful command: inspect exact state/receipt; repair transport only with the same commandId, never launch a duplicate with a new UUID. `wait.kind=timeout` (exit 2) does not cancel development. Resume notification only with `project-taskflow wait --project <dir> --task <id> --cursor <returned seq> --timeout-ms 600000 --json`, again with background/notify. It backfills current unresolved questions/analysis reports/plans/deliveries even at that cursor. Runner changes, stale questions, failures and uncertain runs require reconciliation, not more blind waiting. Do not assume this watcher survives Hermes/gateway/machine restart; reattach on conversation recovery.

On `question`, relay the full question and every option to Kenan, label project/task and keep the exact identity/requestId type. Advice is not a user decision. Answer only after his real response, unless he explicitly authorized that class of delegated decisions; record that provenance rather than inventing a human answer. Re-read `task show` and use the CURRENT `templates.answer` before submission. Use `answer --wait` to attach the next wait in the same operation. Deduplicate displayed notifications by project/task/run/notificationKey and cursor; a still-pending repeated key remains unresolved, not silently answered.

`turn.finished` is reasoning termination; `analysis.ready` is a discussion result, not development approval; `delivery.ready` is only a candidate; `task.completed` proves integration, not successful cleanup. Read cleanup independently (failed/skipped/null must be reported). `operation.failed` after a finished turn requires inspection. Report milestones and blockers, never generic Kanban heartbeat. Long waits should report elapsed time and the actual checkpoint without re-launching healthy work.

## Optional Pi Backend

Read integrated `docs/backends.md`, `docs/pi-1.3.0.md` and `docs/pi-acceptance.md`. Register new projects with `backend:"pi"` and exact pi packageRoot/provider/model/thinking. No implicit migration or fallback. Preserve real sessionRef/runId/toolCallId/entryId identities and pinned SDK checks. Pi formal plans are Taskflow extensions, not native Codex mode. Synthetic/real-model/recovered runs remain separately labeled.

## Verification

- Read back mutations from exact receipts/state; preserve commit/tree/manifest identity and provenance.
- Confirm the live/source and dotfile Skill copies are identical after updates; preserve unrelated dirty files. No automatic dotfile commit/push.
- Workflow updates must change active Skill/docs with the corresponding behavior. Remove obsolete prescriptions rather than appending contradictory exceptions. No Kanban, retired harness, fixed reviewer rounds or implicit publication.
- Do not modify other profiles or rely on hot-reloading tools/skills in the current session.
