---
name: multi-repository-workspace-maintenance
description: "Use when synchronizing Git repositories and workspace links."
version: 1.2.1
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [git, workspace, symlink, synchronization]
---

# Repository and Workspace Synchronization

Synchronize one local Git checkout or a workspace made of several sibling repositories, especially when a private companion repository stores development records. Companion-repository records are addressed by their direct location (`development-artifacts/<project>/`), not through project checkouts: do not create a project-local `.dev`-style link by default. Existing legacy links still need safe maintenance or removal, and link work happens only on explicit request.

## Use This Skill When

- Updating a single local checkout from its upstream branch.
- Updating every repository in a sibling-repository workspace.
- A batch pull encounters dirty worktrees, divergence, or force-updated upstream history.
- Maintaining or removing explicitly requested project-local links to a private companion repository (for example legacy `.dev` symlinks); do not create such links by default.
- Migrating application-global configuration links when ownership moves between repositories, especially GNU Stow packages.
- Verifying that each checkout is synchronized without losing local work.

Do not use this as a substitute for normal single-repository feature development or release workflows.

## Safety Contract

- Treat “update the repository” as source synchronization only: do not build, install, copy artifacts into a consuming application, reload that application, or deploy unless the user explicitly includes that scope.
- Inspect before mutating.
- Preserve pre-existing uncommitted edits.
- Prefer fast-forward-only pulls; never create surprise merge commits in a batch operation.
- Do not rebase commits blindly after an upstream force-push.
- Never replace a real file, real directory, or unexpected symlink.
- Do not create or recreate project-local artifact links such as `.dev` by default: durable records live directly in the companion repository, and consumers (for example the project-taskflow Controller) address them by registered artifacts/project identity. Create, repair, or remove such links only on explicit request.
- Before aligning a divergent local branch to a canonical remote, ensure the working tree is clean, preserve the old HEAD on a backup branch, and obtain any approval required for a destructive reset.
- Verify the final filesystem and Git state rather than trusting command exit codes alone.

## Workflow

### 1. Establish scope and layout

Identify whether the request targets one checkout or a multi-repository workspace. For a repository update, stop the scope at Git synchronization unless installation, deployment, or consumer reload is named explicitly. For a workspace, identify the root, companion/artifact repository, and exact sibling projects in scope. Confirm that every expected checkout exists and has a `.git` directory. Inspect the companion repository's README or setup script before inventing link conventions; it may already define the authoritative project list and target layout.

For every project, record:

```sh
git status --short --branch
git remote -v
git rev-parse --abbrev-ref --symbolic-full-name '@{u}'
```

Also inspect whether the future link path is absent, a real path, or an existing symlink and, if it is a symlink, its current target.

### 2. Synchronize each project conservatively

Run this separately in each checkout:

```sh
git pull --ff-only
```

Do not declare a checkout current from `git status` or `git rev-list HEAD...@{u}` before a fetch: `@{u}` is a local remote-tracking ref and may be stale. The pull above refreshes the remote state and then fast-forwards safely.

A dirty worktree is not automatically a blocker: Git can fast-forward when upstream changes do not overwrite local edits. Preserve and report those edits. Do not stash or discard them merely to make the batch clean.

Track success per repository. One failure must not be hidden by a loop that exits successfully because a later repository succeeded.

### 3. Resolve rewritten upstream history deliberately

If `--ff-only` fails because the branches diverged, inspect before choosing a recovery:

```sh
git status --short --branch
git rev-list --left-right --count HEAD...@{u}
git log --oneline '@{u}'..HEAD
git log --oneline HEAD..'@{u}'
git log --graph --oneline --decorate --all --max-count=30
git cherry -v '@{u}' HEAD
```

Do not infer safety from similar commit subjects alone; rewritten commits may contain additional changes or different patches.

When the remote is explicitly canonical and the local working tree is clean, preserve the pre-alignment HEAD under a unique backup branch, then align the checked-out branch to its upstream:

```sh
git branch backup/pre-sync-<old-short-sha> HEAD
git reset --hard '@{u}'
```

If the local-only commits might still be authoritative, stop and ask whether to merge, rebase, retain a side branch, or align to remote. A backup branch is a safeguard, not permission to discard ambiguous work.

### 4. Create or repair relative artifact links

Apply this section only to links that already exist or were explicitly requested; never reinstate a default project link such as the retired `.dev` convention. Prefer a checked-in, idempotent setup script in the companion repository, and read it before executing it; a retired script kept as a no-op compatibility entry (creating and deleting nothing) is intended behavior, not a defect. A safe link-managing script should:

1. Derive its own absolute location and the workspace root.
2. Use a relative target from each project, such as `../companion-repo/<project>/<records-directory>`.
3. Accept an existing symlink only when its target exactly matches the expected string.
4. Refuse to replace real paths or links to unexpected targets.
5. Fail loudly if an expected project checkout or target directory is missing.

If no script exists, apply the same checks before calling `ln -s`. The project-local path is itself the directory-shaped symlink; do not first create a real directory with the same name.

### Retire companion-directory dependencies

Treat a request to remove a link, update developer instructions, and retire the backing data as separate scopes. For Kenan, the default is direct `development-artifacts/<project>/` records with no project-local `.dev` alias; this does not retire the artifact repository or authorize deleting history. A prior commit/push grant for one repository change does not extend to a later cross-repository cleanup.

