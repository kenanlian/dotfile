---
name: browser-automation-operations
description: Use when setting up or repairing Hermes browser automation.
version: 0.2.0
author: Hermes Agent
license: MIT
platforms: [macos, linux, windows]
metadata:
  hermes:
    tags: [browser, automation, troubleshooting, chromium, cdp, verification]
    related_skills: [hermes-agent, computer-use, dogfood]
---

# Browser Automation Operations

Set up, diagnose, repair, and behaviorally verify Hermes browser automation. This skill governs the operational boundary between web extraction, browser automation, desktop computer use, local Chromium/CDP, and cloud browser providers.

## When to Use

Use this skill when:

- `browser_exec` or browser tools cannot launch, connect, navigate, capture, or interact;
- selecting between local Chromium, an explicit CDP endpoint, and a cloud browser;
- installing or upgrading the Browser Use / browser-harness driver;
- enabling Chrome remote debugging safely;
- confirming that a repaired browser path actually works end to end.

For application QA after the browser is healthy, use `dogfood`. For native application control, use `computer-use`. For current Hermes commands and configuration, consult `hermes-agent` and the official docs first.

## Tool Selection

Choose the cheapest reliable surface:

1. **`web_search` / `web_extract`** for public information and static page content.
2. **Hermes browser automation** for dynamic pages, forms, clicks, DOM inspection, screenshots, console/network behavior, and responsive checks.
3. **`computer_use`** for browser chrome, native dialogs, permission UI observation, extensions, and non-web applications—not as the default web-page driver.
4. **Raw CDP** for protocol-level inspection or a documented escape hatch after the normal browser path is healthy.

Do not turn a simple extraction task into GUI automation. Do not turn a web-only interaction into desktop coordinate clicking when a semantic browser route is available.

## Diagnosis Sequence

Diagnose before changing configuration:

1. Load the current official Browser Automation documentation.
2. Inspect `hermes config get browser` and identify the selected backend/provider.
3. Check whether a documented local Chromium-family browser is installed. Automatic local discovery is documented for Chrome, Brave, Chromium, and Edge; other Chromium derivatives may require an explicit CDP endpoint.
4. Check the active browser driver command and version.
5. Run the driver's doctor command and distinguish:
   - missing browser or backend;
   - driver/launcher migration;
   - daemon not yet started;
   - remote-debugging consent not granted;
   - cloud authentication/provider selection;
   - browser started but no active connection.
6. If native desktop control is implicated, run `hermes computer-use doctor` separately. A healthy desktop driver does not prove the browser backend is healthy, and vice versa.

Treat a stopped daemon before first use as a state to verify through a real browser call, not automatically as a defect.

## Repair Strategy

Prefer the smallest supported repair:

### Local isolated browsing

- Install a browser explicitly supported by Hermes local discovery.
- Keep the browser backend on Browser Use/browser-harness unless there is a reason to select another provider.
- Upgrade the driver using its own supported updater or package migration instructions.
- Reload the driver daemon after upgrading.
- Restart the Hermes session only when configuration or tool registration is cached at session launch.

### Cloud browsing

Use a configured cloud provider when no local browser is desired, anti-bot infrastructure is required, or the agent runs away from the user's desktop. Select providers through `hermes tools`; credentials alone do not necessarily select the provider.

### Explicit CDP

Use an explicit CDP endpoint when attaching to a deliberately launched browser instance. Always use a dedicated non-default `--user-data-dir` for remote debugging on modern Chromium. Avoid exposing a personal default profile unless the user explicitly authorizes it.

## Authenticated Browser State and Dedicated Profiles

Choose the narrowest authentication model that satisfies the task:

1. Keep clean isolated browsing for public or unauthenticated work.
2. Prefer a dedicated supported Chromium profile for repeat authenticated work when the user's daily browser should remain private.
3. Enable real-profile snapshotting only when the user explicitly wants an existing browser profile copied.
4. Attach to a live existing profile only when the task truly needs its current tabs or session and the required grant is present.

A newly installed supported browser can itself be the dedicated automation environment: rename its fresh default profile, keep browser sync/import disabled, and let the user sign into selected sites manually. Renaming is an organizational label; the isolation comes from not mixing personal browsing, sync data, or unrelated accounts into that browser/profile.

Do not enable `browser.use_real_profile` merely because authenticated browsing is desired. A persistent dedicated browser profile may already provide the needed cookies without copying the user's daily profile. Passwords, passkeys, permission dialogs, payment, and MFA remain human-only boundaries.

See `references/dedicated-authenticated-profile.md` for the decision tree, safe setup, Chrome internal-settings workflow, and persistence verification.

## macOS Remote-Debugging Consent

Chrome may require a human to enable remote debugging at `chrome://inspect/#remote-debugging` and may show another per-connection **Allow** dialog.

- Never click these permission controls for the user.
- Ask the user to tick **Allow remote debugging for this browser instance** and approve the dialog.
- If the driver still reports consent missing, take a read-only capture of Chrome and verify the checkbox visually before retrying.
- Do not repeatedly reconnect while the checkbox is visibly off.
- After the page reports a server such as `127.0.0.1:9222`, retry the browser connection and let the user approve any connection-specific prompt.

## End-to-End Acceptance

A successful install, version check, doctor report, or daemon start is not acceptance. Verify the repaired path in a real browser session:

1. Navigate to a known public test page.
2. Read back URL, title, and a stable DOM element such as `h1`.
3. Capture a screenshot and inspect it.
4. Locate a real link or control through the semantic/AX/CDP tree.
5. Click it through the browser driver.
6. Wait for navigation or state change.
7. Read back the new URL, title, and stable page content.
8. Capture the result.
9. Make a second call using the same named session to prove the daemon/session survives beyond one invocation.

Only then report the browser path as working.

## Safety and Configuration

- Never click password, permission, payment, or 2FA UI.
- Use isolated browser profiles by default.
- Real-profile browsing requires explicit user consent because it exposes cookies, storage, and signed-in pages.
- Use `hermes config set ...`; do not hand-edit `config.yaml` for the user.
- Preserve a rollback path when replacing a launcher or migrating packages.
- Do not describe a transient setup failure as a durable tool limitation.

## Pitfalls

- **Conflating desktop and browser health:** `computer_use` can be healthy while browser automation lacks a backend.
- **Assuming any Chromium derivative is auto-discovered:** prefer the documented browser set or configure CDP explicitly.
- **Treating doctor output as proof:** doctor is triage; interaction is acceptance.
- **Retrying consent blindly:** verify the checkbox visually and wait for the user.
- **Using raw CDP as the permanent default:** keep it as an escape hatch unless explicit CDP is the chosen architecture.
- **Deleting the old launcher during migration:** preserve it until the new path passes the full acceptance sequence.

## Reference

- See `references/local-chromium-bootstrap.md` for the validated local-Chromium repair and verification recipe, including the conditional legacy launcher migration.
- See `references/dedicated-authenticated-profile.md` for a least-privilege persistent-login browser profile and its verified Chrome rename procedure.
