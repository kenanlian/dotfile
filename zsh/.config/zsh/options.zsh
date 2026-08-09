# Comfortable interactive behavior.
setopt auto_cd auto_pushd pushd_ignore_dups interactive_comments
unsetopt beep

# Make completion matching forgiving while keeping Oh My Zsh's cached compinit.
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}' 'r:|=*' 'l:|=* r:|=*'
zstyle ':completion:*' menu select

# BSD `ls` (macOS) reads these variables. GNU `ls` on Linux uses LS_COLORS,
# which is initialized by Oh My Zsh when available.
if [[ "$OSTYPE" == darwin* ]]; then
  export CLICOLOR=1
  export LSCOLORS='Gxfxcxdxbxegedabagacad'
fi
