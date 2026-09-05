---
name: obsidian-plugin-acceptance
description: "Use when testing Obsidian plugins via obsidian-cli eval."
version: 1.0.0
license: MIT
platforms: [macos]
tags: [obsidian, plugin, behavior-acceptance, eval, dom]
---

# Obsidian Plugin Acceptance via CLI eval

Exercise a plugin through the same running app a user operates, using the official `obsidian-cli` `eval` command as the primary oracle. This skill owns Obsidian-specific execution mechanics; the acceptance lifecycle (scenarios, verdicts, failure packets, manual-check batching) lives in `development-orchestrator` references/behavior-acceptance.md.

## When to Use

- Behavioral acceptance of an Obsidian plugin build (own or third-party) in a real vault.
- Verifying a plugin's persisted settings, DOM projection, ARIA tree, or live response to metadata edits.
- Preparing a fixture vault and proving which build is actually loaded.

Not for note/vault content management — that is the `obsidian` skill.

## Prerequisites

- Obsidian desktop running; CLI enabled (Settings → General → Advanced → Command line interface).
- Executable: `/Applications/Obsidian.app/Contents/MacOS/obsidian-cli` (the GUI binary is NOT the CLI).
- A scratch vault dedicated to acceptance (never the user's primary vault). `vaults` lists registered names.

### 0. CLI fallback: direct CDP eval (when obsidian-cli hangs)

`obsidian-cli` can hang outright (vault enumeration stalls; every invocation eats the full timeout). Obsidian is often already running with `--remote-debugging-port=9223` — drive the exact same eval surface over CDP instead: `GET http://127.0.0.1:9223/json/list`, pick the `app://obsidian.md` page target, open its WebSocket, and issue `Runtime.evaluate` with `returnByValue: true`. `scripts/cdp_eval.py` in this skill is a stdlib-only client (handshake, masked frames, request/response only; event frames skipped). Every pattern below (DOM probes, `app.plugins.*`, vault ops, `app:reload`) works identically through it. Note `awaitPromise: true` is flaky there ("Promise was collected") — fire the async op without awaiting, sleep, then poll readback.

## Core eval patterns

Invoke as `"$CLI" vault=<name> eval code="<js>"`. Prefer `subprocess.run([...])` from execute_code to avoid shell-quoting hell; for long probes, write the JS to a file and pass its contents as the `code=` argument. Return values print as `=> <json>`; write probes as IIFE-style `(() => {...})()` or `(async () => {...})()` returning `JSON.stringify(...)`.

### 0.5. When docs are ambiguous: read the Obsidian core bundle

`obsidian.asar` ships readable (minified) source for the whole app. Extracting `app.js`/`app.css` and reading the actual implementation settles runtime questions the API docs don't: config defaults (`nativeMenus` macOS default), platform branches, icon-name resolution, DOM/CSS structure of core widgets. Recipe and facts settled so far (Menu render paths, `setIcon` vs `setChecked`, icon hijack via `addIcon`): `references/obsidian-core-bundle.md`.

### 1. Prove build identity before deriving scenarios

1. Hash the built artifact (e.g. `shasum -a 256 main.js`) and copy it into `<vault>/.obsidian/plugins/<id>/`.
2. Reload the plugin through the app's own API: `await app.plugins.disablePlugin('<id>'); await app.plugins.enablePlugin('<id>')`.
3. Probe for a field only the new build has (new settings key, new command id). Absent → old code is still running; stop and fix reload before testing.
4. Minified-bundle pitfall: production `main.js` unicode-escapes CJK literals, so grepping for the Chinese copy of a new UI string yields 0 in BOTH old and new bundles. Grep ASCII identifiers instead (i18n key names like `propertiesDisabledInBox`, new method names): require count >0 in the new bundle and 0 in the installed one.

### 2. Read state from both surfaces

- Runtime: `<plugin>.settingsStore.memory` (or the plugin's settings holder) is the normalized flat view — normalization (lowercasing, dedupe, sort, dropping stale entries) is observable here.
- Disk: `<plugin dir>/data.json` shows the layered document (preferences / workspace / userData) exactly as persisted; remember a field may live in a different layer than you guessed (check both).
- Wait for debounced workspace writes (a bounded ~1–2 s sleep) before asserting disk state.

### 3. Interact through the DOM

- Rows: `row.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, ctrlKey: true}))` — modifier semantics (Ctrl/Cmd for additive select) work.
- Inputs (Svelte): set value via the native setter `Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, v)` then `input.dispatchEvent(new Event('input', {bubbles: true}))`.
- Buttons: find by `aria-label` text, then `.click()`.
- **HTML5 drag rows (Svelte 5)**: synthetic `new DragEvent(...)` has a null `dataTransfer`, and the handler's `event.dataTransfer.setData(...)` then throws, silently killing the drag state machine — `Object.defineProperty(ev, 'dataTransfer', {value: {effectAllowed:null, dropEffect:null, setData(){}, getData(){return ''}}})`. Also Svelte 5 batches state: dispatch, `sleep(~300ms)` for the re-render, THEN read classes (`is-*-dragging` / drop indicators) — same-frame reads are false negatives. Verified: favorites drag reorder acceptance 2026-09-05.
- Menus/modals: modal buttons click fine; transient native/context menus are manual-check territory — route the same behavior through a deterministic alternative (header primary action, settings API) and batch menu items for the user.
- **Native `Menu` never mounts while the Obsidian window is off-Space / not frontmost.** `new Menu().showAtPosition()` from ANY caller (your plugin, card context menus, even Obsidian's own file-explorer right-click) silently creates nothing: no DOM node, no console error, no unhandled rejection. Custom DOM-anchored layers (e.g. Svelte popovers) in the same window still open, so a popover-to-native-Menu refactor looks like a code regression when it is the environment. Before filing one: (a) trigger one of Obsidian's OWN native menus in the same session — if it also fails, stop blaming the plugin; (b) A/B the previous build through the identical click path; (c) check the signature `window.electronWindow?.isFocused?.() === false` while `document.hasFocus()` reports `true`. Synthetic `Input.dispatchMouseEvent` clicks DO reach the button (verify with a capture-phase listener) yet the menu still will not mount; `Page.bringToFront`, `Emulation.setFocusEmulationEnabled`, `open -a`, and cua foreground CGEvents did not recover it cross-Space. Batch the visual check for the user. Full probe chain and recovery attempts: `references/off-space-native-menus.md`.
- **macOS native-menus mode (default on): native Menu renders as a real NSMenu with ZERO DOM** — `document.querySelector('.menu')` is null even when the menu is open and focused. Never assert menu content via DOM on macOS without first checking `app.vault.getConfig('nativeMenus')` (null = native ON on macOS) or forcing `app.vault.setConfig('nativeMenus', false)`. In native mode `MenuItem.setIcon()` is silently dropped (template maps only label/enabled/checked/type/click) — selection marks must use `setChecked()`, never `setIcon('check')`. Details: `references/off-space-native-menus.md`.

### 4. Checkbox truth

Obsidian modal checkboxes are class-driven: read `.checkbox-container.is-enabled`. The `input.checked` DOM property desyncs and reports false for visibly checked boxes — do not file defects from it.

### 5. Keyboard evidence

Synthetic `keydown` reaches activation/focus handlers (Enter activate, Space toggle-add, ArrowDown roving). For collapse/expand assert via the chevron button (`[aria-label=折叠/展开]` or equivalent) click; physical key feel stays on the manual list.

### 6. Live metadata edits

Edit through the app pipeline so metadataCache events fire: `await app.vault.process(file, content => transformed)`. Assert convergence (counts, checked rows, cards, empty states) after a bounded sleep — no reload. To test out-of-source isolation, edit a note outside the current source and assert the view is unchanged.

### 7. Multiple views

Open another leaf: `const leaf = app.workspace.getRightLeaf(false); await leaf.setViewState({type, active: true}); app.workspace.revealLeaf(leaf)`. Disambiguate each view root by its scope label text (e.g. `[class*=scope]` → `当前范围 X`), not DOM order. Shared settings changes must appear in every root; facet counts stay per-source. Detach extras with `leaf.detach()` when done.

### 8. Fixture hygiene

Create fixtures through the CLI (`create path=... content=...`) so the app indexes them. Beware: `create` on an existing path creates a suffixed duplicate ("Note 2.md") instead of overwriting — check the result line, and use `app.vault.process` for in-place rewrites. `delete` moves to trash. Never run `<cli> <subcmd> --help` as a bare command — unrecognized args execute a real default action (created "Untitled.md" in-session); read help only via the shell's own help path or docs. Clean up stray files before recording the verdict. A/B click-testing toolbar buttons drives REAL actions (a note button creates a file at vault root): snapshot `app.vault.getMarkdownFiles().length` first, trash strays via `app.vault.trash(file, false)`, and reconcile against a filesystem `find ... -name '*.md'` count — the in-memory index can lag one cycle, so trust the disk count plus `.trash` mtimes for the ledger.

### 9. Sidebar view instances and the plugin action layer

- `app.workspace.iterateAllLeaves` does NOT enumerate sidebar leaves. To find a sidebar view instance walk `app.workspace.leftSplit.children[].children[]` (and `rightSplit` likewise) matching `l.view.getViewType()`.
- Prefer the plugin's own action layer over DOM/menu driving when it exists: view instances commonly expose `view.modules.*` (controllers/actions such as `boxActions`, `propertyActions`, `scopeController`) and TypeScript-`private` methods survive esbuild minification and remain callable by name (e.g. `view.selectFolderFromNav(path)`). Read the source first to learn the real signatures (e.g. `applyValueFilter(key, {kind:'text',value:...}, additive)`).
- Contract paths matter: two routes that look equivalent can have deliberately different semantics (observed: `exitBoxScope()` did not clear workspace filters while `selectFolderFromNav()` did — a documented parity decision, not a bug). Before filing a defect from a surprising observation, grep the plan/tests for the exact entry point the contract names.
- Full-app reload round trip (restart-persistence scenarios): `app.commands.executeCommandById('app:reload')`, then poll a cheap eval (`app.plugins.enabledPlugins.has('<id>')`) until true, and re-bind every cached view/DOM reference afterward — old references are stale across reload.

### 10. Parallel-session collision in the shared vault

eval stdout echoes OTHER CLI clients' activity as `Received CLI command [...]` lines. If those lines show fixtures/commands you did not issue, another session is driving the same vault. Plugin settings/scope are global to the vault, so two concurrent acceptance runs corrupt each other's state (filters, scope, fixtures). Stop and confirm with the user before continuing; after they finish, re-read all shared state (scope, `filter.*`, boxes, view references) instead of trusting your pre-collision snapshot.

## Recommended scenario order

Identity → migration/default state → chooser/picker draft & atomicity (Cancel vs Done) → facet/list rendering → selection semantics (single, OR, AND, composition with search/tags, pin bypass attempt) → source switching → live metadata → removal atomicity (key removal, zero-count active row) → reload persistence round-trip → keyboard/ARIA/query → multiple views. Record one `verdict.md` per run under the project's acceptance evidence path.

## Verification

- [ ] Build identity proven in the running app before scenarios
- [ ] Every verdict backed by eval readback (DOM, runtime settings, or data.json)
- [ ] No defect claimed from `input.checked` (class-driven checkboxes)
- [ ] Transient-menu / physical-key / VoiceOver items batched for the user with prepared state
- [ ] Native-menu display failures re-tested against Obsidian's own menus and/or the previous build before being called a plugin regression
- [ ] Fixture stray files cleaned; verdict.md written and referenced
