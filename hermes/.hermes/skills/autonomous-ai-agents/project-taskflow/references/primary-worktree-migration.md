# Migrate Controller main to its primary worktree

Use only for an explicit user request to migrate the Controller's runtime/integration layout. This is administrative relocation of the same verified commit, not product implementation, an implicit branch cleanup, or permission to change Controller code. Do not rewrite completed task history or old runtime evidence.

## Preflight

1. Query the exact registered project and read the live runtime's workflow/operations docs. For this machine, the self-hosted registration is `~/Secret-Projects/development-artifacts/project-taskflow/self-hosted/project` (not its parent).
2. Inventory Git worktrees, exact main/dev heads, primary and old-site tracked/index/untracked/ignored files, special index flags, `.dev` links and command-entry realpath. Preserve a historical dev branch; do not reset it. Refuse dirty or unknown sites.
3. Inventory every actual runner using the old source root, not only the Controller's own runner. Save each exact project path, PID, instance, commit/fingerprint and log. All must be idle: no active/uncertain turn, pending question/session start, task authorization or integration queue. An idle app-server process is not an active turn; verify persisted task state.
4. If the Controller project's registration lacks `primaryWorktreeIntegration:true`, renew via `project authorize` while its old runner is healthy and idle. Preserve exact scope/binding, cite this user's actual migration authorization, read back the renewal and leave historical evidence intact. Never hand-edit state or registry.

## Relocate without losing the entry

1. Submit a new-UUID stop command for each affected idle runner, save receipts and verify both old PID exit and runner.lock release. Never steal locks, kill an uncertain turn, or restart only one runner while removing a shared source tree.
2. Save the current entry target. At the expected unchanged clean main commit, detach the old `_integration` to release main; switch the clean primary checkout from dev to main. Do not invoke the main-resolving wrapper during the brief interval with no checked-out main. Check commit identity and preserved `.dev` symlink immediately; use no force/reset/stash.
3. Atomically repoint the existing known command symlink to the primary checkout's executable `scripts/taskflow.mjs`. Verify the exact target before and after. Refuse an unexpected real file/link. Read-only status must now report primary sourceRoot and an unblocked primary integrationSite.
4. Start every affected project through the fixed entry. Assert new instance, unique log, primary sourceRoot/cwd, unchanged sourceCommit/fingerprint. Call start a second time to exercise actual same-instance ping/reuse; a lock file alone is not health.
5. Only after every new runner is healthy, non-forcibly remove the old clean detached integration worktree. Preserve other task worktrees and branches unless separately requested.

## Verify and report

- Assert old path absent from filesystem and Git worktree inventory; command symlink and all actual runner command lines must use the primary path.
- Probe the live runners again after removal. Compare historical task status, acceptance, integration, deliveries and task counts with the before snapshots.
- Run `npm run check` from the primary checkout with a fresh `TASKFLOW_TEST_ROOT` under the project's validation directory; retain full stdout/stderr and true exit. The suite includes synthetic fixtures: do not label it new live-model verification. Actual runner starts/pings are real process verification but start no reasoning.
- Confirm main commit/tree unchanged, primary clean, old dev and unrelated task sites preserved. Do not commit/push or migrate other profiles implicitly.
- Update the active Skill and its dotfile mirror, replace stale environment notes, and save a migration report. Keep old evidence references as history; do not recreate an obsolete path just because a historical report mentions it.

Current machine layout: source/entry runtime `~/Secret-Projects/project-taskflow` on main; fixed entry `~/.local/bin/project-taskflow`; self-hosted project registration `~/Secret-Projects/development-artifacts/project-taskflow/self-hosted/project`. Project artifacts and task worktree roots remain at their registered locations. Generic legacy `_integration` support still exists for other registrations; this migration does not change Controller code or cleanup semantics.
