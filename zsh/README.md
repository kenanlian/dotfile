# Zsh configuration

The files mirror their locations under `$HOME` and can be managed manually or
with GNU Stow. Oh My Zsh itself is installed at `~/.oh-my-zsh` and is not
vendored in this repository.

Powerlevel10k, zsh-autosuggestions, and zsh-syntax-highlighting are detected
from the Oh My Zsh custom directory on Ubuntu or macOS. Homebrew installations
under `/opt/homebrew` or `/usr/local` are also detected on macOS.

Put machine-specific settings and secrets in `~/.zshrc.local`; that file is not
managed here.
