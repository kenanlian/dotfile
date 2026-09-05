# Executor Profile Bootstrap (verified 2026-08-31, hermes-agent on macOS)

Goal: a new profile that inherits tools/config/credentials from an existing
profile but starts with EMPTY skills and EMPTY memory.

## Verified procedure

```bash
# 1. Create (clone brings config.yaml + .env + SOUL.md + skills + memories;
#    --no-skills is mutually exclusive with --clone — do not combine)
hermes profile create executor --clone \
  --description "执行代理：吃掉重上下文执行工作，只汇报结论。"

# 2. Strip skills and prevent `hermes update` from re-seeding bundled skills
P=~/.hermes/profiles/executor
rm -rf $P/skills
touch $P/.no-bundled-skills     # marker checked by seed_profile_skills()

# 3. Empty the cloned memories (files must exist, content emptied)
> $P/memories/MEMORY.md
> $P/memories/USER.md

# 4. Sanity checks
executor doctor                    # expect: All checks passed
executor profile list              # new profile shows with cloned model
```

## Source-code-verified behavior (hermes_cli/profiles.py)

- `NO_BUNDLED_SKILLS_MARKER = ".no-bundled-skills"` at the profile root.
  When present, fresh-create seeding, `hermes update` all-profile sync, and
  the dashboard skip bundled-skill seeding for that profile. Manual skill
  installs (`hermes skills install`, dropping SKILL.md) still work.
- Even with the marker, `seed_profile_skills()` runs the sync and
  `sync_skills()` seeds the ESSENTIAL skills — the `hermes-agent`
  self-knowledge skill lands in `skills/autonomous-ai-agents/hermes-agent/`.
  This reappears after every session start; it is by design, not a leak.
- `--clone` excludes per-profile history (state.db, sessions/, backups,
  state-snapshots/, checkpoints/) — sessions do NOT carry over.

## Credential divergence

The cloned `.env` contains the source profile's messaging credentials
(e.g. FEISHU_APP_ID / FEISHU_APP_SECRET). For any platform where the new
profile must run its own gateway/bot, replace them with a NEW app's
credentials BEFORE starting the new gateway. Two gateways presenting the
same Feishu app credentials compete for the WebSocket long connection.

## Verifying empty state end-to-end

Run a one-shot chat, then read the answer from the transcript:

```bash
executor chat -q "你的 skills 目录里有多少个 skill？记忆文件内容是什么？"
executor sessions list --limit 1          # grab the session id
executor sessions export --session-id <id> --format jsonl - | python3 -c '
import json,sys
rec=json.loads(sys.stdin.read())
texts=[m.get("content") for m in rec.get("messages",[])
       if m.get("role")=="assistant" and isinstance(m.get("content"),str)]
texts=[t for t in texts if t.strip()]
print(texts[-1] if texts else "NO ASSISTANT TEXT")'
```

Notes: the export's first JSON line is a session header (messages live under
the `messages` key); assistant content entries can be empty strings for
tool-call turns — take the last NON-empty one. Expected answer: memory empty,
1 skill (hermes-agent, by design).

## Ops tips

- Wrapper script: `--no-alias` skips it; default creates `~/.local/bin/<name>`
  so `executor <cmd>` addresses the profile directly.
- `hermes profile describe <name>` can set/replace the description later
  (it feeds the kanban decomposer's role routing).
