# dotfile

Personal configuration files managed from one repository and loaded through
symbolic links.

## Packages

- `zsh`: lightweight Oh My Zsh configuration, aliases, functions, and options
- `nvim`: LazyVim-based Neovim configuration for lightweight file editing

Each package mirrors its destination beneath `$HOME`. Machine-specific values
and secrets should remain in local override files and must not be committed.

Install GNU Stow on Ubuntu, then link both packages into `$HOME`:

```sh
sudo apt install stow
stow --dir /path/to/dotfile --target "$HOME" zsh nvim
```

Run the same `stow` command after adding a package or changing its directory
layout. To remove the managed links without deleting the source files:

```sh
stow --delete --dir /path/to/dotfile --target "$HOME" zsh nvim
```
