# delegate-agent router config — verified detail (2026-09-05)

Repo: `~/Secret-Projects/pi-delegate-agent` (symlinked at `~/.pi/agent/extensions/delegate-agent`). Config: `~/.pi/agent/delegate-agent.json` → stow target `~/Secret-Projects/dotfile/pi/.pi/agent/delegate-agent.json`; edits are dotfile commits (tracked alongside the `skills` symlink per that repo's AGENTS.md).

## Who knows the backend

- The parent LLM never reads the config. It calls `delegate_agent` with `agent` (explorer|junior|senior|expert|reviewer) + `prompt` only; the tool description states backend/model come from the json and rejects those params if passed.
- Routing resolves inside the extension at call time: `router.ts` `loadConfig()` does a synchronous `readFileSync` **on every tool invocation** (`index.ts` re-reads per dispatch; `limitsForResume()` and `agentFileForTier()` too). Edits apply to the next delegation; no Pi restart.

## Resolution chain (no overlay)

```
process.env.DELEGATE_AGENT_CONFIG  →  ~/.pi/agent/delegate-agent.json
```

- Whole-file replacement, not a merge. No `delegate-agent.local.json` overlay exists (checked 2026-09-05 when Kenan asked; options presented — keep editing dotfile / shell-export a full replacement config / extend the extension with a local deep-merge overlay following the dotfile `*.local` convention — none built as of that date).
- A shell-level `DELEGATE_AGENT_CONFIG` export only takes effect in the shell that **launches** Pi; the extension process env is fixed at pi start.
- Env-var dual use is safe: nested children get a restricted config injected via `withChildEnv` (`/usr/bin/env DELEGATE_AGENT_CONFIG=<tmpfile> pi …`); non-nested children run `--no-extensions` and never read it. A shell-level export does not fight the nesting gate.

## Editing rules (router blocks otherwise)

- `backend` ∈ {`native`, `cursor`} (BACKENDS set in `router.ts`).
- `native` route requires non-empty `agent_file` (resolved by agent discovery against `pi-delegate-agent/agents/<name>.md`: explorer/junior/senior/expert/reviewer) plus `model`.
- `cursor` route requires only `model`.
- **cursor→native switch trap**: keep the tier key but add `agent_file`, e.g. expert `{backend:"cursor", model:"claude-opus-5-thinking-high"}` → `{backend:"native", agent_file:"expert", model:"zai-coding-cn/glm-5.3"}` (done 2026-09-05 at Kenan's request; all five tiers native after that — read the file for the current mapping, never trust prose).
- `nesting.allow` defaults to `["reviewer"]` when the key is absent.

## Validation recipe (real code, not eyeball)

```bash
node --experimental-strip-types -e 'import("/Users/kenan/Secret-Projects/pi-delegate-agent/router.ts").then(m => { const c = m.loadConfig(); for (const t of ["explorer","junior","senior","expert","reviewer"]) console.log(t, "=>", JSON.stringify(m.resolveNewDelegation(t, c))); })'
```

All five tiers must print a resolved route; a `BlockedError` means the config is semantically wrong (e.g. missing `agent_file`) even when the JSON parses fine.
