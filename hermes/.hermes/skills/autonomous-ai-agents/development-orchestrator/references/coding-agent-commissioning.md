# Coding Agent Commissioning

`development-orchestrator` owns product policy and lifecycle. The selected transport adapter owns exact CLI syntax, permission translation, fresh/resumed outer-Session mechanics, process/result capture, and truthful Relay artifacts. External Coding Agent Skills under `~/Secret-Projects/agent_skills/skills` own engineering internals.

Do not call Hermes `skill_view` for `write-plan` or `execute-plan`, read their source merely to reproduce their protocol, or directly invoke/adjudicate `delegate-work`, `review-plan`, `review-patch`, `review-plan-conformance`, internal reviewer rounds, model tables, work-package scheduling, or persistence formats.

## Direct commissioning

Start one fresh writable parent through the selected adapter. Do not invoke an engineering workflow Skill.

```text
Implement this bounded task in the current repository.

Goal and observable acceptance:
- <Card contract>

Included scope and non-goals:
- <Card contract>

Settled decisions and authority boundaries:
- <Card contract>

UI classification:
- <required with renderer-ready handoff | not-required>

Inspect the repository before editing. Preserve unrelated work. Implement the task,
run focused verification plus relevant integration/end-to-end checks, and report exact
commands and observed results, changed-file scope, top-level outcome, artifacts, and
residual limitations. Do not commit, push, open a PR, release, deploy, publish, change
versions, or perform external side effects.
```

If broader coupling or a load-bearing decision appears, stop expansion and return evidence for Card reclassification.

## `write-plan` public contract

Start a fresh Planning Parent from the converged Card. Never resume or pass an Origin grounding Session ID. Use the adapter's explicit `write-plan` invocation syntax and writable planning mode.

Input:

- Goal and observable acceptance;
- Included scope and non-goals;
- Settled decisions;
- UI acceptance contract;
- authority boundaries.

```text
<adapter-specific explicit write-plan invocation>

Create the self-contained execution Plan from this converged development-task.v1 Card.
Re-verify repository facts independently. Preserve the Card's Goal, observable acceptance,
scope, non-goals, settled decisions, UI contract, and authority boundaries.

Run the external workflow through its own complete top-level gate. Do not implement or
commit. Return success/blocked status, the exact final Plan path, top-level gate status,
declared artifact pointers, and any unresolved user decision or residual limitation.
```

Hermes validates the returned top-level result and reads back the exact Plan path; it does not inspect or reconstruct internal review machinery.

## `execute-plan` public contract

Start a fresh writable Execution Parent—never the Planning Parent—with the exact accepted Plan path. Use the adapter's explicit `execute-plan` invocation syntax.

```text
<adapter-specific explicit execute-plan invocation>

Plan file: <exact accepted Plan path>
Execute the Plan through completion. Preserve unrelated work and the Card's authority
boundaries. The external workflow owns implementation, internal delegation/review,
adjudication, fixes, and final engineering verification.

UI handoff:
- <renderer-ready artifact and exact build/install/reload steps | complete non-UI handoff>

Report implemented/blocked status, exact verification commands and observed results,
changed-file scope, top-level gate status, artifact paths, and residual limitations.
Do not commit, push, open a PR, release, deploy, publish, change versions, or perform
unauthorized external effects.
```

## Rework

For UI behavior failure or incomplete handoff, resume the exact implementation parent through the adapter and send only the observed delta or missing contract. Describe behavior and evidence, not a guessed code cause. Report continuity loss before replacing a non-resumable Session.

## Top-level result boundary

A successful commissioning result includes:

- terminal success/blocked status and process exit truth;
- exact outer Session identity;
- requested/resolved model and permission mode;
- final message and changed-file scope;
- artifact pointers;
- top-level workflow gate status;
- unresolved decisions or residual limitations.

A streamed fragment, progress display, or self-report without the adapter's terminal result contract is not completion.
