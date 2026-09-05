# Pi delegation transport — verified detail (spike 2026-09-04)

Evidence: `~/Secret-Projects/development-artifacts/agent_skills/delegations/pi-feasibility-spike/evidence/`

## Subagent example inventory (pi repo main, ~1200 lines)

Source: `packages/coding-agent/examples/extensions/subagent/` in `earendil-works/pi`.
Sparse-fetch recipe:

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/earendil-works/pi.git pi-repo
cd pi-repo && git sparse-checkout set packages/coding-agent/examples/extensions/subagent
```

Install (verified working on 0.84.4):

```bash
mkdir -p ~/.pi/agent/extensions/subagent ~/.pi/agent/agents
ln -sf "$PWD/.../subagent/index.ts"  ~/.pi/agent/extensions/subagent/index.ts
ln -sf "$PWD/.../subagent/agents.ts" ~/.pi/agent/extensions/subagent/agents.ts
# agent definitions as ~/.pi/agent/agents/<name>.md
```

### Borrow vs drop (for a relay-style fork)

| Component | Lines (approx) | Verdict |
|---|---|---|
| spawn core: subprocess, `--mode json` stream parse, abort propagation, 50KB/task output cap | ~250 | BORROW |
| `agents.ts` frontmatter discovery (string or array `tools:` both accepted) | ~157 | BORROW, simplify to single user dir |
| TUI rendering (renderCall/renderResult, token/cost formatting) | ~350 | DROP headless |
| chain mode (`{previous}` placeholder) + workflow prompts | ~100 + 3 files | DROP (workflow philosophy, invites mode mis-picks) |
| project-scope agents + `ctx.ui.confirm` gate | ~80 | DROP (config-owned trust model instead) |
| `--no-session` hardcoded | — | SWAP to `--session-id` |

Example tool modes: single `{agent, task}`, parallel `{tasks: [...]}` (max 8, 4 concurrent), chain `{chain: [...]}`. Per-task optional `cwd`. Security default: user-level agents only; `agentScope: "both"|"project"` + `confirmProjectAgents` for repo agents.

## Verified CLI behaviors

- `pi -p --mode json --session-id pi-spike-delegate-001 "…"`: stream head `{"type":"session","version":3,"id":"pi-spike-delegate-001","cwd":"…"}`; continuation call answered from prior context in 1.2s; event type histogram of a healthy run: session 1, agent_start 1, turn_start 1, message_start 2, message_end 2, message_update ~4, turn_end 1, agent_end 1, agent_settled 1.
- `-t read`: model asked to create a file reported having no write capability; no file created. Hard gate confirmed.
- Provider smokes (all ~2s except pro ~10s): glm-5.3 via proxy env OK; glm-5.3 with `env -u HTTPS_PROXY -u HTTP_PROXY` OK; `opencode-go/deepseek-v4-pro` OK; `opencode-go/deepseek-v4-flash` OK.
- One observed run: 2× `auto_retry_start` (`"Connection error."`, delays 2s/4s, maxAttempts 3) then success, total 79s. Monitors: count retries, alarm only on exhaustion.

## Relay-monitor adaptation notes

- resume.yaml anchor: parse first `session` event for id+cwd (equivalent to grepping opencode events.jsonl system-init line).
- Terminal detection: process exit + `agent_settled`; result text from last `message_end` assistant content or `agent_end.messages`.
- Progress heartbeat: any `message_update`/`turn_*` activity.
