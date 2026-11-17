---
name: obsidian-plugin-acceptance
description: "Use when testing Obsidian plugins via obsidian-cli eval."
version: 1.2.1
license: MIT
platforms: [macos]
tags: [obsidian, plugin, behavior-acceptance, eval, dom]
---

# Obsidian Plugin Acceptance via CLI eval

Exercise a plugin through the same running app a user operates, using the official `obsidian-cli` `eval` command as the primary oracle. This skill owns Obsidian-specific execution mechanics.

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

Invoke as `"$CLI" vault=<name> eval code="<js>"`. Prefer `subprocess.run([...])` from execute_code to avoid shell-quoting hell; for long probes, write the JS to a file and pass its contents as the `code=` argument. For machine-readable results, wrap an expression as `(async()=>JSON.stringify(await (<expression>)))()` and parse its `=> ` result; returning a bare object can produce multiline pretty output instead of one JSON record. Construct embedded JavaScript string literals with `json.dumps(text, ensure_ascii=False)` so Python does not turn escaped newlines into invalid JavaScript. Preserve raw stdout/stderr alongside parsed assertions. Save the exact executable probe and helper definitions before running it, including any fault injection and `finally` restoration; output-only logs cannot reconstruct an intermittent failure. For pane-routing and chooser probes, record the active window identity, active leaf, candidate leaf IDs/windows and relevant state immediately before the call and after settlement, because later snapshots can miss the failing lifecycle condition.

### 0.5. When docs are ambiguous: read the Obsidian core bundle

`obsidian.asar` ships readable (minified) source for the whole app. Extracting `app.js`/`app.css` and reading the actual implementation settles runtime questions the API docs don't: config defaults (`nativeMenus` macOS default), platform branches, icon-name resolution, DOM/CSS structure of core widgets. Recipe and facts settled so far (Menu render paths, `setIcon` vs `setChecked`, icon hijack via `addIcon`): `references/obsidian-core-bundle.md`.

### 1. Prove build identity before deriving scenarios

1. Copy the candidate's complete runtime set (`main.js`, `manifest.json`, and any external `styles.css`) into `<vault>/.obsidian/plugins/<id>/`, then compare source and installed bytes or SHA-256 for every copied file. Record the accepted commit/tree with these hashes; a matching version label or bundle alone does not prove that styles and manifest belong to the same candidate.
2. Reload the plugin through the app's own API: `await app.plugins.disablePlugin('<id>'); await app.plugins.enablePlugin('<id>')`.
3. Probe for a field only the new build has (new settings key, new command id). Absent → old code is still running; stop and fix reload before testing. If the new code marker exists but `plugin.manifest.version` still reports the previous installation, refresh the app's cached manifest with `app:reload`, wait for plugin readiness, and rebind all plugin/view references before checking again; plugin disable/enable alone can retain cached manifest metadata.
4. Minified-bundle pitfall: production `main.js` unicode-escapes CJK literals, so grepping for the Chinese copy of a new UI string yields 0 in BOTH old and new bundles. Grep ASCII identifiers instead (i18n key names like `propertiesDisabledInBox`, new method names): require count >0 in the new bundle and 0 in the installed one.

### 1.5. Prove visible preview readiness after reload

1. After loading/reloading, rebind plugin and view references, then inspect `document.visibilityState`, native window visibility/focus and the plugin's work-gate/preview diagnostics before judging skeletons or taking the handoff screenshot. Foreground-load completion can legitimately precede preview hydration when a hidden document pauses its work gate.
2. If the dedicated acceptance window may be brought forward, use its own native window handle: `const w = window.electronWindow; w.show(); if (w.isMinimized?.()) w.restore(); w.focus();`. Then boundedly wait for the gate to resume and assert actual note content replaces placeholders. CDP `Page.bringToFront` alone is not proof of native visibility. Keep this intervention scoped to the isolated fixture, not another user window.
3. Capture the product-handoff screenshot only after content is visibly loaded. Treat preview-gate recovery separately from native-menu rendering; showing a window does not establish that every menu or physical input path works.

### 2. Read state from both surfaces

