# Navigation and safer, readable defaults.
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'
alias l='ls -lah'
alias ll='ls -lh'
alias la='ls -A'
alias mkdir='mkdir -p'

# Short Git commands not already supplied by the Oh My Zsh git plugin.
alias gst='git status --short --branch'
alias glog='git log --graph --decorate --oneline --all'

# Clipboard conveniences on macOS and common Linux desktop environments.
if (( $+commands[pbcopy] && $+commands[pbpaste] )); then
  alias copy='pbcopy'
  alias paste='pbpaste'
elif (( $+commands[wl-copy] && $+commands[wl-paste] )); then
  alias copy='wl-copy'
  alias paste='wl-paste'
elif (( $+commands[xclip] )); then
  alias copy='xclip -selection clipboard'
  alias paste='xclip -selection clipboard -out'
fi
