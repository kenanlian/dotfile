# Pi web access (pi-web-access)

Depth for adding web access to Pi via `pi install npm:pi-web-access`. Facts distilled from the package README (pi.dev package page / npm) and Exa's official docs — re-verify limits and pricing before relying on them; they change.

## Keyless Exa vs `exaApiKey`

The extension's rule is "direct API if keyed, MCP if not" — setting `exaApiKey` switches transports automatically.

| | Keyless (zero-config default) | With `exaApiKey` |
|---|---|---|
| Transport | Exa hosted MCP (`mcp.exa.ai/mcp`), anonymous | Exa REST API (`api.exa.ai` `/search`, `/answer`) |
| Limits | Anonymous free tier (documented: 3 QPS, 150 calls/day) | Per-account: 10 QPS on `/search`, no daily cap |
| Billing | None; no usage dashboard | Pay-per-use (~$7/1k searches with contents); $20 signup credit + recurring monthly free credit covers personal use |
| Coverage | Basic search tools only; usage-based tools unavailable | Full API surface + usage dashboard |
| `exaBaseUrl` override | NOT applied — MCP path is fixed to the official endpoint | Applied |

Start keyless (adequate for occasional doc/issue lookups from delegated coding tasks); add a key from dashboard.exa.ai only when 429s actually bite.

## Config keys that matter (`~/.pi/web-search.json`)

- `"workflow": "none"` — mandatory for headless. Default `summary-review` opens a browser curator and stalls headless runs to timeout.
- Per-provider key fields (`exaApiKey`, `bochaApiKey`, `jinaApiKey`, `braveApiKey`, `tavilyApiKey`, `perplexityApiKey`, `geminiApiKey`, …). Values accept literals, `$ENV_VAR` references, or `!command` trusted credential sources; the corresponding env vars (e.g. `EXA_API_KEY`) take precedence over literal values.
- `provider` pins one backend (or `"all"`); `searchRouting.providers` + `fallbackOn` builds an ordered route without pinning.
- Explicit-only providers (never auto-selected, never in `all`, because each call bills or burns plan quota): parallel-mcp, duckduckgo, kimi, anysearch, xcrawl, valyu, xai, mistral, brightdata, serpbase, serper. Adding their keys never starts auto-spending — they must be named.
- Auto search order (keyed providers only participate when configured): SearXNG → Exa → OpenAI → Brave → Parallel → TinyFish → Search1API → Searchinfinity → Querit → Tavily → Firecrawl → Jina → SERPdive → Kagi → Bocha → Ollama → Perplexity → Gemini API → Gemini Web (browser cookies).

## Kenan-setup notes

- pi subprocesses inherit the gateway proxy env; Exa and most providers work through it. `ssrf.trustEnvProxy` is only for sandboxed-proxy DNS preflight issues — not needed on normal local runs.
- Bocha (博查) is China-direct (no proxy needed) — the candidate pinned default if proxy independence starts to matter.
- Extension tools and `-t` allowlists: measure on the installed version before promising either behavior — pi source and the pi-web-access README disagree across versions (one reading: extension tools are filtered by `-t`; the other: they ride outside built-in gating). The load-bearing check for a read-only delegation that must keep web tools: include them explicitly (`-t read,bash,web_search,fetch_content`) and verify with a smoke run, never by inference.
- On install, create `~/.pi/web-search.json` in the dotfile stow (`~/Secret-Projects/dotfile/pi/...`) and symlink, matching the delegate-agent.json pattern.
