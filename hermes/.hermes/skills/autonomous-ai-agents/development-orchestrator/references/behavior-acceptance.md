# UI Behavior Acceptance

The main Skill requires Watson behavior acceptance only when a task's accepted scope contains graphical UI behavior. This reference owns UI scenario construction, real-renderer execution, evidence, failure packets, and verdicts. It does not apply to non-UI CLI, API, service, migration, security, or developer-tooling tasks.

## Continuous UI-acceptance session

UI acceptance is led by one Watson session, normally the fresh session woken after the top-level implementation Relay reaches a verified terminal state.

1. Verify the terminal contract, artifact existence, and process exit.
2. Confirm the intended build is installed and running in the target renderer.
3. Execute deterministic UI checks directly through browser, `computer-use`, live DOM, or the application's official automation surface.
4. Use `delegate_task` only for context-heavy or genuinely parallel-safe scenario groups.
5. Never let two agents drive the same GUI/application instance concurrently.
6. Subagents return observations, preliminary `PASS | FAIL | BLOCKED`, and evidence paths; Watson reads back key evidence and owns the final verdict.
7. Subagents never modify product code, order rework, commit, push, release, or deploy.
8. Batch manual-only experience checks for the user when automation cannot judge them reliably.

Evidence convention:

```text
development-artifacts/<project>/acceptance/<card-id>-<slug>/<run-id>/<scenario-id>/
```

A simple UI task still has a card, so do not use a separate lightweight-task layout.

## Build the UI checklist

Derive a small decisive set of scenarios from the card's accepted UI contract. Each scenario states:

- renderer, build identity, starting state, and persisted state;
- exact user actions;
- expected visible output and UI state;
- relevant empty, failure, cancellation, repeated, restart, and persistence behavior; and
- cleanup before the next scenario.

Do not repeat the coding agent's non-UI engineering checks.

## Prepare the real renderer

Require the implementation parent to return:

- artifact/build identity;
- exact build and installation result;
- target application and version;
- setup, reload, restart, and fixture steps;
- known environmental limitations; and
- intended UI path.

Build success does not prove installation. Confirm the renderer is using the intended artifact before issuing a verdict.

## Exercise and observe

### Obsidian plugins

1. Confirm the intended vault, plugin installation path, and build identity.
2. Open Obsidian and reload the plugin or application as required.
3. Navigate through the real command, menu, view, settings, keyboard, drag/drop, or persistence flow.
4. Observe visible state, notifications, UI-backed files, and restart presentation.
5. Avoid permission dialogs, passwords, destructive vault operations, and unrelated user data.

Use the most reliable observable UI oracle:

- official Obsidian CLI/eval when it reads live renderer state;
- live DOM for visible content, geometry, active element, ARIA, and persistence projection;
- stable screenshots for layout and styling;
- native input for pointer-, hover-, drag-, menu-, keyboard-, and focus-dependent behavior.

Watson normally owns deterministic UI checks such as visible projection, filtering, sorting, grouping, pins, Box membership, empty/repeated presentation, metadata refresh as rendered, restart presentation, objective geometry, overflow, overlap, duplication, omission, and structural accessibility.

Reserve user-manual checks for actual VoiceOver speech, transient Hover/native menu behavior that cannot remain observable, long gesture smoothness, and subjective native feel, visual density, rhythm, or polish.

For one native interaction, make one normal attempt and at most one prescribed escalation. If it remains unverifiable, stop and mark the scenario `BLOCKED`; do not substitute DOM invocation for pointer-only, Hover, drag, native menu, or spoken-accessibility proof.

### Web and desktop applications

Start the real built application, exercise the visible user flow, and observe rendered state, navigation, focus, responsive layout, persistence presentation, error UI, and UI-triggered externally visible effects. Use authorized accounts and avoid destructive or publication actions.

## Record results

For each scenario record:

```text
Scenario: <name>
Environment/build: <identity>
Actions: <steps>
Expected: <visible result>
Observed: <visible result>
Verdict: PASS | FAIL | BLOCKED
Evidence: <screenshot/DOM/path/visible state or None>
```

A `BLOCKED` scenario is not a pass. Tests, lint, typecheck, builds, internal reviews, and executor claims never convert it into one.

## Failure packet

Return UI failures to the exact implementation parent with:

- environment/build identity;
- minimum reproducible UI steps;
- expected versus observed visible behavior;
- whether the failure is consistent or intermittent;
- UI state before and after; and
- screenshot, DOM, or other renderer evidence.

Describe behavior, not a guessed code cause. The implementation parent owns diagnosis, repair, verification, and any internal review rerun.

## Re-enter after UI failure

1. Resume the exact implementation session with the failure packet.
2. Start one new top-level rework Relay and monitor generation.
3. After the terminal wake, verify the failed UI scenarios first, then the necessary UI regression.
4. Report continuity loss before replacing a non-resumable session.

## Verdict

Pass only when every authorized UI scenario is `PASS`. If any is `FAIL`, return the card to `in_progress`; if any is `BLOCKED`, report the blocker and keep the card open. Non-UI checks and residual engineering limitations remain the coding agent's recorded responsibility rather than additional Watson acceptance scenarios.
