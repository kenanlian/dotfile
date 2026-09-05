# GNU Stow application-config migration

Use this pattern when application-global configuration moves from one repository to a dotfile repository whose package mirrors paths beneath `$HOME`.

## Preconditions

- Both repositories are clean or all pre-existing edits are understood.
- Both tracking branches have been updated with `git pull --ff-only` and verified at `0 0` against upstream.
- The dotfile README explicitly declares the package and its Stow target layout.
- The consuming application and GNU Stow are installed.

## Safe migration

1. Inspect the upstream diff first. A deliberate ownership move often deletes files from the old repository and adds equivalent files beneath a package such as `opencode/.config/opencode/` in the dotfile repository.
2. Inventory destination paths using `lexists`, `islink`, `readlink`, and `realpath`. A link to a deleted old source is still present even though ordinary `exists` checks return false.
3. Read any existing regular config file before replacing it. Remove it only when its exact content is known to be superseded by the tracked package; otherwise stop for a merge decision.
4. Remove only links whose literal or resolved target matches the old source exactly. Refuse unknown targets.
5. Install the package through Stow rather than recreating its individual links manually:

```sh
stow --dir /path/to/dotfile --target "$HOME" opencode
```

6. Verify every expected destination is a symlink, resolves to the exact package source, and remains readable.

## Consumer-level verification

For OpenCode, filesystem checks are necessary but not sufficient:

```sh
opencode agent list
opencode debug config
```

`agent list` confirms custom agents were discovered. `debug config` confirms the merged JSONC, agent prompts, and selected models that OpenCode actually interpreted.

Do not infer that permission rules are effective merely because an agent appears. Compare the merged effective `permission` field with the source frontmatter. OpenCode's current schema uses singular `permission`; launching subagents is governed by `task`, and editing by `edit`. Unknown or legacy frontmatter such as a plural `permissions` list may survive under provider/options data while the effective `permission` object remains empty.

Treat permission migration as a semantic policy translation, not a field-name substitution. Confirm each role's intended authority before choosing `allow` or `deny`. For example, tiered workers may use `task: deny` to prevent nested delegation, while an independent reviewer that delegates read-only evidence gathering should retain `edit: deny` and explicitly use `task: allow`. Verify the resolved values through both commands after any correction.

## Final proof

- Each repository is still clean and `0 0` against its upstream.
- Every global path resolves to the dotfile package, not the retired repository.
- The application lists the expected custom objects.
- The application's merged config contains the intended model routes and effective permissions.
- Re-running Stow is conflict-free/idempotent when practical.
