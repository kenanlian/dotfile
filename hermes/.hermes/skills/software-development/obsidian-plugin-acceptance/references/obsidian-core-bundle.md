# Reading the Obsidian core bundle (when docs are ambiguous)

Obsidian ships minified-but-readable JS in `/Applications/Obsidian.app/Contents/Resources/obsidian.asar`. When the public API docs don't answer a runtime question (rendering paths, config defaults, icon resolution, DOM structure), read the source — it settles arguments in minutes that guessing turns into filed-wrong-defects.

Validated 2026-09-05 against Obsidian 1.13.7 (Card Workspace t_cad8a7c6 missing-checkmark root cause).

## Extraction

```sh
mkdir -p /tmp/obs-extract && cd /tmp/obs-extract
npx --yes @electron/asar extract-file /Applications/Obsidian.app/Contents/Resources/obsidian.asar app.js   # ~4 MB, lands in cwd
npx --yes @electron/asar extract-file /Applications/Obsidian.app/Contents/Resources/obsidian.asar app.css  # ~635 KB
```

`app.asar` is the Electron shell; the app logic you want is in `obsidian.asar`. Keep commands short — huge inline `&&` chains can trip agent-shell payload limits; run extraction and inspection as separate commands.

## Inspecting minified code

Use Python (BSD `grep -o` chokes on long context windows with "maximum repetition exceeds 255"):

```python
src = open('app.js').read()
i = src.find('menu-item-icon')            # anchor on a stable literal
print(src[i-1500:i+800])                   # read the surrounding implementation
```

To find which object a key lives in, locate the `name={` assignments and brace-match their extents, then test `start <= idx <= end` for the key's index. Productive anchors: CSS class strings (`"menu-item tappable"`), settings keys (`nativeMenus`), method names (`setChecked=function`, `prototype.showAtPosition`).

## Facts settled this way (1.13.7)

**Menu has two render paths.** `showAtPosition`: DOM path (`!isDesktop || !useNativeMenu`) appends `.menu` to body; native path (`isDesktop && useNativeMenu`) builds an Electron NSMenu with ZERO DOM. `useNativeMenu` comes from `vault.getConfig('nativeMenus')`; **macOS null → default true** (`td.isMacOS&&null===e&&(e=!0)`). See `references/off-space-native-menus.md`.

**MenuItem DOM construction.** Each item creates `menu-item-icon` + `menu-item-title` divs at construction. `setIcon(name)` fills the leading icon div (`setIcon(null)` empties it, div remains); `setChecked(true)` APPENDS a separate trailing `menu-item-icon mod-checked` div — the leading slot stays empty. `removeIcon()` detaches the leading div entirely; `setNoIcon()` on the Menu adds `mod-no-icon`, which core CSS hides via `.menu.mod-no-icon .menu-item-icon:first-child { display: none; }`.

**Icon name resolution (`Sg`).** Order: `lucide-` prefix → `kg` (runtime `addIcon` registry) → `wg` (custom core SVG strings) → alias map `bg` (e.g. `checkmark→check`) → `fg` (lucide path table). Consequence: **any plugin's `addIcon("check", ...)` hijacks every `setIcon("check")` vault-wide** — check `app.plugins` bundles for `addIcon` collisions when icons render wrong. Built-in lucide keys live in `fg` (e.g. `check:[[6,"M20 6 9 17l-5-5"]]`).

**Native template drops icon.** The NSMenu item template maps only `{label, enabled, checked, type, click}` — no icon field. `titleEl.getText()` flattens DocumentFragment titles to concatenated plain text, so multi-line fragment titles become one run-on line in native mode.

## When to use this

- An API behaves differently than the docs imply (defaults, config gates, platform branches).
- A DOM assertion needs ground truth about what core renders (`app.css` rules for the classes you probe).
- An icon or checkmark renders inconsistently across platforms — trace the resolution chain before blaming the plugin.
