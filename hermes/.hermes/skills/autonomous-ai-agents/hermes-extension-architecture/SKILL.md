---
name: hermes-extension-architecture
description: "Use when designing Hermes extensions without core forks."
version: 0.1.1
author: Hermes Agent
license: MIT
platforms: [macos, linux, windows]
metadata:
  hermes:
    tags: [hermes, plugins, sidecar, architecture, kanban, maintainability]
    category: autonomous-ai-agents
    related_skills: [hermes-agent, multi-profile-agents]
---

# Hermes Extension Architecture

Design user-specific Hermes capabilities so official upgrades remain replaceable instead of becoming source-merge projects. Prefer documented extension contracts and isolate any unavoidable coupling behind one tested adapter.

## Current Project Workflow Boundary

Kenan's project development uses Project Taskflow Controller as the only task lifecycle owner. Do not activate Hermes Kanban, dispatchers, task heartbeats or mirrored board records for it. The Kanban/plugin/worker patterns below describe optional architectures only when a user explicitly requests those systems; they are not the current project-development procedure. Follow project-taskflow for the active direct/plan, acceptance and integration contract. An explicit request for Hermes to edit the workflow itself is a bounded maintenance exception, not permission to bypass Controller for product work.

## Analysis Gate

When the user asks to analyze, compare, or discuss first, stay read-only. Inspect plans, the installed Hermes version, current extension documentation, and the existing external component, then return feasibility, tradeoffs, recommendation, and remaining decisions. Do not edit code, configuration, plans, or repositories until the user separately authorizes implementation.

## Procedure

### 1. Separate responsibilities before choosing a mechanism

List what must be owned by each layer:

- Hermes: agent sessions, native tools, Kanban task-level lifecycle, profiles, and product-facing acceptance capabilities.
- External extension: fine-grained workflow state, transition policy, retries, immutable artifacts, and orchestration-specific configuration.
- Harness or worker backend: one bounded execution job and one structured terminal result.

Do not let a plan's current file list decide the architecture. Re-derive ownership from invariants and acceptance requirements first.

### 2. Verify the live extension surface

Load the `hermes-agent` skill and the matching current references before making claims. Check the installed source and CLI help only for the exact seams under consideration:

- general plugins: typed tools, CLI commands, bundled plugin skills, plugin-owned config/state;
- MCP: external reusable tool servers;
- Kanban: worker tool injection, dispatcher claim behavior, review-lane behavior, heartbeat, and lifecycle ownership;
- observer hooks: timing and whether return values can affect behavior.

Inspect the external component's real Job/Result contract and tests rather than reasoning from its design document. Treat official documentation and the installed checkout as the source of truth; Hermes changes quickly.

### 3. Choose the smallest maintainable placement

Use `references/placement-decision.md` for the decision table. Default order for Kenan's private capabilities:

1. Skill plus existing CLI/tools when no new machine interface is required.
2. Out-of-tree general plugin when Hermes workers need typed tools, plugin-owned state, or a dedicated CLI.
3. MCP server when the capability is a reusable external tool independent of Hermes lifecycle.
4. Sidecar service when work must continue independently of an agent process.
5. Core modification only when an atomic dispatcher or lifecycle guarantee cannot be expressed through a documented extension point.

A source fork is not the default merely because it offers the cleanest internal call graph.

### 4. Design the external control plane

For a durable autonomous workflow, prefer this split:

- A standalone Hermes plugin registers a small typed control surface such as `status`, `advance`, and `submit_acceptance`, plus a namespaced workflow skill or CLI diagnostics.
- The controller and transition policy live in the external package, not in `hermes_cli/`.
- Persist workflow manifests, Job ledger, repo leases, and artifact hashes in plugin-owned storage or a separate SQLite database outside both `kanban.db` and the Git worktree.
- Exchange only versioned `job.json` / `result.json` / `events.jsonl` files with the execution Harness.
- Keep Kanban authoritative only for coarse `ready/running/review/blocked/done`; store internal stages externally.
- Run workflow cards through a dedicated Hermes profile so plugin tools and instructions are fixed at worker startup and do not enlarge unrelated sessions.

Interface rule for model/operator-invoked CLI commands: make safety-relevant parameters explicit and required — reject with a non-zero exit and a stderr message that names the exact flags to re-run with, rather than silently applying a config default. A default hides the decision (a fixed notify target cannot follow the invoking session); a rejection teaches the caller the contract at the moment it matters. Keep the gate at the CLI boundary only when programmatic/service-layer callers legitimately differ; do not duplicate the check at every layer.

