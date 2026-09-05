# Cursor and Codex explicit-invocation smoke tests

This note records a verified, no-task invocation pattern. Treat concrete versions as provenance only; always rerun each transport's live preflight.

## Disposable workspace

Create a temporary Git repository and expose the live Skill collection through both harness discovery roots:

```text
<tmp-repo>/.cursor/skills -> <live-skill-collection>
<tmp-repo>/.agents/skills -> <live-skill-collection>
```

Keep relay briefs and artifacts outside the tracked worktree, or commit only the disposable fixture setup so `git status --porcelain` starts clean.

## Cursor

Explicit invocation starts with:

```text
/write-plan
```

or:

```text
/execute-plan
```

For an invocation-only test, tell Cursor to load exactly that Skill, stop immediately, perform no repository investigation or substantive workflow action, call no dependency Skills, and return `SMOKE_OK <name>` or `SMOKE_FAIL <name>`.

Dispatch through the Cursor relay with:

- the disposable repository as `--cd`;
- `--read-only`, even for Skills normally used in writable stages;
- an explicit currently available model;
- a short watchdog; and
- a unique external `--out-dir`.

### Cursor evidence

Inspect the relay's `events.jsonl`. Passing evidence is a completed read tool call whose argument resolves to the expected discovery path, for example:

```text
<tmp-repo>/.cursor/skills/<skill-name>/SKILL.md
```

Confirm the tool result succeeded and returned that Skill's content. Do not accept the final success token by itself.

## Codex

Explicit invocation starts with:

```text
$write-plan
```

or:

```text
$execute-plan
```

Use the same taskless stop-boundary prompt. Dispatch through the Codex relay with:

- the disposable repository as `--cd`;
- `--read-only`;
- explicit model and reasoning effort;
- a short watchdog; and
- a unique external `--out-dir`.

### Codex evidence

The relay's compact `events.jsonl` can contain only the final message and usage. Use `threadId` from `result.json` to locate the persisted Codex rollout under the active Codex home. In that rollout, verify this sequence:

1. the user message contains the expected `$skill-name` token;
2. a subsequent injected user payload contains `<skill>`;
3. `<name>` equals the expected Skill name; and
4. `<path>` resolves to the intended live `SKILL.md` source.

That injected block is the positive proof that Codex expanded the explicit Skill reference.

## Prompt skeletons

Cursor:

```text
/<skill-name>

This is an invocation-only smoke test, not a real task. Explicitly load <skill-name>. As soon as loading is confirmed, stop. Do not inspect the repository, ask questions, create or modify files, run commands or tests, execute the Skill workflow, or invoke another Skill. Return only `SMOKE_OK <skill-name>`; if loading fails, return `SMOKE_FAIL <skill-name>` and one short reason.
```

Codex uses the same body with `$<skill-name>` as the first line.

## Final zero-side-effect checks

For every harness/Skill pair require:

- relay `status: completed` and exit code `0`;
- expected final success token;
- harness-specific attachment/read evidence;
- `touchedFiles: []`; and
- an independently clean `git status --porcelain`.

Observed successful smoke tests loaded `write-plan` and `execute-plan` in both Cursor and Codex while remaining read-only and leaving the disposable repository clean. The durable lesson is the evidence method, not the observed CLI versions or session IDs.
