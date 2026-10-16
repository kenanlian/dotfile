---
name: delegated-development-acceptance
description: Use when accepting delegated code. Verify independently.
license: MIT
compatibility: Requires git plus the transport adapter used for the delegated coding agent.
metadata:
  version: 0.3.3
  hermes:
    related_skills: [cursor-delegate, pi-delegate, requesting-code-review, test-driven-development]
---

# Delegated Development Acceptance

Verify an implementation produced by a coding agent under the current task's execution contract. The implementation agent prepares the candidate; Hermes independently checks evidence. Keep technical verification separate from human acceptance: when the workflow reserves acceptance for the user, record only their actual decision, bound to the exact delivery version, commit, tree and manifest hash. Never replace a human gate with passing tests or an agent's completion message.

Kenan's standing policy: Hermes accepts deliveries that can be objectively verified from code, tests and actual non-UI behavior, then proceeds with already-authorized local integration without a ceremonial user approval. UI/UX appearance, interaction and subjective experience remain real user acceptance gates. Preserve the original delegation plus an exact-version independent verification report, label the decision as delegated technical acceptance, and never say the user personally tested the candidate. Advance permission alone is not a passing result; incomplete evidence remains incomplete. This policy does not waive native plan choices or expand network/publication permissions.

## Procedure

### 1. Freeze the execution contract

Read the accepted plan and repository rules before dispatch. Record the repository, branch, baseline HEAD, clean-state expectation, exact target layout, required test commands, real-behavior smoke, prohibited side effects, and landing authorization. Verify load-bearing hashes or versions when the plan pins them. Classify acceptance at this point: objective code and non-UI behavior belong to Hermes's independent verification; UI/UX appearance and subjective interaction expectations belong to the user. For mixed deliveries, separate those dimensions rather than asking the user to repeat technical checks. Do not turn a command-line walkthrough into a mandatory human gate merely because the workflow calls it tool acceptance.

Do not silently broaden scope or let the coding agent reinterpret exclusions. Do not authorize commit, push, PR, release, or deploy unless the controlling request explicitly does.

### 2. Identify the execution contract

For Kenan's project development, use `project-taskflow`: the controller owns native planning, explicit same-context/fresh-context/stay-plan choices, task worktrees and version-bound delivery. Do not impose execute-plan, a fresh implementation session, uncommitted delivery, or a separate transport result format. Those are task-specific decisions, not acceptance defaults. Preserve the controller's exact thread/run, Git commit/tree, manifest and check evidence.

For an explicitly requested one-off coding-agent task, use its selected transport adapter and actual result contract. Native turn completion, transport exit and accepted/integrated delivery are distinct facts.

### 3. Monitor without disturbing healthy work

Let a healthy long-running process run. When the user requests a check interval, wait for that cumulative interval before polling. If the process-wait tool has a shorter ceiling, chain bounded waits silently and treat them as one interval. Do not repeatedly inspect the repository, terminate, or restart merely because one wait window expired.

Relay mid-run permission or acceptance-policy clarifications explicitly: retain their original source and bounded scope in durable task artifacts, then inspect the live pending-request identity. A question printed as ordinary agent text is not an answerable structured request. Use the supported answer path for a matching live request; otherwise, at a known terminated checkpoint, continue the exact execution thread with feedback containing the existing permission. Do not ask the user to grant it again, invent a scope change for an in-plan permission, or claim that saving consent delivered it to the child. Verify the feedback receipt and same-thread continuation before reporting successful relay.

### 4. Reproduce acceptance independently

Never accept the implementer's report as evidence. Run the named suites and real smoke yourself, then read back retained `result.json` and raw event files.

Record the actual interpreter binary/version for both implementation checks and independent verification. When they differ within the declared support range, reproduce the full suite on both rather than assuming the implementer's environment covers the operator's. For machine-parsed Node test output, run the child explicitly with `node --test --test-reporter=tap`, enforce its exit status, and parse the selected reporter; default output can change between Node versions or terminal contexts. Require a positive assertion count for real behavioral fixtures so an empty suite cannot establish success.

Bind each live-model smoke to the source commit/tree that actually ran. After a checker-only repair, retain the historical live-run identity and report a fresh offline re-audit separately; do not relabel old evidence as a live run of the new source. After changes to production transport or lifecycle behavior, require a new minimal live smoke under the existing bounded permission, preserving earlier failures and any same-session repair history.

Inventory the whole candidate with `git status --short`, tracked diffs, and every untracked file. Ordinary `git diff` omits untracked files and can hide most of a newly added feature. When the plan declares a target layout, compare expected and actual path sets programmatically and fail on missing or unexpected paths.

When the user questions the SIZE of a change ("did this feature really need N lines?"), calibrate before judging. Compute per-file added lines by counting `git show ref:file` output at baseline and head; classify test vs production lines by path (`.test.`, test trees, `__mocks__`); compare the feature's test/production ratio against the repo-wide ratio rather than a fixed number. Group production additions by concern (domain services, UI managers, commands, modals, i18n catalogs, settings wiring) so localization strings and wiring are not misread as logic bloat. Probe for real duplication by grepping production files for repeated sanitizer regexes / re-implemented validation of the same config — a few hits across layer boundaries is defensive validation; a helper reimplemented per call site is the finding.

For real agent smokes, verify from files rather than prose:

- every stage has terminal `status=completed` and `error=null`;
- the expected terminating tool succeeded exactly once;
- an `agent_settled` event exists;
- resumed work preserves the exact session ID;
- reviewer sessions are fresh and distinct where required;
- read-only snapshots are unchanged;
- write-stage touched files and deterministic check results are host-derived; and
- canonical Artifact paths and hashes exist.