Prefer a plugin-assisted dispatcher-spawned worker over a pure polling daemon when the flow needs native worker ownership, review provenance, browser/Obsidian acceptance, or task-scoped Kanban tools. The worker should act as a thin pump over deterministic controller tools, not as the state authority.

### 5. Audit the hard seams explicitly

Before declaring an external design equivalent, answer all of these:

- **Admission:** Can two cards be claimed before the external repo lease is acquired? Observer hooks cannot veto a claim when their return values are ignored.
- **Ownership:** Can lifecycle actions retain the current `run_id` and claim guard? Avoid `--force` as normal automation.
- **Liveness:** Who extends the Kanban heartbeat while a long Harness process runs?
- **Recovery:** Does a stable idempotency key map to the same run directory, and does an existing valid Result win over process/PID guesses?
- **Review:** Does every formal reviewer remain fresh and read-only while rework resumes the original Planner/Implementer session?
- **Acceptance:** Is product acceptance submitted through a typed host tool in a fresh review worker rather than inferred from tests or prose?
- **Serialization:** Is the conservative concurrency rule sufficient for the board/profile topology, including the gap between implementation and review dispatch?

If a seam is unavailable, distinguish a conservative MVP compromise from a true correctness gap. For example, serializing one dedicated profile globally may be acceptable for an MVP but is not equivalent to per-repository parallel leases.

### 6. Minimize upgrade coupling

Use documented PluginContext methods and public CLI/tool contracts. Do not import Hermes internals or write Hermes-owned SQLite tables from the extension unless no stable surface exists. If one internal adapter is unavoidable:

- keep it in one module;
- fail closed on version or signature mismatch;
- test it against the installed Hermes release through the real plugin discovery path;
- make upgrade verification replace the adapter rather than merge a fork.

Run plugin validation and contract smoke tests after every Hermes update. Verify behavior, not source layout or exact registry counts.

Plugin tool handlers must return `str` — `json.dumps(payload, ensure_ascii=False)`, never a raw dict. A dict return executes the handler fully (side effects included) and only then fails tool-result serialization (`tool_result_contract`), so the model sees an error for an operation that actually succeeded and may retry it. Cover the `str` contract in the handler's unit tests, not just the payload fields.

### 7. Audit the implemented workflow end to end

When reviewing an implementation rather than designing one, trace the same workflow fact through every enforcing layer before declaring it present:

1. State/status enums and transition policy.
2. Job builder inputs, defaults, and persisted Manifest fields.
3. Harness schema, stage contracts, prompts, adapter dispatch, and terminating submit tools.
4. Worker tool guards and the native lifecycle projection.

A stage named in a design or policy is not implemented if its inputs never reach the Job that enforces it. Trace verification and acceptance data from the producing Artifact through the downstream Job and final gate. Explicitly test empty collections: predicates such as `all([])` can turn a missing verification configuration into a guaranteed pass.

Audit each persisted execution boundary in authority order:

1. Re-hash the mutable `job.json` and compare it with the immutable Job-ledger hash before deriving any Result expectation; otherwise a self-consistent replacement Job, Result, and Artifact can redefine the verification contract after dispatch.
2. Validate every host check as the complete Result-check record, bind its id/argv/cwd/expected exit code to the Job, and require status/exit/signal coherence. Missing or contradictory evidence is a protocol failure; a structurally valid failed check is workflow rework.
3. Re-hash and parse the canonical Artifact before ledger registration, then bind its wrapper, Job identity, session, inputs, and payload to the authoritative Job and structured Result.
4. Enforce template-owned status transitions and allowed Job stages inside the Store transaction, not only in parser or policy code; allow same-status checkpoints explicitly and keep any block/unblock operational exceptions narrow.
5. Keep runtime validators, public JSON Schemas, and terminating-tool schemas behaviorally equivalent, including cross-field outcome rules and stage-conditional input/verification cardinality.

When repairing a missing verification bridge, close it at both boundaries in this order:

