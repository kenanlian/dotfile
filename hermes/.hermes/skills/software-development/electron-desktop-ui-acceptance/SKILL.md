---
name: electron-desktop-ui-acceptance
description: Use when accepting Electron UI changes in a real renderer.
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [macos, linux, windows]
metadata:
  hermes:
    tags: [electron, cdp, desktop, ui-verification, behavior-acceptance]
    related_skills: [computer-use, development-orchestrator, dogfood, inspecting-hermes-desktop-dom]
---

# Electron Desktop UI Acceptance

Accept Electron and Chromium-rendered desktop UI changes through the real application renderer when native computer control alone cannot reliably exercise the surface. Use Chrome DevTools Protocol (CDP) as an acceptance transport, not as a substitute for product behavior or visual judgment.

## When to Use

Use this skill when all of the following are true:

- the target is an Electron app, an Electron-hosted plugin surface, or another Chromium desktop renderer;
- a real built/deployed artifact exists in a dedicated test profile, vault, or workspace;
- acceptance requires rendered geometry, computed styles, focus, hover, keyboard, IME, screenshots, or state hierarchy; and
- native background input is unavailable, off-Space, AX-unresolved, or otherwise cannot be verified.

Examples include Obsidian plugins, Electron editors, desktop productivity apps, and test instances of Chromium-based tools.

Do not use this for static mockup review, source-only code review, browser-only web apps already supported by normal browser automation, or production accounts where launching a debug port would expose sensitive state.

## Acceptance Boundary

CDP is valid here because it operates the actual renderer and can send Chromium `Input.*` events. Keep the trust boundary explicit:

- Prefer `Input.dispatchMouseEvent`, `Input.insertText`, `Input.dispatchKeyEvent`, and `Input.imeSetComposition` for interaction.
- Use `Runtime.evaluate` primarily for observation: selectors, geometry, active element, ARIA state, classes, and computed styles.
- Do not silently replace trusted input with `element.click()`, direct `value=` assignment, or synthetic DOM events. If a direct DOM mutation is intentionally used for a scoped token-environment probe, label it as such and do not claim setting-level behavior.
- Screenshots remain necessary for visual judgment. Computed styles prove facts, not aesthetic quality.

## Prerequisites

1. Confirm the user-authorized test workspace/profile/vault.
2. Record the built artifact identity and verify the deployed artifact matches it.
3. Preserve unrelated user work and settings.
4. Obtain explicit authority before closing or restarting an existing application session.
5. Prefer an isolated app profile or dedicated test vault. Never expose a debug port for a sensitive live profile without clear authorization.

## Workflow

### 1. Establish the artifact actually under test

- Build and deploy the intended renderer artifact.
- Compare hashes or another deterministic identity between repository output and the test installation.
- Confirm that a previous renderer instance is not still holding old JavaScript or CSS.

`Cmd+R` or an app-specific force reload is optional. A complete quit and reopen is more deterministic when the user authorizes it and autosave makes it safe. Explain that reload refreshes the renderer; it is not intrinsically required if the process restarts.

### 2. Start a bounded CDP instance

If the current process already exposes an authorized local CDP port, reuse it. Otherwise, after explicit restart authority, launch the test instance with a loopback debugging port, for example:

```bash
open -a Obsidian --args --remote-debugging-port=9222
open 'obsidian://open?vault=<test-vault>'
```

For generic Electron apps, prefer a separate `--user-data-dir` and a non-default port when the app supports them. Bind only to loopback. Poll rather than probing once:

```bash
curl -sS --max-time 2 http://127.0.0.1:9222/json/list
```

Select the intended target by `type === "page"` plus a stable URL and/or title. Do not attach blindly to the first target; overlays, workers, quick-entry windows, and devtools targets may coexist.

### 3. Use a small CDP runner

Use [scripts/cdp-runner.mjs](scripts/cdp-runner.mjs) with a JSON operation spec, or an equivalent existing project client. Keep evaluated results projected to small JSON objects rather than dumping the DOM.

Useful methods:

- `Runtime.evaluate` — active element, geometry, ARIA state, classes, token values, computed style;
- `Input.dispatchMouseEvent` — trusted hover/click in renderer coordinates;
- `Input.insertText` — committed text input;
- `Input.dispatchKeyEvent` — Escape, Tab, arrows, shortcuts;
- `Input.imeSetComposition` — composition start/update before commit;
- `Page.captureScreenshot` — actual renderer evidence.

### 4. Resolve the visible instance

