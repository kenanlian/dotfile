# OpenCode Go model-access probe — 2026-08-29

This is a dated provider snapshot, not a permanent allow/deny list. Re-fetch the live catalog and re-probe before changing a production route.

## Incident that motivated the probe

Hermes context compression was configured as:

```yaml
auxiliary:
  compression:
    provider: opencode-go
    model: deepseek-v4-pro
```

When the session crossed its 300K-token compression threshold, summary generation failed repeatedly with HTTP 403 `RegionError`: the latest model version was hosted in China and required explicit workspace opt-in. Hermes safely aborted each compaction commit and retained the original context. Because no `auxiliary.compression.fallback_chain` was configured and `compression.abort_on_summary_failure` was false, the main turn continued uncompressed and request size kept growing.

Reusable diagnosis:

1. Inspect the resolved auxiliary route with `hermes config get auxiliary.compression`.
2. Inspect compression logs for the exact provider/model and upstream status; separate the first summary failure from later oversized-request symptoms.
3. Check whether a fallback chain exists. Do not assume `provider: auto` or main-model fallback applies to an explicitly pinned auxiliary route.
4. Fetch the provider's current `/models` endpoint.
5. Probe candidate replacements through Hermes' real provider path before recommending or configuring them.

## Probe method

The provider's public model endpoint returned 33 IDs. Each was tested through the user's configured OpenCode Go credential and Hermes runtime with a bounded, minimal one-shot request:

```bash
hermes chat -Q --source tool \
  --provider opencode-go -m MODEL_ID \
  --ignore-rules -t '' \
  -q 'Reply with exactly OK.' \
  --max-turns 1 --run-budget 60
```

Access success meant exit code 0 and no provider error. `OK.` counted as access success even though it was not byte-exact instruction following. This smoke test verifies authentication, entitlement, transport selection, provider policy gates, and basic inference; it is **not** a 300K-token compression stress test.

## Results

### Live-access PASS (27)

```text
deepseek-v4-flash-vision-exp
glm-5
glm-5.1
glm-5.2
glm-5.3
glm-5.3-flash
gpt-5.6-luna
grok-4.5
grok-4.6
hy3
hy4-preview
kimi-k2.5
kimi-k2.6
kimi-k2.7-code
kimi-k3
longcat-2.0
mimo-v2.5
mimo-v2.5-pro
minimax-m2.5
minimax-m2.7
minimax-m3
qwen3.5-plus
qwen3.6-plus
qwen3.7-max
qwen3.7-plus
qwen3.8-flash
qwen3.8-max
```

### Region/hosting opt-in failure

- `deepseek-v4-pro` — HTTP 403 China-hosting opt-in required.
- `deepseek-v4-flash` — same HTTP 403 and message.

`deepseek-v4-flash-vision-exp` happened to pass, but its experimental status and distinct hosting route make it a poor critical compression default.

### Listed but unavailable/unsupported upstream

- `hy3-preview` — model unavailable.
- `mimo-v2-pro` — unsupported model.
- `mimo-v2-omni` — unsupported model.

### Policy-gated

- `muse-spark-1.2-contributor` — Hermes correctly blocked unattended use because the tier permits training on prompts/completions and requires explicit user acceptance. Do not use it for background compression merely to make the probe pass.

## Compression-model selection from the passing set

For this route, the preferred primary was `glm-5.3-flash`: live access passed; official documentation advertised a 1M context window, 128K output, zero-day retention, and low pricing. Practical fallback candidates were:

1. `mimo-v2.5` — live pass, 1M-class context, low cost, zero-day retention.
2. `qwen3.8-flash` — live pass, 1M context, zero-day retention.
3. `minimax-m3` — live pass, 1M context.

Re-check current first-party privacy, pricing, context metadata, and live access before reuse. Do not copy this dated ranking blindly if models or hosting routes have changed.
