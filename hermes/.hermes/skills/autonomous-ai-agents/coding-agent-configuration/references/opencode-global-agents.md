# OpenCode agent configuration

Use this reference for OpenCode built-in overrides and custom agent definitions installed globally or per project.

## Locations and discovery

- Global runtime config: `~/.config/opencode/opencode.json` or `opencode.jsonc`
- Global Markdown definitions: `~/.config/opencode/agents/<name>.md`
- Project runtime config: `opencode.json` or `opencode.jsonc` in the project
- Project Markdown definitions: `.opencode/agents/<name>.md`
- A Markdown filename becomes the agent name.
- `opencode debug config` prints the resolved merged configuration.
- `opencode agent list` prints built-in and custom agents with their effective permissions.

## JSONC versus Markdown

Both formats are first-class. Choose according to ownership and maintenance needs:

- Use JSONC when models, permissions, built-in-agent overrides, and other runtime policy should be visible in one schema-backed file.
- Use one Markdown file per custom agent when long role prompts benefit from natural prose and independent files.
- A robust hybrid keeps runtime metadata in JSONC and loads long prompts with `"prompt": "{file:./prompts/name.md}"`.
- Another valid hybrid uses JSONC for built-in overrides and Markdown for custom agents.

Keep one authoritative definition per agent name. Avoid defining the same agent in both JSONC and Markdown unless merge precedence has been deliberately tested. When the user asks only to correct permissions, preserve the current structure rather than performing an unsolicited format migration.

Check the active executable and version first:

```sh
which -a opencode
opencode --version
```

## Current permission schema

Current OpenCode Markdown frontmatter uses `permission` in the singular.

Relevant permission names:

- `task`: launching subagents; deny it when a custom worker or reviewer must not create nested children.
- `edit`: built-in writes, edits, and patches; deny it for reviewers that must not use those tools.
- `bash`: shell commands; restrict it separately when the reviewer must be hard read-only because `edit: deny` does not stop a shell command from writing files.

A strict reviewer may use `bash: deny`, or a catch-all deny followed by audited read-only exceptions such as `git status*`, `git diff*`, `git log*`, and `git show*`. Pattern rules use last-match-wins semantics, so place the catch-all first.

## Pattern-matching internals (verified against v1.18.25 source)

Verified in `packages/opencode/src/util/wildcard.ts`, `src/permission/index.ts`, and `src/tool/edit.ts` (dev branch):

- Patterns compile to an anchored regex (`^...$`): `*` → `.*` (crosses `/`, so it also matches nested directories), `?` → `.` (exactly one character, not digit-restricted). A trailing ` *` becomes optional, so `git status *` also matches bare `git status`.
- Evaluation is `findLast` over the merged ruleset: the LAST matching rule wins. Put `"*": deny` first and narrow allows after it.
- The `edit` permission governs the `edit`, `write`, AND `apply_patch` tools — a path allowlist therefore also permits creating new files under it.
- Edit/write permission is checked against `path.relative(worktree, filePath)`: config patterns must be worktree-relative (e.g. `.dev/review/*/round-??-review.md`). Paths outside the worktree become `../…` and cannot be allowlisted by in-repo patterns.

This enables a narrow `audit-write` reviewer: catch-all `edit`/`bash` deny plus one allow per exact artifact path pattern, e.g. `".dev/review/*/round-??-review-patch.md": allow`. Caveats: `??` accepts any two characters (not just digits), and `*` matching across `/` makes the boundary slightly wider than the literal path suggests. Port `Wildcard.match` to a local script to dry-run candidate paths against a ruleset before installing it.

Bounded worker example:

```yaml
---
description: Performs bounded delegated implementation work.
mode: subagent
permission:
  task: deny
---
```

Read-only reviewer example:

```yaml
---
description: Independently reviews work without modifying it.
mode: subagent
permission:
  edit: deny
  task: deny
---
```

Older list-shaped blocks such as the following are not equivalent:

```yaml
permissions:
  - action: subagent
    resource: "*"
    effect: deny
```

A current OpenCode build may still discover the agent while ignoring those fields. The conceptual “launch a subagent” restriction maps to the host permission named `task`, not `subagent`.

## Safe promotion from a repository

1. Inspect all source Markdown definitions.
2. Inspect `~/.config/opencode/agents/`; if absent, create it.
3. Refuse to replace unexpected destinations.
4. If source syntax is current, symlink when automatic updates are desired.
5. If source syntax is obsolete and source modification is not in scope, create schema-compatible local copies that preserve prompts and role boundaries.
6. Do not assign a concrete `model` when the source intentionally inherits OpenCode's default; report the inherited routing.

If replacing a just-created symlink with a local adapter, verify that it is a symlink and that its resolved target is the exact source file. Remove only that verified link. Writing directly to the symlink would modify the repository source.

## GNU Stow installation

A Stow package should mirror the target beneath `$HOME`, for example:

```text
dotfile/opencode/.config/opencode/
├── opencode.jsonc
└── agents/
    ├── worker.md
    └── reviewer.md
```

Install with:

```sh
stow --dir /path/to/dotfile --target "$HOME" opencode
```

Inspect conflicts first. Remove only known files or exact verified symlinks, preserve nontrivial local configuration, and refuse unexpected targets. After Stow runs, verify each link is relative when portability matters and that its resolved path equals the intended source. Re-running Stow should be idempotent.

## Acceptance

Run:

```sh
opencode debug config
opencode agent list
```

For every custom role, verify:

- the expected name appears and it is reported as `subagent`;
- the resolved model is unchanged or matches the requested route;
- `opencode debug config` contains the intended singular `permission` map;
- a no-nesting worker has an effective `task` rule with action `deny`;
- a reviewer has the requested `task`, `edit`, and optional `bash` restrictions;
- global or project symlinks resolve to the intended sources.

Do not accept the installation merely because the role name appears. A plural `permissions` value under provider `options` alongside an empty singular `permission` map proves that the intended policy is not enforced.

When output is large, parse each named agent block and assert role type, model, and permission/action pairs programmatically. Finally verify that Git changes are limited to the authorized configuration files. When global paths are symlinks to repository sources, a source edit should affect `opencode debug config` immediately; relinking is needed only when layout or targets change.