- Runtime: `<plugin>.settingsStore.memory` (or the plugin's settings holder) is the normalized flat view — normalization (lowercasing, dedupe, sort, dropping stale entries) is observable here.
- Disk: `<plugin dir>/data.json` shows the layered document (preferences / workspace / userData) exactly as persisted; remember a field may live in a different layer than you guessed (check both).
- Wait for debounced workspace writes (a bounded ~1–2 s sleep) before asserting disk state.

### 2.5. Verify third-party file creation through its consumer

1. Reproduce **create → first open** without pre-opening or waiting for indexing; a fresh file can lack cached metadata even when its extension and bytes are valid. Record the immediate view type, then check later recognition separately so eventual indexing cannot conceal incorrect first-open routing.
2. Assert the requested view **and actual editor readiness**, then create a meaningful element, save, close and reopen through the ordinary product path. A correct view-type enum can precede asynchronous editor initialization; it is not proof that the document loaded.
3. Validate saved content through the consumer's parser before comparing semantic identifiers; compression or serialization can remove literal identifiers from raw text without losing data. Keep byte-equality checks for artifact identity, not semantic persistence across a consumer save.
4. Exercise unavailable dependencies in an isolated vault: snapshot file paths and editor-tab identities, disable the dependency, invoke the real action, assert the notice and unchanged snapshots, then restore its original enabled state in `finally` and verify readiness. Label absent-plugin unit fixtures separately from a real disabled-plugin run; do not claim an uninstall test you did not perform.

See `references/plugin-file-lifecycle.md` for the Excalidraw consumer recipe and fixture cleanup details.

### 3. Interact through the DOM

- Rows: `row.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, ctrlKey: true}))` — modifier semantics (Ctrl/Cmd for additive select) work.
- Inputs (Svelte): set value via the native setter `Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, v)` then `input.dispatchEvent(new Event('input', {bubbles: true}))`.
- Buttons: find by `aria-label` text, then `.click()`.
- **Collapsed sections render no child rows AND no empty-state text** — a nav/accordion section with `aria-expanded="false"` hides its disabled/empty placeholder entirely. Before claiming a missing empty state, read `aria-expanded` and click the section header to expand, then re-assert.
- **HTML5 drag rows (Svelte 5)**: synthetic `new DragEvent(...)` has a null `dataTransfer`, and the handler's `event.dataTransfer.setData(...)` then throws, silently killing the drag state machine — `Object.defineProperty(ev, 'dataTransfer', {value: {effectAllowed:null, dropEffect:null, setData(){}, getData(){return ''}}})`. Also Svelte 5 batches state: dispatch, `sleep(~300ms)` for the re-render, THEN read classes (`is-*-dragging` / drop indicators) — same-frame reads are false negatives. Verified: favorites drag reorder acceptance 2026-09-05.
- Menus/modals: modal buttons click fine; transient native/context menus are manual-check territory — route the same behavior through a deterministic alternative (header primary action, settings API) and batch menu items for the user.
- **Native `Menu` never mounts while the Obsidian window is off-Space / not frontmost.** `new Menu().showAtPosition()` from ANY caller (your plugin, card context menus, even Obsidian's own file-explorer right-click) silently creates nothing: no DOM node, no console error, no unhandled rejection. Custom DOM-anchored layers (e.g. Svelte popovers) in the same window still open, so a popover-to-native-Menu refactor looks like a code regression when it is the environment. Before filing one: (a) trigger one of Obsidian's OWN native menus in the same session — if it also fails, stop blaming the plugin; (b) A/B the previous build through the identical click path; (c) check the signature `window.electronWindow?.isFocused?.() === false` while `document.hasFocus()` reports `true`. Synthetic `Input.dispatchMouseEvent` clicks DO reach the button (verify with a capture-phase listener) yet the menu still will not mount; `Page.bringToFront`, `Emulation.setFocusEmulationEnabled`, `open -a`, and cua foreground CGEvents did not recover it cross-Space. Batch the visual check for the user. Full probe chain and recovery attempts: `references/off-space-native-menus.md`.
- **macOS native-menus mode (default on): native Menu renders as a real NSMenu with ZERO DOM** — `document.querySelector('.menu')` is null even when the menu is open and focused. Never assert menu content via DOM on macOS without first checking `app.vault.getConfig('nativeMenus')` (null = native ON on macOS) or forcing `app.vault.setConfig('nativeMenus', false)`. In native mode `MenuItem.setIcon()` is silently dropped (template maps only label/enabled/checked/type/click) — selection marks must use `setChecked()`, never `setIcon('check')`. Details: `references/off-space-native-menus.md`.

### 3.5. Native draft editors and presentation-specific smoke

1. Open the actual product entry in a dedicated test vault and obtain the live draft/editor through its owning manager. For auxiliary windows, construct input/composition events with `element.ownerDocument.defaultView`, not the main window's constructors.
2. When the draft exposes no setter, use `draft.editor.focus()` and its owning document's `execCommand('insertText', false, text)`. To replace this draft's entire contents, issue `execCommand('selectAll')` only after focusing that isolated editor. Wait for the host editor's update before reading `editor.getValue()`; same-frame reads can still contain the previous document.
3. Exercise Send through the real button: assert composition blocks submission, end composition, then click twice. Read the created note through `app.vault.read`, assert exact text and exactly one matching file, and repeat for same-name append. When boxes are selected, independently assert persisted membership rather than treating note creation as complete submission.
4. For a plugin with an injected presentation contract, temporarily selecting its mobile Modal in the real desktop host can verify native-editor, folder/box chooser and coordinator integration. Snapshot the original contract/settings, restore them in `finally`, trash only owned fixtures, and verify restoration. Label this **desktop-host presentation injection**, never mobile-device, keyboard, touch, resource-policy or performance acceptance; retain applicable real-device product checks.

### 4. Checkbox truth

Obsidian modal checkboxes are class-driven: read `.checkbox-container.is-enabled`. The `input.checked` DOM property desyncs and reports false for visibly checked boxes — do not file defects from it.

### 5. Keyboard evidence

Synthetic `keydown` reaches activation/focus handlers (Enter activate, Space toggle-add, ArrowDown roving). For collapse/expand assert via the chevron button (`[aria-label=折叠/展开]` or equivalent) click; physical key feel stays on the manual list.

### 6. Live metadata edits

Edit through the app pipeline so metadataCache events fire: `await app.vault.process(file, content => transformed)`. Assert convergence (counts, checked rows, cards, empty states) after a bounded sleep — no reload. To test out-of-source isolation, edit a note outside the current source and assert the view is unchanged.

### 7. Multiple views

Measure the actual pane/content dimensions before asserting how many regions should remain visible; a wide browser viewport does not guarantee enough space after adjacent editors and navigation consume it. For virtualized reading-position checks, compare the contract's semantic anchor (item identity plus viewport offset) after remount and measurement settle, not absolute `scrollTop`, because row-height remeasurement can change pixel totals while preserving the reader's position.

Open another leaf: `const leaf = app.workspace.getRightLeaf(false); await leaf.setViewState({type, active: true}); app.workspace.revealLeaf(leaf)`. Disambiguate each view root by its scope label text (e.g. `[class*=scope]` → `当前范围 X`), not DOM order. Shared settings changes must appear in every root; facet counts stay per-source. Detach extras with `leaf.detach()` when done.

### 7.5. Workspace ownership vs native popup windows

- Do not equate Obsidian's global `activeWindow` with a workspace window: a native Settings popup can become `activeWindow` while owning no workspace leaves. Verify focused-window ownership against real leaves; a non-workspace popup must route through its owning active view/workspace window, without collapsing a genuine floating workspace window into main.
- For global target selection, reproduce the FIRST call with Settings still open, then verify cancel leaves exact leaf/stream identities unchanged, choosing changes only one target, and a single candidate is reused. A/B the old and candidate bundles in the same isolated host before declaring root cause; an original incident without sampled window identity remains unproven even if the same symptom is reproduced.
- Use the exact saved probes required by Core eval patterns for old/new comparisons; preserve their setup and restoration rather than reconstructing an allegedly equivalent reproducer from output alone.

### 8. Fixture hygiene

Create fixtures through the CLI (`create path=... content=...`) so the app indexes them. Beware: `create` on an existing path creates a suffixed duplicate ("Note 2.md") instead of overwriting — check the result line, and use `app.vault.process` for in-place rewrites. `delete` moves to trash. Never run `<cli> <subcmd> --help` as a bare command — unrecognized args execute a real default action (created "Untitled.md" in-session); read help only via the shell's own help path or docs. Clean up stray files before recording the verdict. A/B click-testing toolbar buttons drives REAL actions (a note button creates a file at vault root): snapshot `app.vault.getMarkdownFiles().length` first, trash strays via `app.vault.trash(file, false)`, and reconcile against a filesystem `find ... -name '*.md'` count — the in-memory index can lag one cycle, so trust the disk count plus `.trash` mtimes for the ledger.

### 8.5. Timing, staleness, and off-Space traps (verified 2026-09-08, card-workspace links acceptance)

- **`workspace.activeFile` (property) is null in an off-Space/hidden window** even though `activeLeaf.view.file` and `activeEditor.file` are correct. Plugins that use the `workspace.getActiveFile()` METHOD are unaffected. When probing, always use the method; never assert against the property in a background-driven session.
- **`metadataCache 'changed'` fires ~1s BEFORE `resolvedLinks` is updated** (measured add-link: changed at t, resolvedLinks at t+1008ms). Any reconcile reading resolvedLinks inside a changed handler sees the PREVIOUS graph — one-generation stale. To assert live-graph updates, poll `resolvedLinks` directly for convergence, or assert after the second metadata event. This bit a shipped feature whose plan assumed changed-time reads were current.
- **`metadataCache.resolvedLinks` does NOT rewrite backlink keys after a rename** (rename A.md→A2.md: dest maps of linkers keep pointing at A.md until each linker is re-resolved). Feature behavior that depends on backlinks after rename must re-scan or accept the stale window.
- **Svelte 5 batched re-render**: after `.click()`, DOM reads earlier than ~200ms are false negatives (button labels, aria-pressed, class flips). Sleep ≥0.3s before asserting DOM state.
- **Stale `lastFolderPath` pointing at a deleted folder makes the plugin's startup restore load NOTHING** (empty view, zero cards, no error) — pre-existing card-workspace behavior since 1.1.4. Before reload-based scenarios, reset it: `p.saveSettings({lastFolderPath: ''})` (fire-then-poll; the store exposes only load/save/debouncedWorkspaceWrite).
- **Settings in-memory shape**: boxes live under `memory.boxes` (not `cardBoxes`); mutating via `plugin.saveSettings({...})` is the supported path.

### 9. Sidebar view instances and the plugin action layer

- `app.workspace.iterateAllLeaves` does NOT enumerate sidebar leaves. To find a sidebar view instance walk `app.workspace.leftSplit.children[].children[]` (and `rightSplit` likewise) matching `l.view.getViewType()`.
- Prefer the plugin's own action layer over DOM/menu driving when it exists: view instances commonly expose `view.modules.*` (controllers/actions such as `boxActions`, `propertyActions`, `scopeController`) and TypeScript-`private` methods survive esbuild minification and remain callable by name (e.g. `view.selectFolderFromNav(path)`). Read the source first to learn the real signatures (e.g. `applyValueFilter(key, {kind:'text',value:...}, additive)`).
- Contract paths matter: two routes that look equivalent can have deliberately different semantics (observed: `exitBoxScope()` did not clear workspace filters while `selectFolderFromNav()` did — a documented parity decision, not a bug). Before filing a defect from a surprising observation, grep the plan/tests for the exact entry point the contract names.
- Distinguish app reload from full process restart in persistence evidence. For reload, run `app.commands.executeCommandById('app:reload')`, poll plugin readiness, and rebind every cached plugin/view/DOM reference. For full restart, first save the workspace and snapshot the compared fields, verify the exact isolated profile/vault, close only that process, reopen the same profile, and compare restored state. Re-observe the actual host version and loaded candidate identity after either operation, because the restarted app can load a different host version; earlier probes do not establish coverage of that version or the declared minimum.

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