### 5. Review only when the current contract requires it

Independent verification is required; a separate reviewer is not a fixed workflow stage. Commission a review only when the user or accepted task contract calls for one. Do not automatically create reviewer rounds or revive the retired Pi/Harness pipeline. When a review is required, give the reviewer the accepted plan, complete candidate inventory, repository path and objective evidence, and require direct inspection of tracked and untracked files.

When the user asks for a fresh subagent review, use `delegate_task`; do not silently substitute Cursor or another coding-agent CLI because delegation failed. If dispatch fails before review starts, report the delegation failure and resolve the configured delegation provider/model or ask before choosing another transport.

For protocol and orchestration code, review these boundaries explicitly even when tests are green:

- structured/canonical inputs are parsed and validated before agent dispatch;
- JSONL framing is tested in both production reader directions with literal U+2028/U+2029 inside JSON strings, split multibyte UTF-8, CRLF and backpressure; emoji-only tests do not prove record framing, and valid string separators must not terminate an LF-delimited record;
- mutable job/input documents are rebound to authoritative ledger hashes before Result consumption;
- canonical Artifacts are hashed and parsed from disk, with wrapper Job/session/input/payload identity compared before ledger or lifecycle writes;
- verification Result evidence is complete, exactly bound to Job checks, and status/exit evidence is coherent;
- durable Store/CAS paths enforce template state transitions and allowed stages, not only policy or API layers;
- public schemas recursively match runtime validators;
- any forbidden or duplicate submit-tool execution fails closed;
- idempotent replay binds the stored Result to the full current Job identity and hash;
- lexical and realpath containment are checked before filesystem writes or command execution;
- index-only Git changes are represented in snapshots;
- terminal truth comes from structured Result/Event artifacts, never final prose; and
- failure paths publish a terminal Result and release locks when the contract requires it.

### 6. Rework the exact execution session

For each blocking finding, first confirm it against the plan and source. Resume the exact execution session with the same explicit model; never replace a resumable implementation session with a fresh agent. If another blocker is found while rework is active and no supported steering path exists, retain a durable findings list with reproduction, affected version and relay status; deliver it at the next supported terminal checkpoint and recheck every unresolved finding before accepting a later version. Recording a finding is not relaying it, and fixing the first rejection does not resolve the rest.

Send a concrete failure packet containing file/line or contract location, mechanism, required behavior, and the regression test that must go RED then GREEN. Preserve earlier fixes and require the contract's gates and real smoke. Commit policy follows the current task: taskflow delivery requires a committed clean candidate, not a blanket no-commit rule. After rework, repeat independent verification and any separately required review; renew acceptance for the exact changed version under its policy (delegated technical verification for code-only work, real user decision for UI/UX).

Keep the fix loop bounded by the controlling review workflow. If blocking defects remain after its allowed cycles, report them honestly instead of lowering acceptance.

### 7. Report the verdict

Report implementation and verification as separate dimensions: identify what code exists, what automated checks passed, what real end-to-end paths passed, and what remains blocked or deferred. Name any applicable human checkpoint and distinguish reasoning finished, delivery ready, delegated technically accepted, personally human accepted, and exact-version integration completed; a green first implementation is not a completed workflow. Preserve failed-attempt evidence even after recovery, and distinguish a recovered existing thread from a successful clean fresh-thread run. Report only state changes from background notifications; deduplicate by project/task/run and event sequence or delivery version so repeated notifications do not trigger repeated acceptance requests.

## Pitfalls

- Include untracked files in every review inventory; `git diff --stat` excludes them.
- Re-run suites with the plan's exact full-suite command (e.g. whole-directory discovery), not per-file runs the implementer chose — per-file green can hide cross-module import/path shadowing that only fails when the suite runs combined.
- Treat mock/stub-based smoke as integration evidence only when the mock enforces the real dependency's hard contract checks (input ownership, protocol validation, exit conditions); otherwise demand one minimal real-component end-to-end before accepting the milestone.
- When a supervised child process produces no output, check that its stderr is actually captured somewhere — a supervisor spawning with stderr=DEVNULL makes instant crashes invisible and the green/red signal you are reading may be a silent restart loop.
- Treat a green suite as necessary, not sufficient; tests can encode the wrong contract.
- Validate paths before creating the rejected target; post-write containment checks already violated read-only scope.
- Realpath command working directories; lexical containment permits symlink escape.
- Include Git status/index metadata in snapshots; content-only comparison misses staged changes.
- Require a clean single structured submission; accepting success after an earlier submit-tool error weakens fail-closed semantics.
- Validate nested schema shape, not only top-level keys; external consumers rely on the public protocol.
- Preserve retained smoke roots until acceptance finishes; they are the audit trail for Result, Artifact, and raw events.
- Answer size questions from per-ref `git show` line counts, never `git diff --stat` — diffstat nets insertions against deletions and cannot split test from production lines.
- Treat a size spike as a trigger to read the heaviest modules, not as a verdict: weight forced by product semantics (a write path that must survive its target being open in an editor, multi-window UI, embedding a host-owned editor) is a product decision, not duplication. Report which decisions drive the weight and let the user make the keep/simplify call; only code-level duplication or layer-boundary violations are yours to flag as defects.
- When a feature adds a whole subsystem, check the repo's declared source-of-truth docs (architecture/patterns files named in AGENTS.md) actually mention it — a large feature landed with zero coverage there is an acceptance finding to report even when CI is green.