1. Read the immutable canonical Plan Artifact, re-check its ledger hash before parsing, and reject a wrong envelope/schema instead of falling back to prose or a mock-only shape.
2. Translate approved checks into the Harness Job contract explicitly: argv array, repo-contained realpath cwd, bounded timeout, and expected exit code. Do not parse a human-readable `expected` sentence as machine policy; add a typed assertion field in a new contract version if stdout/stderr semantics must be enforced.
3. Require at least one verification check in the Implement Job builder so a future caller cannot recreate an empty gate even if the controller wiring changes.
4. Use TDD at the persisted-Job boundary: first make a workflow smoke assert that the Implement `job.json` contains the Plan checks and watch it fail, then add a builder-level empty-check rejection. Run both controller and Harness contract suites, and exercise a real Artifact envelope rather than trusting a simplified mock fixture.

Classify findings by mechanism instead of giving every missing guard the same priority:

- **Deterministic defect:** the intended control is absent on every run. State this separately from the probability that a bad output escapes; prioritize it as a correctness gap.
- **Unenforced invariant:** the prompt asks for behavior but the typed protocol permits omission. Under a trusted-model MVP, treat this as hardening unless the consequence is severe; do not describe model noncompliance as certain.
- **Tail liveness risk:** the problem appears only after hangs, crashes, or orphaned processes. Rank it by unattended duration and blast radius. Prefer progress-based stall detection and operator notification over a fixed hard timeout when healthy long-running agents must not be killed.
- **Operational drift:** stale processes, outdated documentation, or mixed runtime modules need remediation, but are not missing product capabilities.

For human intent discovery, prefer a foreground pre-intake Skill that produces a versioned, user-confirmed Requirement Artifact. Do not put interactive product discussion inside a headless Dispatcher card unless the product explicitly needs durable question/reply Artifacts, block/unblock semantics, and invalidation of downstream plans after each answer.

Do not build an arbitrary workflow engine merely because one fixed pipeline exists. Keep the core pipeline fixed until a second concrete workflow is proven. When that second flow appears, first inventory every assumption coupled to the old flow: Manifest/template validation, initial state, transition policy, Job input cardinality, output cross-field validation, prompts, reviewer inputs, CLI intake, diagnostics, and recovery tests. Then introduce an allowlisted, versioned template registry pinned in each Manifest—not a user-authored DAG DSL. Each template owns its initial action, allowed transitions, Job contracts and Artifact inputs, verification source, lifecycle gates, and retry budgets; persistence, leases, Harness supervision, lifecycle sagas, candidate binding, and product acceptance remain shared mechanisms.

Treat every allowlisted workflow template as a complete, fixed process contract, not as a bag of optional gates. Do not implement `enable_plan`, `enable_review`, or similar switches that silently compose variants. A direct requirement-to-implementation template ends after its own Coding Agent job and host deterministic checks; it must not enter a review lane, start an independent reviewer, or require product acceptance unless those stages are explicitly part of that named template. When a reviewed implementation flow has a real consumer, add it later as a separate versioned template rather than expanding direct mode.

For a direct flow, do not merely skip planning statuses while the Implement Job or implementation payload still requires a Plan Artifact. Source host-executed verification from a typed intake Artifact or project-owned configuration and fail closed when it is absent; never parse command authority from Markdown code blocks or let an Implementer invent commands after its Job is fixed. Start with explicit operator/template selection rather than an automatic complexity classifier, because misrouting a complex task silently removes gates.

Avoid fabricating a synthetic Plan solely to satisfy plan-centric contracts unless the user explicitly accepts that compatibility compromise: it obscures provenance and leaves direct-mode outputs coupled to fake work-package identifiers. Prefer a new versioned direct Job/output contract driven by the Requirement. Prove the existing full template is behaviorally unchanged, then test direct happy path, verification failure, structured blocking, exact-session rework, transport retry, crash recovery, and the absence of Plan, review-lane, reviewer, and product-acceptance side effects; finish with one real Dispatcher/Harness E2E.

Distinguish “supports an adapter” from “adapter is configurable” by checking both the Job schema and the actual dispatch implementation.

## Output Shape

Return architectural analysis in this order:

1. Feasibility verdict and confidence.
2. Recommended architecture and why.
3. What moves out of Hermes core.
4. What still relies on native Hermes behavior.
5. Compromises and hard gaps.
6. Revised implementation phases, without executing them.
7. Decisions requiring the user's confirmation.

Be explicit about whether “no core modifications” means zero source fork or zero coupling; an external plugin can avoid merge maintenance while still depending on documented Hermes contracts.
