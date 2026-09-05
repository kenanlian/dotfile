---
name: ai-tool-provider-evaluation
description: "Use when evaluating AI tool providers, routing, and cost."
version: 1.1.0
metadata:
  hermes:
    category: research
    tags: [tool-providers, web-search, pricing, routing, api, billing]
    related_skills: [current-product-research, grounded-citations, hermes-agent]
---

# AI Tool Provider Evaluation

Evaluate an agent-facing tool, its underlying provider, and its real billing path without conflating product UI, API services, wrappers, drivers, or subscriptions.

## When to Use

Use when the user asks:

- whether a tool is “built in” to an agent framework
- which backend actually serves a search, browser, image, voice, or computer-use call
- whether a consumer subscription includes developer API usage
- how a provider charges and what one real agent action costs
- whether a configured free/keyless/paid route will charge the user
- which models a provider catalog lists versus which models the user’s current account can actually invoke
- why an auxiliary task such as compression fails on one model and which live-tested replacement is suitable
- how two tool providers differ in capabilities, limits, privacy, or cost

Pair with `current-product-research` for broad market comparisons and `grounded-citations` for citation-heavy deliverables. For Hermes-specific commands and current feature support, load `hermes-agent` and treat the live Hermes docs as authoritative.

## Core Model: Separate the Layers

Always identify these layers explicitly:

1. **Agent-visible tool interface** — e.g. `web_search`, `web_extract`, `browser_exec`, `computer_use`.
2. **Framework/toolset registration** — whether the framework natively exposes and dispatches the tool.
3. **Execution adapter or driver** — SDK, CLI, browser harness, desktop driver, MCP server, or plugin.
4. **Service backend** — Exa, Firecrawl, Tavily, OpenAI, Browserbase, a local browser, etc.
5. **Credential and tier resolution** — API key, OAuth subscription, anonymous/keyless tier, managed gateway, or fallback ring.
6. **Billing account and unit** — request, result, page, content type, token, compute unit, or fixed-effort run.

A tool can be built into the framework while relying on an external driver and a separately billed service. Say which meaning of “built in” applies.

## Workflow

### 1. Establish the user’s actual question

Usually answer both:

- **Product capability:** does the vendor/framework offer this service?
- **Current route:** is this session actually using that service?

Do not assume that the model provider also provides the active tool backend.

### 2. Verify current product facts from first-party sources

Use official documentation, pricing pages, API guides, and help-center pages. Search snippets are discovery aids, not final evidence. Extract the official page and check:

- product UI availability versus developer API availability
- supported endpoints/tools and response shape
- current pricing units and included allowances
- free credits, recurring grants, minimum spend, and auto-recharge behavior
- deprecations and migration paths

Revalidate all quoted prices at answer time; pricing changes quickly.

### 3. Inspect the live route safely

For Hermes, prefer supported commands such as:

```bash
hermes config get web
hermes tools --help
hermes portal info
```

Interpret precedence rather than reading only one field:

1. capability-specific selection
2. shared backend selection
3. never-configured credential auto-detection
4. keyless fallback/rescue, if enabled

Check credential **presence only** when needed. Never print, copy, or expose secret values. A safe probe reports `configured: yes/no`.

### 3b. Distinguish catalog presence from live account access

A model appearing in docs or `/v1/models` proves discoverability, not successful inference. For fast-moving aggregators, fetch the live model endpoint and then issue a minimal request through the user's real configured route.

For Hermes, a low-impact probe is:

```bash
hermes chat -Q --source tool \
  --provider PROVIDER -m MODEL \
  --ignore-rules -t '' \
  -q 'Reply with exactly OK.' \
  --max-turns 1 --run-budget 60
```

Probe rules:

- Use the supported Hermes path so credential pools, transport selection, provider profiles, and policy gates are exercised—not a hand-built request that bypasses them.
- Batch candidates with bounded concurrency to avoid rate limits; note that each call consumes quota and creates a tool-tagged session.
- Treat exit code 0 plus the absence of a provider error as access success. Do **not** require byte-exact `OK`; models may return `OK.` while still proving access.
- Classify failures precisely: authorization/region opt-in, listed-but-upstream-unavailable, unsupported model alias, policy/data-training gate, rate limit, or transport failure.
- Revalidate at answer time. Aggregator catalogs, aliases, hosting regions, and account entitlements change quickly.

