# Comfortable interactive behavior.
setopt auto_cd auto_pushd pushd_ignore_dups interactive_comments
unsetopt beep

# Make completion matching forgiving while keeping Oh My Zsh's cached compinit.
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}' 'r:|=*' 'l:|=* r:|=*'
zstyle ':completion:*' menu select

# Use terminal colors for supported BSD/macOS tools.
export CLICOLOR=1
export LSCOLORS='Gxfxcxdxbxegedabagacad'
