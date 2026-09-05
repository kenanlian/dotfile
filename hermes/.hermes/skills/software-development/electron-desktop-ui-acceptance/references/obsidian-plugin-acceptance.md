# Obsidian Plugin Acceptance via CDP

This reference records a validated workflow for accepting a built Obsidian plugin inside a dedicated vault when native macOS input could observe the window but could not reliably focus or drive it across Spaces.

## Scope

- Host: Obsidian 1.13.7 on macOS
- Renderer URL: `app://obsidian.md/index.html`
- Test surface: a dedicated vault, not the user's daily vault
- Artifact: plugin `main.js`, `styles.css`, and `manifest.json`
- Goal: verify a navigation pane's search, hover, selected states, Light/Dark token adaptation, keyboard flow, and IME behavior

## Deterministic artifact load

1. Hash repository build outputs.
2. Copy only the intended artifact files into the test vault's `.obsidian/plugins/<plugin-id>/` directory.
3. Hash the deployed copies and require equality.
4. Fully quit Obsidian and reopen the test vault when the user authorizes it.

A full process restart made the new embedded search icon visibly appear. `Cmd+R` would also reload the renderer, but was not required after a complete restart.

## Temporary CDP launch

After the user authorized closing all Obsidian windows:

```bash
open -a Obsidian --args --remote-debugging-port=9222
open 'obsidian://open?vault=Card-Workspace-Hermes-Test'
```

Poll `http://127.0.0.1:9222/json/list`, then choose the `type: page` target whose URL is `app://obsidian.md/index.html` and whose title names the test vault.

## Hidden duplicate instances

The workspace kept two plugin instances mounted:

- a hidden single-column sidebar instance whose search input had a `0×0` rect;
- the visible dual-column instance whose search input had a non-zero rect.

A plain `querySelector` selected the hidden input and would have invalidated the test. Every input and row lookup filtered on `getBoundingClientRect().width > 0` and height > 0.

## Search and keyboard evidence

Using CDP mouse and keyboard input on the visible search field:

- focus made `document.activeElement` equal the input;
- `Input.insertText("Beacon")` updated the value and filtered real navigation rows;
- the clear button appeared;
- Escape restored the full row set and kept search focus;
- Tab moved from search to the current-range tree item.

Computed style and screenshots were both captured. Geometry established fixed icon placement; screenshots established visual weight and toolbar alignment.

## IME evidence

An event observer was attached only for evidence. CDP then sent:

1. `Input.imeSetComposition` with `导`;
2. `Input.imeSetComposition` with `导航`;
3. `Input.insertText` with `导航` to commit.

Observed sequence:

```text
compositionstart
compositionupdate("导")
input(value="导", isComposing=true)
compositionupdate("导航")
input(value="导航", isComposing=true)
compositionend("导航")
```

The final value was `导航`, filtering updated, and Escape cleared it while preserving focus. This is stronger evidence than direct Unicode insertion alone.

## Hover and fixed-slot evidence

For an expandable folder row, the glyph and chevron had the same renderer rect before and during hover. Hover changed only opacity:

- resting: glyph 1, chevron 0;
- hover: glyph 0, chevron 1.

The count became hidden and one row action became visible. For a section header, hover kept the row background transparent and revealed actions while changing muted text/icon to normal.

## Selected-state evidence

Three states were differentiated:

- current range: active background plus a light left marker;
- checked tag: active background, no border/shadow, right check at rest;
- active favorite file: accent text/icon only, no right border or strong background.

A critical test detail: clicking a checked tag left keyboard focus on the row, so hover/focus actions replaced the check. Moving only the pointer was insufficient. After clicking a neutral main-content location, focus moved to `BODY`, actions hid, and the check became visible. Always separate pointer hover from keyboard focus before diagnosing a missing indicator.

## Active-file reproduction

The main Card Workspace tab itself was active, so the favorite initially had no active-file state. To reproduce the state while retaining a plugin surface:

1. activate an existing note tab (`Active Card`);
2. expand the Card Workspace view that remained in the Obsidian sidebar;
3. inspect the favorite there.

The active favorite used accent text/icon while the current-range row retained stronger background treatment.

## Light/Dark token probe

The renderer body was temporarily moved from `theme-light` to `theme-dark` solely to test token adaptation. This did not test Obsidian's settings UI or theme persistence and was reported as a token-environment probe.

In dark tokens:

- the resting search surface remained muted with a transparent border;
- focus used the theme's darker surface and border, with no shadow;
- current and checked backgrounds adapted;
- the selected check remained visible.

The original `theme-light` class was restored before completion.

## Cleanup

Before closing the debug process:

- search value was empty;
- checked-filter count was zero;
- Light theme class was restored;
- the main Card Workspace tab and visible navigation pane were restored.

Then Obsidian was quit, the debugging port was verified closed, and the test vault was reopened normally. The repository remained uncommitted pending user authority.