Electron workspaces often keep hidden component instances mounted. A selector may match both a hidden sidebar instance and a visible main instance. Always select by visibility and geometry, for example:

```js
Array.from(document.querySelectorAll('input[aria-label="Search"]'))
  .find((el) => {
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0
  })
```

Use `getBoundingClientRect()` to derive CDP input coordinates. Record the rect before and after hover/focus when layout stability matters.

### 5. Exercise behavior, not just appearance

Build decisive scenarios from the requirement:

- **Resting state:** muted background, transparent/weak border, no unintended shadow, correct density and baseline.
- **Focus:** real active element, theme-derived border/background, stable icon geometry.
- **Text and clear:** committed input filters real content; clear control appears; Escape restores state.
- **Keyboard:** Tab lands on the intended next control; arrows and focus-visible behavior remain intact.
- **IME:** use `Input.imeSetComposition` for start/update, then `Input.insertText` to commit. Observe `compositionstart`, `compositionupdate`, composing `input`, and `compositionend` rather than treating direct Unicode insertion as IME coverage.
- **Hover:** move the CDP pointer onto the actual row; confirm hover style, action disclosure, and fixed-slot icon transitions.
- **Selected/checked/active:** separate resting selection from hover/focus replacement behavior. Move pointer and keyboard focus away before concluding an indicator is missing.
- **Light/dark:** prefer the app's real theme switch. A temporary renderer class change may validate actual token adaptation, but report it as a token-environment test and restore it before completion.

### 6. Combine factual and visual evidence

For each scenario record:

```text
Scenario: <name>
Artifact: <identity>
Input route: CDP Input.* | native computer use
Expected: <observable behavior>
Observed: <behavior + computed facts>
Screenshot: <path or none>
Verdict: PASS | FAIL | BLOCKED
```

Use computed style for exact height, radius, border, opacity, visibility, color, and geometry. Use screenshots to judge visual weight, alignment, hierarchy, and whether the interface feels natural.

### 7. Restore and remove the debugging surface

Before finalizing:

1. clear temporary search/filter/selection state;
2. restore the original theme and active tab/workspace;
3. close the debug-enabled process;
4. verify the CDP port no longer accepts connections;
5. reopen the authorized test workspace normally when the user expects the app left open;
6. verify the source working tree and deployed artifact identity remain as intended;
7. do not commit until the accepted scope passes and commit authority exists.

## Pitfalls

- **Hidden duplicate instance:** the first selector match may have a zero rect. Select the visible instance explicitly.
- **Focus masquerading as hover:** clicking a row often leaves keyboard focus there, so actions remain visible after the pointer moves. Blur both pointer and focus before deciding that a selected check/count is missing.
- **Static style as behavior:** class names and CSS tokens do not prove Escape, Tab, IME, filtering, or action replacement.
- **Direct Unicode is not IME:** `Input.insertText("中文")` covers committed text only. Use composition methods and observe composition events.
- **Theme class overclaim:** directly switching `theme-light`/`theme-dark` proves token response, not persistence or settings UI behavior.
- **Debug port left behind:** a successful acceptance run is incomplete until the temporary port is closed.
- **Whole-DOM dumps:** they flood context and conceal the decisive state. Project small JSON summaries.
- **Wrong target:** Electron may expose page, worker, overlay, and devtools targets. Match URL/title/type.
- **Visual approval from numbers:** geometry and computed colors cannot establish that the result looks good; inspect screenshots.

## Verification Checklist

- [ ] Test artifact matches the deployed artifact.
- [ ] Real renderer, correct page target, and visible component instance were used.
- [ ] Input used CDP `Input.*` or another declared trusted route.
- [ ] Resting, hover, focus, selection, keyboard, clear, and IME scenarios were exercised when relevant.
- [ ] Light/dark claims distinguish token adaptation from persisted settings behavior.
- [ ] Screenshots support visual conclusions.
- [ ] Temporary UI state and theme were restored.
- [ ] Debug process/port were removed and the normal test app was reopened when appropriate.
- [ ] Remaining limitations are explicit; no blocked scenario is reported as PASS.

## References

- [references/obsidian-plugin-acceptance.md](references/obsidian-plugin-acceptance.md) — validated Obsidian/Card Workspace example, including hidden instances, IME, state hierarchy, and cleanup.
- [scripts/cdp-runner.mjs](scripts/cdp-runner.mjs) — generic JSON-driven CDP acceptance runner using Node's built-in WebSocket.
