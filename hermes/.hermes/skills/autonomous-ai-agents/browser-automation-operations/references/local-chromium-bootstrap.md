# Local Chromium Bootstrap and Verification

This is a condensed, validated repair recipe for a Hermes installation where browser automation has no usable local browser or the Browser Use launcher is in a legacy package layout.

## 1. Establish the boundary

Check these independently:

```bash
hermes config get browser
hermes computer-use doctor --json
```

A passing computer-use report confirms desktop AX/capture/input prerequisites only. It does not confirm a browser backend.

## 2. Discover the local browser and driver

Check for a browser documented by Hermes local discovery: Chrome, Brave, Chromium, or Edge. Inspect the actual driver resolved from `PATH` and its version:

```bash
command -v browser-use
browser-use --version
browser-use doctor --json
```

If only another Chromium derivative is installed, either install a documented browser or deliberately launch that derivative with a dedicated profile and configure an explicit CDP endpoint. Do not assume auto-discovery.

## 3. Install a supported local browser

Use the platform's normal package manager or official installer. On macOS with Homebrew, one validated option is:

```bash
brew install --cask google-chrome
```

Verify the application executable and version before proceeding.

## 4. Conditional legacy launcher migration

Apply this section only when the driver's own updater explicitly reports that the newer `browser-harness` package is missing while an older `browser-use` launcher is active.

```bash
uv tool install browser-harness
browser-harness --version
browser-harness --help
```

Compare the old and new command interfaces. If they are compatible, preserve the old package and point the Hermes-facing `browser-use` launcher at the new executable rather than deleting the old installation immediately. Then reload:

```bash
browser-use --version
browser-use --reload
```

This is a migration pattern, not a universal installation requirement. Prefer the current official installer/updater when it already manages the launcher correctly.

## 5. Handle Chrome consent safely on macOS

The first connection can open:

```text
chrome://inspect/#remote-debugging
```

The user must personally:

1. tick **Allow remote debugging for this browser instance**;
2. click **Allow** in the permission dialog;
3. approve a later per-connection Allow prompt if Chrome presents it.

The agent may take a read-only screenshot to verify whether the checkbox is actually checked. It must not click the permission control. When enabled, the page should report a local server such as `127.0.0.1:9222`.

## 6. End-to-end probe

Use a named browser session and perform all of the following:

- navigate to `https://example.com`;
- read URL, title, and `h1`;
- save a screenshot;
- locate the `Learn more` link through the accessibility/CDP tree;
- click it through the browser driver;
- wait for load;
- verify navigation to the IANA example-domain documentation;
- read the new URL, title, and `h1`;
- save a second screenshot;
- make the click/readback in a second call with the same session name.

Expected stable evidence:

```text
Initial h1: Example Domain
Link name: Learn more
Result URL: https://www.iana.org/help/example-domains
Result h1: Example Domains
```

Do not claim success after installation alone. This probe validates launch, CDP connection, DOM evaluation, screenshot capture, semantic element discovery, pointer input, navigation, and session persistence.

## 7. Operational defaults after repair

- Static public content: `web_search` / `web_extract`.
- Dynamic web interaction and visual QA: browser automation.
- Browser chrome and native app surfaces: `computer_use`.
- Protocol-specific diagnostics: raw CDP.
- Personal login state: isolated from the default workflow unless the user explicitly authorizes real-profile access.
