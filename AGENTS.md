# Repository Guidelines

## Project Structure & Module Organization

This repository manages home-directory dotfiles with GNU Stow. Each top-level
package mirrors the paths it creates beneath `$HOME`:

- `zsh/` contains `.zshrc`, `.zprofile`, and the tracked Powerlevel10k prompt.
- `nvim/.config/nvim/` contains the LazyVim configuration: entry point
  `init.lua`, core settings in `lua/config/`, plugin specs in `lua/plugins/`,
  and the pinned `lazy-lock.json`.
- Package-specific setup notes live in `zsh/README.md` and `nvim/README.md`.

Keep new files in the package and relative path that Stow should link. For
example, add `nvim/.config/nvim/lua/plugins/git.lua` for a Neovim plugin spec.

## Build, Test, and Development Commands

There is no build system or automated test suite. Validate changes with the
tools that load them:

```sh
stow --dir "$PWD" --target "$HOME" zsh nvim  # create or refresh links
zsh -n zsh/.zshrc                             # check shell syntax
nvim --headless '+LazyHealth' +qa              # inspect Neovim health
stow --delete --dir "$PWD" --target "$HOME" zsh nvim  # remove links
```

Run the Stow command only against the packages you changed when practical.
After Neovim plugin changes, start Neovim and run `:LazyHealth`.

## Coding Style & Naming Conventions

Preserve the existing style: two-space continuation indentation in Zsh, clear
comments for platform-specific behavior, and guarded loads such as
`[[ -r "$file" ]] && source "$file"`. Keep machine-specific values in ignored
`*.local` files. Lua configuration follows LazyVim conventions: lowercase file
names, `snake_case` local variables, and plugin specs under `lua/plugins/`.
Use the existing `nvim/.config/nvim/stylua.toml` when formatting Lua.

## Cross-Platform Compatibility

Changes must remain compatible with both Ubuntu and macOS. Prefer portable
shell features and detect OS- or package-manager-specific paths before using
them—for example, support both `/opt/homebrew` and `/usr/local` for Homebrew.
Do not hard-code a single system's executable locations or assumptions.
When behavior must differ, document the reason and retain a safe fallback for
the other platform.

## Testing Guidelines

Before committing, run syntax or health checks appropriate to every changed
package and manually open an interactive Zsh or Neovim session when altering
startup behavior. For platform-sensitive changes, verify the affected paths or
startup flow on both Ubuntu and macOS. Keep `lazy-lock.json` in sync when
deliberately updating plugins; avoid incidental lockfile churn.

## Commit & Pull Request Guidelines

Recent commits use short, imperative, sentence-style subjects (for example,
`Improve cross-platform zsh setup` and `add nvim config`). Keep each commit
focused on one package or concern. Pull requests should explain the user-facing
configuration change, list validation performed, link related issues when
available, and include screenshots only for visible Neovim UI changes.
