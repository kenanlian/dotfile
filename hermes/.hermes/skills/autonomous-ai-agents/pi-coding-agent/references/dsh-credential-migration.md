# Migrating Pi provider credentials to DeepSeek Harness (dsh)

Applies when a task installs, configures, or re-authenticates DeepSeek Harness (`dsh`, npm `@deepseek-ai/dsh`), or moves Pi credentials into it. Install/upgrade: `npm install -g @deepseek-ai/dsh` (Node ≥22.19 required, `npx @deepseek-ai/dsh web` works without global install). Kenan's machine: dsh installed globally (`~/.local/bin/dsh`), web profile at `http://127.0.0.1:3080` — the UI requires the `?token=…` URL printed at startup; every other route answers 401.

## Why migration works at all

dsh's multi-provider LLM adapter (`@deepseek-ai/dsh-llm-pi-ai`) embeds the same `@earendil-works/pi-ai` library Pi uses. Provider ids and the model catalog are identical (`zai-coding-cn`, `opencode-go`, `kimi-coding`, `openai-codex` all builtin, `glm-5.3` included), so credentials — not provider definitions — are the only thing to move. The two harnesses never share a store: Pi reads `~/.pi/agent/auth.json`, dsh reads `~/.dsh/.credentials.yaml`. There is no live sync; migration is a copy.

## Recipe (copy, never move — Pi keeps working untouched)

1. Back up both target files before writing (`*.bak-<suffix>` siblings).
2. Translate each Pi credential (keyed by provider id) into a dsh record at `llm-pi-ai/<provider-id>` in `~/.dsh/.credentials.yaml`:
   - `{type: api_key, key}` → `kind: api-key` record with `key:` (plus `env:` if present).
   - `{type: oauth, …}` → `kind: grant` record whose `payload:` is the ENTIRE Pi credential object **including `type: oauth`** — dsh's reader returns the payload verbatim, so dropping `type` breaks OAuth detection. Preserve `access`/`refresh`/`expires`/`accountId` byte-for-byte.
   - Preserve other existing records (e.g. `client-connection/browser-session`) — the file is shared across dsh subsystems.
   - Provider id must be lowercase-hyphenated; dsh refuses other shapes (`UNSTORABLE_PROVIDER_ID`).
3. Enable routes in `~/.dsh/settings.yaml` under the `llm-pi-ai:` namespace:

   ```yaml
   llm-pi-ai:
     providers:
       zai-coding-cn: {}
   ```

   A provider present in credentials but absent from settings is dormant.
4. No restart needed: both files are watched (default `watch: true`) and hot-reload in the running instance.
5. Verify:
   - Parse the YAML back (node `yaml` package from dsh's `node_modules`) and byte-compare every key/token against `auth.json` — prefix eyeballing misses unfilled placeholders.
   - UI: Settings → 模型 lists each migrated route with 编辑/删除. Opening 编辑 shows the key-field placeholder "输入 API 密钥，或留空使用环境认证" — an empty-but-enabled field means the stored credential was detected; the UI never echoes secret values by design, so that is NOT evidence of a missing key.

## Pitfalls

- Copying an OAuth credential duplicates ONE refresh token across two stores. Rotation in either harness invalidates the other's copy — symptom is an auth failure on that single provider only. Fix: sign in again inside dsh; do not blindly re-copy.
- Hand-writing the YAML: quote scalars containing `:#{}[],&*?|<>=!%@`, leading `-`, or spaces — a bare long token with a colon silently truncates into a mapping.
- Hand-edited `settings.yaml` sections survive UI writes: the settings service merges leaf-level and never drops namespaces it doesn't own, so editing the file by hand while the UI is live is safe.

## Post-migration failure: opencode-go 400 MissingSessionID

Symptom: every chat on the `opencode-go` route fails instantly with `400 {"type":"MissingSessionID","message":"Error from provider (Console Go): Request is missing x-opencode-session…"}` while the other migrated routes work. Mechanism: the OpenCode Go gateway requires `x-opencode-session` on every request (routing + prompt-cache affinity); pi-coding-agent injects it at the APP layer (`provider-attribution.js` → `getSessionHeaders`), but dsh routes through the bare `@earendil-works/pi-ai` library, which only ever sends `x-client-request-id`/`x-session-affinity`. A correct migrated credential cannot fix this — the header is the missing piece, and OpenCode's docs list dsh as a known-problematic client for exactly this gap, so check that table before assuming local regression.

Fix (verified end-to-end: 400 gone, full chat completed): static route `headers` in `~/.dsh/settings.yaml`, hot-reloads with no restart:

```yaml
llm-pi-ai:
  providers:
    opencode-go:
      headers:
        x-opencode-session: dsh-<stable-random-id>
        x-opencode-client: dsh
```

Trade-off: one shared session id for all dsh conversations → weaker cross-request prompt-cache affinity than Pi's per-session ids; acceptable until dsh ships native session headers, then delete the block (leave a comment in the file saying so). Do NOT reach for `compat:` — `sendSessionAffinityHeaders` is not an offered compat field in dsh's schema; route `headers` is the sanctioned surface.

## Driving the web UI to verify a route end-to-end

- Auth: the `?token=` URL is printed once in the `dsh web` startup output (background-process log); curl probes of any path without the token session answer 401 — that is not a server failure.
- Model picker: bottom-bar trigger → click the 模型 cell → models grouped under per-provider headings. Pick the model under the RIGHT provider heading — the same model id can exist under several providers (GLM-5.3 exists under both `zai-coding-cn` and `opencode-go`), so selecting by display name alone can test the wrong route.
- Composer is a `contenteditable` DIV, not a textarea: focus it, `document.execCommand('insertText', …)`, then dispatch an Enter `KeyboardEvent`.
- A good turn ends with 用量/用时 stats; a failed one renders `本轮运行失败<code>` inline with the provider error body — that inline text is the fastest way to capture the exact provider error.
