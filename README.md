# dotfile

Personal configuration files managed from one repository and loaded through
symbolic links.

## Packages

- `zsh`: lightweight Oh My Zsh configuration, aliases, functions, and options
- `nvim`: LazyVim-based Neovim configuration for lightweight file editing

Each package mirrors its destination beneath `$HOME`. Machine-specific values
and secrets should remain in local override files and must not be committed.

Install a package with GNU Stow, for example:

```sh
stow --target "$HOME" nvim
```
