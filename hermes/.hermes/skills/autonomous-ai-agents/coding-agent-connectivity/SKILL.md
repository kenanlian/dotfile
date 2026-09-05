---
name: coding-agent-connectivity
description: "Use when a coding-agent CLI hangs or stalls mid-stream."
version: 1.0.0
metadata:
  hermes:
    tags: [Coding-Agent, OpenCode, Networking, Proxy, Troubleshooting]
    related_skills: [opencode, codex, development-orchestrator]
---

# Coding-Agent CLI Connectivity Diagnosis

Use when a coding-agent CLI (OpenCode, Codex, Cursor) appears hung mid-task: TUI dead, stream stops, repeated user restarts. The usual root cause is NOT the model provider — it is the network path between the CLI and the provider, most often a local HTTP proxy intermittently dropping long-lived SSE streams.

## Diagnostic Procedure

1. **Reconstruct the failure timeline from the agent's own log.**
   - OpenCode: `~/.local/share/opencode/log/opencode.log` (single rolling file, UTC).
   - Look for: timestamp gaps > 5 min (stalls), run-ID changes (user restarts), `Cannot connect to API: The socket connection was closed unexpectedly`, or a stream that stops mid-step with NO error line (dead-socket hang — the flaky-proxy signature).
   - Convert UTC log times to local before matching user-reported hang times.
2. **Resolve the provider's real baseURL.** OpenCode: `~/.cache/opencode/models.json` (models.dev cache), provider id → `options.baseURL`.
3. **Probe direct vs proxied — repeat each 3-5 times.** Flaky proxies fail intermittently; a single probe proves nothing. `http=000` timeouts only through the proxy while direct answers fast = proxy blackhole confirmed. See references/opencode-stream-hang.md for exact curl incantations.
4. **Identify the proxy.** `env | grep -i proxy`, `scutil --proxy` (macOS), `lsof -nP -iTCP:<port> -sTCP:LISTEN`.

## Fix: NO_PROXY Bypass

Bun-based CLIs (OpenCode) and most curl/Node tooling honor `NO_PROXY`/`no_proxy`. Export a bypass for the provider domain alongside the existing proxy exports in the user's shell rc:

```sh
export NO_PROXY="localhost,127.0.0.1,.provider-domain.com,provider-domain.com"
export no_proxy="$NO_PROXY"
```

Include both dotted and bare domain forms (matchers differ). Only NEW shells/processes inherit it — running agent sessions must be restarted.

## Verify End-to-End

Never declare fixed on curl alone — prove the full agent chain:

```sh
NO_PROXY="..." opencode run -m <provider>/<model> "Reply with exactly: PONG"
```

Fast correct reply = Bun NO_PROXY handling + auth + streaming all work on the bypassed path.

## Pitfalls

- Don't blame the provider on first error: `401`/fast responses mean the endpoint is healthy; silent timeouts mean the middlebox.
- A hang with NO error in the log is as diagnostic as an error — it means the socket died silently (proxy dropped it without a FIN).
- `Model not found: provider/model#variant` log noise = an agent config picked a variant the provider catalog doesn't list. Separate issue from hangs; flag it but don't conflate.
- GUI proxy apps (MonoProxy, ClashX, etc.) manage their own opaque rule sets; per-domain bypass at the shell-env level is more reliable than fighting their rule UI.

## References

- `references/opencode-stream-hang.md` — full worked example: opencode 1.18.25 + zhipuai-coding-plan/glm-5.3 hangs traced to a local proxy blackholing open.bigmodel.cn, with log-analysis scripts and verification transcript.
