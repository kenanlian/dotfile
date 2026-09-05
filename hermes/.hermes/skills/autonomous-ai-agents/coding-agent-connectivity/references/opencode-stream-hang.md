# Worked Example: OpenCode Stream Hangs via Flaky Local Proxy

Session 2026-09-03, macOS: user reported repeated OpenCode 挂死 during Card Workspace development. Root cause: local proxy app (MonoProxy, 127.0.0.1:8118) intermittently blackholed `open.bigmodel.cn` (~1 in 3 connections timed out). Provider itself was healthy.

## Timeline reconstruction

Log: `~/.local/share/opencode/log/opencode.log` (UTC; CST = +8).

Gap analysis script (prints stalls > 5 min):

```sh
awk '{print $1}' ~/.local/share/opencode/log/opencode.log | grep "<date>" | python3 -c "
import sys, datetime
prev=None
for line in sys.stdin:
    t=line.strip().replace('timestamp=','')
    dt=datetime.datetime.fromisoformat(t.replace('Z','+00:00'))
    if prev and (dt-prev).total_seconds()>300:
        print('GAP %.1f min: %s -> %s'%((dt-prev).total_seconds()/60, prev.strftime('%H:%M:%S'), dt.strftime('%H:%M:%S')))
    prev=dt
"
```

Found 5 gaps in one morning; each gap ended with a NEW `run=<id>` (user restarted). Two gaps contained:

```
level=ERROR message="stream error" providerID=zhipuai-coding-plan modelID=glm-5.3
  error.error="AI_APICallError: Cannot connect to API: The socket connection was closed unexpectedly..."
```

The first hang had NO error — stream stopped mid-step-62, log silent, process killed 6 min later. Dead-socket hang.

## Provider baseURL resolution

```python
import json
d = json.load(open('~/.cache/opencode/models.json'))  # expanduser
d['zhipuai-coding-plan']['options']['baseURL']
# -> https://open.bigmodel.cn/api/coding/paas/v4
```

## Proxy-vs-direct probes (the decisive test)

```sh
# Through proxy (repeat!):
for i in 1 2 3; do curl -s -o /dev/null -w "try$i http=%{http_code} total=%{time_total}s\n" \
  -m 20 -x http://127.0.0.1:8118 https://open.bigmodel.cn/api/coding/paas/v4/models; done
# Result: 401/0.1s, 000/20.1s (TIMEOUT), 401/0.1s  <- intermittent blackhole

# Direct:
curl -s -o /dev/null -w "http=%{http_code} total=%{time_total}s\n" -m 20 \
  --noproxy '*' https://open.bigmodel.cn/api/coding/paas/v4/models
# Result: 401 in 0.3-1.7s every time
```

Proxy process identified via `lsof -nP -iTCP:8118 -sTCP:LISTEN` → MonoProxyMac. Shell env (`HTTP(S)_PROXY=127.0.0.1:8118`) came from the user's `.zshrc` (stow-linked to their dotfile repo).

## Fix applied

Added to the proxy block in `.zshrc`:

```sh
export NO_PROXY="localhost,127.0.0.1,.bigmodel.cn,bigmodel.cn,.z.ai,z.ai"
export no_proxy="$NO_PROXY"
```

## Verification transcript

- curl with NO_PROXY: 5/5 fast 401 (bypass active).
- Full agent chain:
  ```sh
  cd /tmp && NO_PROXY="..." no_proxy="..." opencode run -m zhipuai-coding-plan/glm-5.3 "Reply with exactly: PONG"
  # > build · glm-5.3
  # PONG
  ```
- `zsh -n` syntax check passed; dotfile repo change left uncommitted for user review.

## Adjacent finding (separate issue)

Log noise: `share subscriber failed ... ProviderModelNotFoundError: Model not found: opencode-go/deepseek-v4-flash#high` — an agent config combined a model with a variant the provider catalog doesn't list. Harmless to the hang, flagged to user separately.