For an auxiliary model, access is only the first gate. Also verify context window, output limit, retention/training policy, cost, latency, and suitability for the task. A compression summarizer should normally have a context window at least as large as the main model and a reliable fallback route.

### 4. Verify the wrapper’s actual request shape

Provider list prices are insufficient when the framework adds options that change billing. If necessary, inspect the current adapter/plugin source to determine:

- endpoint called
- number of results requested
- whether contents/highlights/summaries are included
- number of URLs/pages per call
- search mode or effort level
- fallback behavior

Treat wrapper defaults as version-dependent and re-check them in the installed source.

### 5. Map one agent action to billable units

Build the cost from the real request shape:

```text
cost = base request charge
     + extra-result charges
     + page/content-type charges
     + summaries or model-compute charges
     + connected-data enrichment charges
```

Use a calculator/tool for arithmetic. State assumptions and distinguish:

- list price
- free-credit consumption
- actual card charge
- anonymous/keyless usage
- managed-subscription usage

“Uses an API key” means usage is attributed to that account; it does not necessarily mean an immediate card charge if free/prepaid credits cover it.

### 6. Explain fallback billing

A configured paid backend may have one-shot keyless rescue. Say:

- the normal route
- the failure route
- whether fallback is sticky or per-call
- which account is charged in each route

Do not describe fallback availability as proof that the current successful call was free.

## Common Pitfalls

- **Tool/provider conflation:** `web_search` is a tool name; Exa may be the backend.
- **Model/tool conflation:** using an OpenAI model does not imply OpenAI handled web search.
- **Consumer/API conflation:** ChatGPT subscriptions and OpenAI API billing are separate unless an official integration explicitly says otherwise.
- **Search/browser conflation:** browser automation and desktop control can discover web content but are not search-provider backends.
- **“Built in” overclaim:** distinguish native tool registration from external SDK/CLI/service dependencies.
- **Free-tier overclaim:** recurring credits, anonymous endpoints, and paid routes covered by promotional credit are different things.
- **Base-price undercount:** result limits, page extraction modes, summaries, deep search, and enrichment may add charges.
- **Secret leakage:** never show API keys while verifying route selection.
- **Catalog-equals-access:** `/models` may include region-gated, retired, unsupported, or policy-gated entries. Make a live request before recommending one.
- **Over-strict smoke assertion:** `OK.` versus `OK` is not an access failure; evaluate transport/provider success separately from instruction-following fidelity.
- **Auxiliary-route tunnel vision:** a good compression/vision/title model must satisfy access, context, privacy, cost, and fallback requirements—not merely return one short completion.
- **Stale pricing:** quote official numbers only after live verification and link the source.

## Answer Shape

A concise answer should normally contain:

1. direct yes/no or billing model
2. tool-interface versus backend distinction
3. current live route, if relevant
4. cost per real action with assumptions
5. free-credit/keyless caveat
6. official source links

Use a table only when it makes the units or layers easier to compare.

## Verification Checklist

- [ ] Agent-visible tool and provider are named separately
- [ ] Consumer product and developer API are distinguished
- [ ] Current route was inspected rather than inferred from the model name
- [ ] Catalog presence and live account access were distinguished when model availability mattered
- [ ] Live probes classified provider errors without mistaking punctuation differences for access failures
- [ ] Credential presence was checked without exposing a secret
- [ ] Actual wrapper request shape was verified when it affects price
- [ ] Pricing came from a current first-party page
- [ ] Free credits and card charges are not conflated
- [ ] Fallback routing and billing are explained accurately
- [ ] Arithmetic was tool-verified

## References

- See `references/hermes-web-routing-and-exa-pricing.md` for a concrete Hermes/Exa routing and cost-mapping case. Revalidate all provider lists, code paths, and prices before reuse.
- See `references/opencode-go-model-access-probe-2026-08-29.md` for a dated full-catalog access probe, a compression RegionError diagnosis, and the reusable Hermes smoke-test method. Treat model statuses as a snapshot and re-probe before acting.
