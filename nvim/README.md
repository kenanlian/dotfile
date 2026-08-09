# Neovim configuration

This package mirrors `~/.config/nvim` and is managed with GNU Stow:

```sh
brew install neovim ripgrep fd tree-sitter-cli stow
stow --dir /path/to/dotfile --target "$HOME" nvim
```

The configuration uses LazyVim with the One Dark theme. It is deliberately
scoped to the current working directory and disables automatic session restore,
making it suitable for single files and small groups of unrelated files.

Useful mappings (the leader key is Space):

- `<leader>ff`: find a file below the current working directory
- `<leader>sg`: search text below the current working directory
- `<leader>,`: switch between open buffers
- `<leader>e`: toggle the file explorer
- `<leader>fn`: open a new unnamed file
- `<leader>-` / `<leader>|`: horizontal / vertical split
- `<C-h/j/k/l>`: move between windows
- `<leader>bd`: close the current buffer
- `Cmd-s`: save on macOS terminals that pass the key through

Run `:LazyHealth` after plugin updates to check the installation.
