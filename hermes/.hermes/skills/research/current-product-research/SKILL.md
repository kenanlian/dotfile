---
name: current-product-research
description: "Use for current research on fast-changing software."
version: 1.0.0
metadata:
  hermes:
    category: research
    tags: [product-research, competitive-analysis, changelog, positioning, citations]
    related_skills: [grounded-citations]
---

# Current Product Research

Research new or rapidly iterating software products without mistaking old launches, obsolete terminology, or marketing claims for the present product.

## When to Use

Use for:

- Product positioning, feature, audience, or competitive research
- Products whose UI, concepts, pricing, or customer focus changed recently
- Requests that explicitly prioritize recent information
- Comparisons between a new AI-native product and mature product categories

Pair with `grounded-citations` when the deliverable needs inline citations.

## Core Principle

**Establish the dated current state before synthesizing positioning.**

Do not build a feature list from search snippets accumulated across years. First identify the latest stable product vocabulary, architecture, plans, platform availability, and target-customer statement. Then use older material only to explain evolution.

## Workflow

### 1. Declare the research cutoff

Record the live date and write the deliverable as “截至 YYYY-MM-DD”. Product facts are a dated snapshot, not timeless truth.

### 2. Split parallel research by evidence stream

Good independent workstreams are:

1. **Current official product:** homepage, overview, docs/help, download page, pricing, changelog, release posts, API/agent docs.
2. **Customer and market evidence:** recent founder interviews, launch pages, app-store reviews, browser-extension reviews, community posts, hands-on demos.
3. **Category comparison:** official pages for representative incumbent note, writing, collaboration, or specialist tools.

Ask each researcher to return URLs, dates, explicit claims, and a clear fact-vs-analysis distinction. Do not ask every worker to produce the same broad report.

### 3. Build a product-evolution timeline

Extract recent structural changes such as:

- renamed or merged core objects
- navigation or workflow redesigns
- new output modalities
- pricing or credit-system changes
- platform availability
- target-customer shifts
- ecosystem or marketplace launches

Use this timeline to mark old terminology as historical. If an older guide conflicts with a newer changelog or launch post, prefer the newer official source and explain the transition.

### 4. Model the current product as a system

Capture:

- **Primary job:** what progress the product helps a user make
- **Core objects:** project, file, task, memory, workflow, database, etc.
- **Input → process → output:** what enters, what the product does, what leaves
- **AI role:** assistant, editor, retriever, agent, long-term companion, executor
- **Control surface:** editing, versioning, approval steps, model choice, export
- **Distribution:** sharing, publishing, integrations, marketplace
- **Business model:** plans, credits, usage limits, paid ecosystem
- **Constraints:** collaboration, privacy, data portability, offline use, platform gaps

This system model is more durable and useful than a flat feature list.

### 5. Treat dynamic pages as dynamic

Pricing and plan matrices are often client-rendered and omitted by text extraction.

Fallback order:

1. official extracted page text
2. official page source or embedded JSON-LD / application state
3. official app-store in-app purchase listing
4. recent official pricing/update post
5. third-party pricing only as a labeled secondary check

Report “starts at” when a plan has multiple credit bands. Separate web price from app-store price. Never infer current credits from an old review.

### 6. Identify customers by jobs, not only personas

Separate:

- **Core current customer** supported by recent company statements or repeated evidence
- **Adjacent users** supported by use cases or app listings
- **Aspirational market** from founder vision
- **Poor-fit users** inferred from missing capabilities or deliberate positioning

Write Jobs-to-be-Done such as “turn collected sources into a publishable artifact” rather than only demographics such as “students and creators.”

### 7. Compare product paradigms, not slogans

For a new product versus incumbents, compare along:

- default starting point
- core data object
- time horizon
- information entry
- AI role
- research-to-output closure
- knowledge reuse
- collaboration and governance
- publishing and export
- offline/data ownership/portability
- best-fit and poor-fit users

Acknowledge convergence: mature incumbents may now have AI agents, and new products may have notes or documents. The meaningful difference is the **default workflow and product center of gravity**, not whether a checkbox feature exists.

### 8. Separate evidence from judgment

Use explicit labels or phrasing:

- **Official fact:** directly stated or demonstrable in current official material
- **External evidence:** review, store listing, interview, or demo
- **Analysis:** synthesis about positioning, strengths, or likely fit
- **Unverified/gap:** no current authoritative evidence found

Marketing claims such as “with taste,” “best,” or revenue success stories must remain attributed to the company unless independently corroborated.

### 9. Include limitations and adoption conditions

At minimum assess:

- product volatility and terminology churn
- breadth-versus-depth tradeoff
- cloud/privacy implications
- collaboration and governance maturity
- platform coverage
- pricing/credit predictability
- export and data portability
- ecosystem quality and maturity

End with conditional guidance: “This product is valuable when X is the bottleneck; prefer Y when the bottleneck is Z.”

## Parallel Citation Discipline

When using citation ledgers with subagents, keep the **parent as ledger owner**:

1. Parent creates or resets one task-specific ledger.
2. Children return raw URLs/titles, dates, claims, and quotes—not final citation numbers.
3. Parent registers sources and assigns final ids after consolidation.
4. Never let children reset the parent/default ledger.
5. If children need ledgers, give each a unique path and re-register their URLs in the parent ledger; do not copy child ids.

This prevents concurrent resets and number collisions.

## Deliverable Structure

A strong report usually contains:

1. Scope and cutoff date
2. Executive one-sentence positioning
3. Current product system and recent evolution
4. Main selling points, each tied to user value
5. Core, adjacent, aspirational, and poor-fit customers
6. Paradigm comparison with incumbent categories
7. Limitations and risks
8. Conditional adoption guidance
9. Sources

## Verification Checklist

- [ ] Current date and cutoff are explicit
- [ ] Latest official changelog/release material was checked
- [ ] Old terminology is labeled historical
- [ ] Current pricing was checked from an official dynamic source if necessary
- [ ] Platform availability is current
- [ ] Customer claims distinguish current, adjacent, and aspirational groups
- [ ] Comparison uses official incumbent sources
- [ ] Facts, company claims, external evidence, and analysis are distinguishable
- [ ] Limitations include privacy, portability, collaboration, and volatility
- [ ] Citation ids were assigned only by the final ledger owner

## References

- See `references/youmind-2026-case.md` for a condensed case study of handling rapid terminology, positioning, and pricing changes. Revalidate all dated facts before reuse.
