# Gateway Post-Start Cleanup for Cloned Profiles

Session-verified 2026-08-31 (executor profile + Feishu bot 小龙). Context: profile created via `--clone`, Feishu creds replaced via QR registration, `executor gateway start` succeeded — then three cloned-config leftovers surfaced in logs.

## 1. Cloned platform credential conflict

Log signature:
```
ERROR gateway.platforms.base: [QQBot] QQBot app ID already in use by the 'default' profile gateway (PID ...). Stop that gateway first.
WARNING gateway.run: ✗ qqbot failed to connect
INFO gateway.run: Starting reconnection watcher for 1 failed platform(s): qqbot
```

Fix (disable the platform for this profile only):
```python
# config.yaml: platforms.qqbot.enabled = false  (NOT channels.qqbot.enabled —
# `hermes config set channels.X.enabled` targets the wrong key and changes nothing)
import yaml
p = '<profile_dir>/config.yaml'
cfg = yaml.safe_load(open(p))
cfg['platforms']['qqbot']['enabled'] = False
del cfg['platforms']['qqbot']['home_channel']   # if cloned
yaml.safe_dump(cfg, open(p, 'w'), allow_unicode=True, sort_keys=False)
```
Also blank the cloned creds in `.env` (`QQ_APP_ID=`, `QQ_CLIENT_SECRET=`) via `hermes_cli.config.save_env_value(k, '')`. Restart gateway; the reconnection watcher entry disappears.

## 2. Stale Feishu home_channel

Symptom on every gateway start:
```
WARNING gateway.run: Home-channel startup notification failed for feishu:oc_...: [230002] Bot/User can NOT be out of the chat.
```
Meaning: home_channel points at a chat the NEW bot was never in (cloned from source profile).

It is stored in two places — clear BOTH:
1. `platforms.feishu.home_channel` in config.yaml (delete the key)
2. `FEISHU_HOME_CHANNEL` / `FEISHU_HOME_CHANNEL_THREAD_ID` in `.env` (set to empty via `save_env_value`; `gateway/config.py` reads the env var first — `if feishu_home:` — so an empty env value is safe, but a non-empty stale one overrides YAML removal)

The real home channel gets set later by the user via `/sethome` in the new group, or explicitly once known.

## 3. require_mention inheritance

`--clone` copies `platforms.feishu.require_mention`. If source was `false`, the new executor bot responds to every group message and competes with the orchestrator bot for replies.

```python
cfg['platforms']['feishu']['require_mention'] = True
```
Desired end state for an orchestrator+executor pair in one group: orchestrator `require_mention: false` (conversational), executor `true` (speaks only when @-mentioned).

## Credential verification without a gateway

```bash
cd ~/.hermes/hermes-agent && HERMES_HOME=<profile_dir> ./venv/bin/python -c \
  "import sys; sys.path.insert(0,'.'); from plugins.platforms.feishu.adapter import probe_bot; \
   print(probe_bot('<app_id>','<secret>','feishu'))"
# → {'bot_name': ..., 'bot_open_id': ...} on success
```

## Verification of clean state

After each fix: `gateway restart`, wait ~10s, then check `executor logs | grep -i "warning\|error\|connected"` — success is `✓ feishu connected` + `Lark: connected to wss://msg-frontier.feishu.cn/...` with no qqbot watcher line and no `[230002]` warning.
