# UI Behavior Acceptance

Use only when accepted scope contains graphical UI behavior. This reference owns scenario construction, real-renderer execution, evidence, failure packets, and verdicts; application-specific mechanics stay in the matching acceptance Skill.

## Ownership and ordering

Required UI acceptance is led by the current **Implement Worker** after a frozen local candidate commit exists and before push or managed handoff:

```text
terminal implementation Relay + engineering checks
→ devflow current-run/candidate validation
→ local Card-trailer candidate commit + candidate manifest
→ acquire named UI lease
→ load exact candidate build and execute real-renderer scenarios
→ persist candidate-bound evidence and release lease
→ authorized push only after PASS
→ recheck current run/candidate
→ devflow_implement_handoff
```

The Review Worker does not drive UI again. It verifies that PASS evidence and any manual verdict belong to the current board/card/feature, producing implement run, candidate commit, diff range, accepted Plan SHA, and valid lease interval. A new candidate or Plan invalidates earlier evidence.

## UI lease

Before any agent drives a shared application resource, call `devflow_ui_lease(action=acquire)` with a stable resource such as `obsidian:<acceptance-vault>`. Only an owning Implement Worker with a frozen current candidate may acquire it.

- Never let two agents or sessions drive one renderer/vault concurrently.
- A live owning holder blocks acquisition.
- Reclaim only when the holder process is dead and its run is no longer current.
- The owner releases after evidence persistence and records cleanup. A lease is local coordination, not lifecycle truth.
- If another session or the user is using the resource, stop rather than attempting to win focus or overwrite shared state.

## Evidence layout and identity

```text
~/Secret-Projects/development-artifacts/<board>/tasks/<card-id>/
  ui/<candidate-sha>/<implement-run-id>/
```

Record one run manifest plus bounded scenario evidence. It includes:

- schema/version and artifact content SHA;
- board, Card, feature, stage, implement run and attempt;
- candidate commit and diff base/head;
- accepted Plan path/SHA when execute-plan;
- terminal Relay/session identity;
- candidate/build/install identity;
- fixture starting state and cleanup result;
- UI lease resource/holder/acquired/released identity;
- each scenario's actions, expected/observed result, verdict, and evidence paths;
- automation boundaries and pending manual items.

File presence is not PASS; the Harness parses identity and verdict.

## Build the checklist

Derive a small decisive set from the Card's accepted UI contract. Each scenario states renderer, exact candidate build, starting/persisted state, user actions, expected visible result, relevant empty/failure/cancel/repeat/restart behavior, evidence oracle, and cleanup. Do not repeat the Coding Agent's non-UI checks.

## Prepare the renderer

Require the implementation parent to return artifact/build identity, build/install result, target application/version, setup/reload/restart/fixture steps, environmental limitations, and intended UI path. Build success does not prove installation; verify the running renderer loaded the exact candidate artifact.

## Exercise and observe

Use deterministic UI checks through the real browser/application, `computer-use`, live DOM, or the application's official automation surface. `delegate_task` is allowed only for context-heavy or parallel-safe scenario groups that do not share one renderer. Subagents may observe and persist scoped evidence but never modify product code, order rework, commit, push, release, deploy, or own the final verdict. Watson reads back load-bearing evidence.

For Obsidian plugins, use the `obsidian-plugin-acceptance` Skill. Prefer official CLI/eval for live state, live DOM for visible/ARIA/geometry evidence, stable screenshots for layout, and native input for pointer/hover/drag/menu/keyboard/focus behavior. Never operate on the primary vault or unrelated user data.

Watson normally owns deterministic visible projection, filtering, sorting, grouping, pins, Box membership, empty/repeated presentation, metadata refresh as rendered, restart presentation, objective geometry, overflow/overlap/duplication/omission, and structural accessibility.

Reserve user-manual checks for actual VoiceOver speech, transient hover/native menus that cannot remain observable, long-gesture feel, and subjective native feel/density/rhythm/polish. For one native interaction make one normal attempt and at most one prescribed escalation; if still unverifiable, mark BLOCKED rather than substituting a weaker oracle.

## Scenario record

```text
Scenario: <name>
Environment/build: <candidate identity>
Starting state: <fixture/settings>
Actions: <steps>
Expected: <visible result>
Observed: <visible result>
Verdict: PASS | FAIL | BLOCKED
Evidence: <paths or None>
Cleanup: <result>
```

Tests, lint, typecheck, builds, reviews, and executor claims never convert BLOCKED to PASS.

## Failure and rework

A FAIL is a correctable implementation result, not a blocker. Keep implementation ownership and resume the exact recorded session with:

- candidate/build identity;
- minimal UI reproduction;
- expected versus observed behavior;
- consistency/intermittency;
- before/after state; and
- screenshot/DOM/renderer evidence.

Describe behavior, not a guessed cause. Start a new guard v2 rework attempt with a fresh output directory/result path and mandatory accepted-Plan Auto Handoff for execute-plan. The repaired output becomes a new local candidate; old evidence remains historical but cannot satisfy the gate. Verify failed scenarios first, then necessary regression.

Use BLOCKED only for permission, external environment, unavailable automation evidence, or a manual-only decision. Persist the pending checklist, release/clean the UI resource, and call typed `needs_input`. Origin records Kenan's candidate-bound verdict; after unblock a fresh Implement Worker revalidates candidate/Plan before continuing. Manual FAIL returns to exact-session rework.

Pass only when every authorized automated scenario is PASS and every required manual item has a current candidate-bound PASS. Release the lease and verify cleanup before handoff.
