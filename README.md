# dotfile

Personal configuration files managed from one repository and loaded through
GNU Stow symbolic links.

## Packages

- `zsh`: lightweight Oh My Zsh configuration, aliases, functions, and options
- `nvim`: LazyVim-based Neovim configuration for lightweight file editing
- `opencode`: OpenCode user configuration and delegated-agent definitions
- `pi`: Pi coding-agent `delegate_agent` routing (`~/.pi/agent/delegate-agent.json`)

Each package mirrors its destination beneath `$HOME`. Machine-specific values
and secrets should remain in local override files and must not be committed.

Install GNU Stow on Ubuntu, then link the packages you want into `$HOME`:

```sh
sudo apt install stow
stow --dir /path/to/dotfile --target "$HOME" zsh nvim opencode pi
```

Run the same `stow` command after adding a package or changing its directory
layout. To remove the managed links without deleting the source files:

```sh
stow --delete --dir /path/to/dotfile --target "$HOME" zsh nvim opencode pi
```

The OpenCode package owns concrete local provider/model routing. Cross-platform
delegation semantics remain in the separate `agent_skills` repository.
