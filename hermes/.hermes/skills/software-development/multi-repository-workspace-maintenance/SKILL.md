---
name: multi-repository-workspace-maintenance
description: "Use for syncing sibling Git repos and artifact symlinks."
version: 1.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [git, workspace, symlink, synchronization]
---

# Multi-Repository Workspace Maintenance

Maintain a workspace made of several sibling Git repositories, especially when one private companion repository stores development artifacts that public or separately versioned projects expose through ignored relative symlinks.

## Use This Skill When

- Updating every repository in a sibling-repository workspace.
- A batch pull encounters dirty worktrees, divergence, or force-updated upstream history.
- Wiring project-local directories such as `.dev` to a private companion repository.
- Migrating application-global configuration links when ownership moves between repositories, especially GNU Stow packages.
- Verifying that each checkout is synchronized without losing local work.

Do not use this as a substitute for normal single-repository feature development or release workflows.

## Safety Contract

- Inspect before mutating.
- Preserve pre-existing uncommitted edits.
- Prefer fast-forward-only pulls; never create surprise merge commits in a batch operation.
- Do not rebase commits blindly after an upstream force-push.
- Never replace a real file, real directory, or unexpected symlink.
- Before aligning a divergent local branch to a canonical remote, ensure the working tree is clean, preserve the old HEAD on a backup branch, and obtain any approval required for a destructive reset.
- Verify the final filesystem and Git state rather than trusting command exit codes alone.

## Workflow

### 1. Establish scope and layout

Identify the workspace root, the companion/artifact repository, and the exact sibling projects in scope. Confirm that every expected checkout exists and has a `.git` directory. Inspect the companion repository's README or setup script before inventing link conventions; it may already define the authoritative project list and target layout.

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

Prefer a checked-in, idempotent setup script in the companion repository. Read it before executing it. A safe script should:

1. Derive its own absolute location and the workspace root.
2. Use a relative target from each project, such as `../companion-repo/<project>/.dev`.
3. Accept an existing symlink only when its target exactly matches the expected string.
4. Refuse to replace real paths or links to unexpected targets.
5. Fail loudly if an expected project checkout or target directory is missing.

If no script exists, apply the same checks before calling `ln -s`. The project-local path is itself the directory-shaped symlink; do not first create a real directory with the same name.

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

Re-run the companion setup script once when practical; an idempotent script should report that links are already configured and make no changes.

## Reporting

Report results per repository, including:

- synchronized branch/upstream status;
- any pull failure and the recovery chosen;
- the name of any backup branch created;
- retained uncommitted modifications;
- each link's relative target and verification status.

Never summarize a batch as fully clean if one repository still has local edits, is ahead/behind, or has a broken/unignored link.

## Pitfalls

- Plain `git pull` may create merge commits; use `--ff-only` for batch maintenance.
- A force-updated remote can make a formerly tracking local branch diverge even when remote work supersedes it.
- `git cherry` compares patch equivalence, not semantic intent; a `+` result does not prove local work is missing upstream.
- Shell loops can mask per-repository failures unless exit codes are captured and checked individually.
- Quoting complex shell probes inside another scripting language is fragile; use simple commands or structured subprocess calls for verification.
- Absolute symlinks break when the workspace moves or is cloned on another machine.
- A dangling symlink can report `exists = false`; inspect with `lexists`/`lstat` before treating the path as absent.
- Creating a real `.dev` directory before `ln -s` changes the link location and violates the intended layout.
- An application listing a custom configuration object proves discovery, not semantic enforcement; inspect its merged/effective configuration when available.
- Permission-schema migration is semantic, not mechanical: preserve each role's intended delegation authority. A reviewer may deny edits while explicitly allowing subagent tasks for evidence gathering.

## References

- `references/forced-upstream-rewrite-and-artifact-links.md` — worked pattern for safely recovering a rewritten tracking branch and validating sibling relative links.
- `references/gnu-stow-application-config-migration.md` — safe ownership migration from stale/manual links to a Stow-managed application package, with consumer-level verification.
