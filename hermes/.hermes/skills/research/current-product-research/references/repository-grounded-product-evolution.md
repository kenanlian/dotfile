# Repository-Grounded Product Evolution Research

Use this pattern when evaluating several interacting feature directions for an existing software product while the parent agent should not inspect the codebase directly.

## Split the evidence streams

Run distinct, read-only repository researchers rather than several copies of the same broad brief:

1. **Architecture baseline** — current objects, state ownership, persistence, projection flow, invariants, and coupling points.
2. **One product problem per lane** — e.g. discovery/grouping, project workflow, or another coherent user job.
3. **Cross-feature interaction** — how proposed concepts alter existing object semantics and migration boundaries.
4. **Official external evidence** — host-platform API/docs and representative product paradigms, owned by the parent.

Each repository lane must distinguish repository fact, inference, and recommendation; cite file paths and symbols; remain read-only; and return exact session/result artifacts.

## Reconcile reports by evidence, not consensus

Parallel reports will conflict. Do not average their recommendations or count votes.

Use this priority:

1. Direct repository fact and public host API/type documentation.
2. A report that traces the complete relevant runtime/data path.
3. Product inference consistent with those facts.
4. Analogy to other products.

When one lane says a capability requires full-file scanning but another identifies parsed host metadata, verify the host API and prefer the stronger evidence. When a product object is described differently across lanes, inspect the reported fields and runtime semantics before naming it.

Document important reconciliations in the final synthesis so hidden disagreements do not become architecture assumptions.

## Build a concept-layer model before a roadmap

For collection-oriented products, classify proposed capabilities before discussing UI or sequence:

- **Source** — produces the candidate item set.
- **Filter** — narrows a source without becoming an independent container.
- **View** — search, sort, group, collapse, displayed fields.
- **Curation** — named, user-owned, persistent membership or overrides.
- **Derived signals** — read-only rollups such as task counts or relation counts.

This prevents tags, properties, links, saved views, and manual collections from becoming overlapping implementations of the same idea.

## Product synthesis

For each requested direction, state:

- user job and actual memory/recognition burden;
- recommended MVP and explicit non-goals;
- interaction with existing core objects;
- edge and unknown states;
- independently testable user value;
- prerequisites and likely rework traps.

Prefer a phased roadmap that validates cheap, high-value signals before introducing broad configuration systems. Separate zero-behavior architecture preparation from user-facing phases.

## External evidence discipline

The parent owns the citation ledger. Register official sources at retrieval time, use current official host documentation for API and native-product behavior, and use competitor examples to support a paradigm—not to justify copying a feature list.

## Verification

Before delivery:

- every parallel run completed and reports no writes;
- report count and touched files are checked programmatically;
- contradictions are explicitly resolved;
- repository facts are attributed to paths/symbols;
- external claims have ledger-backed citations;
- final recommendations separate product choice from technical prerequisite;
- no implementation plan is implied when the user requested research only.
