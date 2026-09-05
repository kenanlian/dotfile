# Dedicated Authenticated Browser Profile

Use this reference when browser automation needs durable website login state but should not inherit the user's whole daily browsing environment.

## Choose the Authentication Model

| Need | Preferred model |
|---|---|
| Public pages, docs, visual QA | Clean isolated browser; no login state |
| Repeated authenticated work on selected sites | Dedicated supported Chromium profile |
| Existing daily-browser cookies must be copied | Hermes real-profile snapshot, with explicit consent |
| Exact live tabs/session must be controlled | Existing-profile attachment with its explicit grant |

A dedicated profile is usually the best least-privilege middle ground. It preserves selected site cookies while excluding unrelated tabs, history, saved passwords, and accounts.

## Safe Setup

If a supported browser was freshly installed for automation and the user normally browses elsewhere, its fresh default profile can become the dedicated profile; creating another profile is unnecessary.

1. Rename the fresh profile to a recognizable label such as `Hermes`.
2. Do not enable browser Sync.
3. Do not import bookmarks, passwords, history, payment data, or extensions from the daily browser.
4. Let the user sign into only the sites needed for automation.
5. The user handles passwords, passkeys, CAPTCHAs, MFA, permission prompts, and payment UI.
6. Keep personal and high-sensitivity browsing out of this profile.
7. Keep `browser.use_real_profile` off unless the task specifically requires copying another browser profile.

Profile renaming is not a security boundary by itself. The boundary is the separate browser/profile, limited accounts, and absence of sync/imported personal data.

## Renaming Through Chrome Settings

Chrome's native AX tree can be sparse while its internal settings pages remain fully available through CDP.

1. Navigate the connected browser to:

   ```text
   chrome://settings/manageProfile
   ```

2. Do not rely on `document.body.innerText`; Chrome Settings uses nested Shadow DOM and body text may appear empty.
3. Use `Accessibility.getFullAXTree` and locate the profile-name `textbox`. Record its `backendDOMNodeId` and current value.
4. Resolve the node, focus it, and call the input element's `select()` before inserting the new name.
5. Use `Input.insertText` for the replacement, then send `Tab` to blur and commit.
6. Read the AX tree again and verify the textbox value exactly matches the requested name.

### Reliable replacement pattern

```python
obj = cdp('DOM.resolveNode', backendNodeId=backend)['object']['objectId']
cdp(
    'Runtime.callFunctionOn',
    objectId=obj,
    functionDeclaration='function(){ this.focus(); this.select(); return this.value; }',
    returnByValue=True,
)
cdp('Input.insertText', text='Hermes')
cdp('Input.dispatchKeyEvent', type='keyDown', key='Tab', code='Tab', windowsVirtualKeyCode=9)
cdp('Input.dispatchKeyEvent', type='keyUp', key='Tab', code='Tab', windowsVirtualKeyCode=9)
```

Pitfall: synthesizing Cmd/Ctrl+A through generic key events may fail to select the existing value, causing the new name to append. Always read back the field; if it appended, correct it with the element's own `select()` rather than assuming success.

## Persistence Verification

UI readback proves the visible field changed, but profile metadata should also be verified before claiming completion.

On macOS, Chrome stores profile metadata in:

```text
~/Library/Application Support/Google/Chrome/Local State
```

Parse the JSON and check the target entry under:

```text
profile.info_cache.<profile-directory>.name
```

Also confirm `is_using_default_name` is false when that field is present. On other platforms, use Chrome's platform-appropriate user-data root but verify the same `profile.info_cache` structure.

## Login and Revocation Workflow

For a new authenticated site:

1. The agent opens the login page in the dedicated profile.
2. The user completes credentials and MFA manually.
3. The agent verifies a harmless authenticated landing page.
4. Future tasks reuse that profile's cookies.

To revoke one site's access, log out and clear that site's cookies. To reset the whole environment, delete the dedicated profile through Chrome's profile manager. Do not delete or modify the user's daily browser profile.

## Operational Cautions

- A browser-level CDP connection may enumerate tabs from every profile open in that browser process. Keep unrelated personal profiles/windows closed while the automation browser is connected.
- Login state improves completion of account-scoped workflows; it provides no meaningful benefit for public research.
- Never reinterpret an authenticated session as permission for destructive account actions outside the user's request.
