---
name: intent-requirement-exploration
description: "Use for 意图探索流程 requirement exploration before coding."
version: 1.2.0
---

# Intent Requirement Exploration (意图探索流程)

Exploration-only workflow: analyze feasibility and converge decisions with the user. Never implement during exploration, and never persist the requirement before the user has decided.

## Procedure

- **Delegate technical exploration without starting implementation.** For Kenan's project work, use native Codex investigation/planning through `project-taskflow`; Hermes owns synthesis and user decision relay. Pi, Cursor or OpenCode are optional only when explicitly requested, using their transport contract. Do not resurrect the retired Pi default, stage harness, or fixed review pipeline. Exploration alone never registers a project, authorizes Git writes, or grants implementation.

1. **Read repo docs first.** Open the target repo's `AGENTS.md` and `.dev/` architecture docs before grepping — they usually state the exact scope/policy model and invariants, which saves most of the search time.
2. **Verify every user claim against code**, citing `file` + `symbol`. User perceptions of current behavior are often partially wrong (e.g. a control looks clickable but its action is a guarded no-op) — report discrepancies plainly, with evidence.
3. **Hunt interaction traps beyond the stated question:** persisted/global state that silently carries across modes (filters, selections), asymmetric handling between sibling features (one section scope-aware, another hard-coded), and hard-coded wording that names the wrong mode.
4. **Size the change through policy seams.** Look for a centralized capability/policy table (e.g. a `resolve*Capabilities` switch) before estimating — with such a seam the logic change is a few lines, and the real work is UX presentation + i18n + tests. Grep all consumers of the policy flags to size the fallout. An exhaustive dispatch with a `never` arm (e.g. per-scope pipeline step chains) is doubly useful: adding a variant is compiler-checked, and its consumer list is the audit surface the new variant must deliberately declare against.
5. **Deliver the analysis as:** 现状核实 (evidence table) → 可行性 + change surface (files/symbols + size) → options with ONE recommendation → numbered decision points the user can answer one line each. Never end with a vague "what do you think".
6. **Persist only after explicit authorization.** Finish discussion with the agreed scope, decisions, acceptance criteria, and open questions. Save a requirement only when the user asks; use ordinary file tools at the authorized path. Do not automatically enqueue work, implement, commit, or push.

## Pitfalls

- When the user says "先讨论 / 探索" the turn ends with analysis + decision points — do not also start implementing or writing the requirement in the same turn.
- Empty-state and disabled UI often disagree: check BOTH the projection layer (does the row render disabled?) and the action layer (is the click guarded?) — asymmetry between them is itself a finding worth reporting.
- Dormant persisted state beats clearing as the default recommendation: clearing on mode switch destroys user work silently; dormancy + a visible paused cue preserves it.
