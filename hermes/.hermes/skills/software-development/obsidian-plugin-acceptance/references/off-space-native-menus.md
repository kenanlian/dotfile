# Off-Space native Menu non-mount (diagnosis recipe)

Observed 2026-09-05, Card Workspace t_cad8a7c6 acceptance (Obsidian 1.9.x, macOS, window on another Space).

## Symptom

A refactor that replaced a custom Svelte popover with Obsidian's native `Menu` API showed: click reaches the button, but no `.menu` node ever appears — while the OLD build's popover opened fine in the same environment. Looks exactly like a code regression.

## Discriminator chain (run in this order — each step is cheap)

1. **Zero-error check.** Arm `window.addEventListener('error')` + `unhandledrejection` + a `console.error` override, re-click. Self-test the probe with `setTimeout(() => { throw new Error('probe-test') }, 0)` to prove the probe fires. Native Menu non-mount produces NOTHING here.
2. **Event-arrival check.** Capture-phase listener on the button (`btn.addEventListener('click', ...)` with `true`). CDP `Input.dispatchMouseEvent` (mousePressed+mouseReleased at the button rect center) delivers a real click even when the window is off-Space — count increments, Svelte-delegated handlers for OTHER buttons in the same toolbar run (e.g. note creation actually creates a file).
3. **Mount spy.** `MutationObserver` on `document.body` counting added nodes with class `menu`, plus wrap `Element.prototype.appendChild` to log `.menu` appends. Both stay at zero → `new Menu()`/`showAtPosition` never reached the DOM stage (the handler short-circuits earlier, inside Obsidian's Menu code).
4. **Cross-check Obsidian's OWN menus.** Right-click the file-explorer vault header, or a card context menu, or `document.querySelector('.menu')` after any native trigger. If Obsidian's own menus ALSO fail to mount, the plugin is exonerated — it is the environment.
5. **Off-Space signature.** `window.electronWindow?.isFocused?.() === false` while `document.hasFocus() === true` and `document.visibilityState === 'visible'`. rAF still runs. This combination = window on another macOS Space / occluded, CDP sees a focused renderer.
6. **A/B previous build.** Swap the prior build (or `git stash` the plugin dir), `app:reload`, re-run the identical click path. A DOM popover opening where the native Menu doesn't is the final confirmation the code path changed, not broke.

## CRITICAL companion fact (found 2026-09-05, Obsidian 1.13.7): native-menus mode never mounts DOM even when focused

On **macOS**, `Menu.useNativeMenu` defaults to TRUE when the vault config `nativeMenus` is unset (`td.isMacOS&&null===e&&(e=!0)` in app.js). In that mode `showAtPosition` takes the Electron native NSMenu branch: **zero DOM nodes, ever** — a frontmost, fully focused window included. So "no `.menu` node in CDP" does NOT imply the menu failed to open; it may be rendering as a real NSMenu. Consequences:

- DOM probes cannot verify menu content on macOS default config. To force the DOM path for testing: `app.vault.setConfig('nativeMenus', false)` (persists to app.json — restore after), or probe on a vault where it's off. Windows/Linux always use the DOM path.
- **The DOM path is ALSO the off-Space escape hatch (verified 2026-09-05, Obsidian 1.13.7).** With `nativeMenus: false`, a synthetic click on the trigger mounts the full `.menu` DOM even while the window is on another Space (`isFocused: false`, `visibility: hidden`): items, `mod-checked` marks, section-title decoration all readable via CDP. This decouples the two previously conflated factors — off-Space only blocks the NATIVE path (NSMenu needs a truly frontmost window); the DOM path never depended on window focus. So menu LOGIC (item list, selection marks, disabled states, decorations) is now automatable cross-Space; only the final native-path PIXELS (real NSMenu appearance, left-positioned system checkmark) stay on the user's manual list. Wrap-up: toggle config → click → assert → restore config to null.
- In native mode the item template maps ONLY `{label, enabled, checked, type, click}` — **`MenuItem.setIcon()` is silently dropped**. A checked state must use `setChecked(bool)`, which works on both paths, but the check lands in DIFFERENT places: DOM path appends a trailing `.menu-item-icon.mod-checked` div at the END of the item (verified: left icon slot stays empty), while the native NSMenu checkbox renders on the LEFT per macOS convention. `setIcon("check")` renders on the DOM path only (left icon slot) and looks like a missing-checkmark bug on macOS (Card Workspace t_cad8a7c6 defect, 2026-09-05).
- `titleEl.getText()` flattens DocumentFragment titles to concatenated plain text in native mode — two-line hint rows become one run-on line. Acceptable or redesign per menu.
- Recovery attempts below refer to getting the WINDOW frontmost, which is still required for the native menu to actually appear on screen (off-Space native menus still do not open).

## What did NOT recover menu mounting (do not re-burn time on these)

- `Page.bringToFront`, `Emulation.setFocusEmulationEnabled({enabled:true})`
- `open -a Obsidian`, `electronWindow.focus()` (cross-Space focus is refused by macOS)
- AppleScript `activate` / System Events queries — these hung entirely (180 s timeout) in this state
- cua `focus_app` background and `delivery_mode='foreground'` CGEvent click — event posts but the Space does not switch; cua also refuses background input to off-Space windows (`off_space_or_ax_unresolved`)
- Opening a popout leaf (`app.workspace.getLeaf('popout').setViewState({type, active: true})` via eval) brought the window frontmost ONCE in a session and let native-menu DOM/AX probing proceed — but a second attempt later in the same session failed. Non-deterministic: try it once, verify `electronWindow.isFocused()` after, never depend on it.

## Why popovers still work

Svelte/popover layers mount purely via DOM appends inside the view; Obsidian's native `Menu.showAtPosition` path defers mount behind window-interaction state and simply no-ops. So "old build opens, new build doesn't" is NOT a regression signal when the change was popover → native Menu.

## Correct handling

- Verify everything that does NOT need the menu surface through eval: build identity, item construction logic (jsdom tests), settings changes from the menu's callback layer.
- Batch the visual/interaction check for the user: ask them to bring the Obsidian window to the front, then re-run the click — the menu mounts normally and the remaining scenarios take seconds.
- Do not file a defect, do not request code rework, until step 4 above exonerates/acquits the environment.
