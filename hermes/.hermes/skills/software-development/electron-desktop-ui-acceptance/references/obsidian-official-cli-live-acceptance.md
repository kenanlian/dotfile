# Official Obsidian CLI as a Live Acceptance Transport

Use this route only when the target is the running desktop Obsidian app, the official CLI is enabled, and native/typed input cannot reach the exact renderer window. It supplements the CDP workflow; it does not silently upgrade synthetic DOM events to trusted input.

## Valid uses

- Confirm app/vault/version and loaded plugin identity.
- Read small live-DOM projections: selected navigation row, rendered card titles/order, ARIA state, visible Section IDs, search results, and absence of out-of-scope UI.
- Read live plugin settings and public runtime state.
- Invoke an official command such as `app:reload`, then wait and verify the rebuilt live surface.
- Use a narrow public plugin API to prepare an isolated fixture, provided the behavior verdict is read from the rendered application.

Direct `element.click()`, `value=`, and synthetic DOM events are a declared downgraded route. They may verify application data flow when native input is impossible, but do not claim trusted keyboard/pointer behavior from them. Keep any such limitation in the acceptance report.

## Persistence-focused workflow

1. Use an isolated Vault with `data.json` created before the change.
2. Hash repository and installed `main.js`, `manifest.json`, and `styles.css`; require exact matches.
3. Hash pre-existing `data.json` before installation.
4. Through the running app, exercise persisted Section state, global/per-source sort, pins, search/filter projection, and Box membership as relevant.
5. Reload with the official `app:reload` command and re-read the live DOM/settings.
6. Restore all temporary fixture state through the running plugin, reload once more, and hash `data.json` again.
7. Exact pre/post `data.json` hash equality after restoring original values is strong evidence that normalization did not rewrite the persisted representation.
8. Capture real renderer screenshots at decisive states and record the input route honestly.

This route is especially useful for migration-only or no-visible-change work where the decisive risks are persisted-state reset, per-source configuration loss, stale projection, and unexpected new UI.