1. Inventory every affected checkout with `git status --short --branch` and inspect each candidate with `os.path.lexists`, `is_symlink`, and `readlink`; a real directory must not be handled as a link. Save HEAD/index state, exact link targets, and bytes or hashes of pre-existing modified and untracked files before editing shared workspaces.
2. Trace consumers and recreators before unlinking: developer instructions, executable configuration, implicit output defaults, directly invoked tests, report writers, setup scripts, and active Memory/Skill conventions. Separate actual path dependencies from historical quotations, defensive `.gitignore` entries, and unrelated symbols such as a filesystem device-number field.
3. Remove or redirect executable defaults first. Prefer explicit persistent output paths and the existing isolated-test bootstrap rather than another generic project alias. Write a regression that fails when a command silently recreates the retired directory; exercise report generation with a deliberately failing local child when a real model/network call is unnecessary, and never label that fixture a successful live-model run.
4. Retire setup behavior and current instructions together. A compatibility setup entry may remain as a no-op; test that it neither recreates missing links nor alters existing targets. Mark retained research and evidence as historical instead of rewriting original task records or importing stale manuals into AGENTS.md.
5. Unlink only exact verified aliases and preserve their targets. When a real directory also needs removal, move it to an explicitly chosen archive and compare its complete file manifest before and after. Never rewrite Controller registration, authorization, or task history merely to remove a convenience alias: use the registered `artifactsDir`/project identity directly.
6. Verify with the aliases absent: run the affected full checks/builds, resolve existing projects through their real paths, and check runner identity and applicable permission gates. Restart only confirmed-idle runners when their loaded source identity must change. Compare registration/configuration and task objects to the baseline, and verify unrelated dirty files and Git refs remain unchanged. Distinguish a preserved pre-existing dirty-worktree gate from a newly introduced dependency failure; do not bypass it to claim every project is unblocked.

### 5. Migrate package-managed global configuration

When a repository adopts an application configuration package, prefer the repository's declared package manager—commonly GNU Stow—over hand-building equivalent links.

1. Synchronize both the old owner and the new dotfile/config repository before rewiring; an upstream move may intentionally delete the old source files and leave existing links dangling.
2. Read the dotfile repository's README and confirm the package mirrors the destination beneath `$HOME`.
3. Inventory every destination with a check that detects dangling symlinks. `Path.exists()`/`os.path.exists()` is insufficient by itself; use `lexists` plus `islink` and `readlink`.
4. Replace only paths proven to be the exact old links or exact superseded regular files. Refuse unexpected files, directories, or link targets.
5. Run the package manager from the declared repository, for example:

```sh
stow --dir /path/to/dotfile --target "$HOME" <package>
```

6. Verify each installed link resolves to the exact package source. Then invoke the consuming application's own configuration introspection command; filesystem correctness does not prove the application interpreted the configuration as intended.

See `references/gnu-stow-application-config-migration.md` for a worked verification pattern, including custom-agent configuration checks.

### 6. Verify every repository and link

Fetch once more, then verify branch synchronization:

```sh
git fetch --quiet origin
git rev-list --left-right --count HEAD...@{u}
```

`0 0` proves that the checked-out branch and its upstream currently point to the same history. Separately run `git status --short --branch` so retained working-tree modifications remain visible.

For each artifact link, verify all of the following:

- It is a symbolic link.
- `readlink` returns a relative target.
- Resolving it reaches the exact expected companion directory.
- The resolved target exists and is a directory.
- `git check-ignore -v <link-path>` confirms the project repository ignores it.

A retired companion setup script kept as a no-op compatibility entry must stay side-effect free: verify it creates and deletes nothing. When a live link-managing script still exists, re-run it once when practical; an idempotent script should report that links are already configured and make no changes.

## Reporting

Report results per repository, including:

- synchronized branch/upstream status;
- any pull failure and the recovery chosen;
- the name of any backup branch created;
- retained uncommitted modifications;
- each link's relative target and verification status.

Never summarize a batch as fully clean if one repository still has local edits, is ahead/behind, or has a broken/unignored link.

## Pitfalls

- A pre-fetch `0 0` comparison only proves equality with the cached upstream ref; fetch or run `git pull --ff-only` before claiming the repository is current.
- Plain `git pull` may create merge commits; use `--ff-only` for repository maintenance.
- A force-updated remote can make a formerly tracking local branch diverge even when remote work supersedes it.
- `git cherry` compares patch equivalence, not semantic intent; a `+` result does not prove local work is missing upstream.
- Shell loops can mask per-repository failures unless exit codes are captured and checked individually.
- Quoting complex shell probes inside another scripting language is fragile; use simple commands or structured subprocess calls for verification.
- Absolute symlinks break when the workspace moves or is cloned on another machine.
- A dangling symlink can report `exists = false`; inspect with `lexists`/`lstat` before treating the path as absent.
- Creating a real directory where a symlink is intended (historically `.dev`) before `ln -s` changes the link location and violates the intended layout.
- An application listing a custom configuration object proves discovery, not semantic enforcement; inspect its merged/effective configuration when available.
- Permission-schema migration is semantic, not mechanical: preserve each role's intended delegation authority. A reviewer may deny edits while explicitly allowing subagent tasks for evidence gathering.

## References

- `references/forced-upstream-rewrite-and-artifact-links.md` — worked pattern for safely recovering a rewritten tracking branch and validating sibling relative links.
- `references/gnu-stow-application-config-migration.md` — safe ownership migration from stale/manual links to a Stow-managed application package, with consumer-level verification.
