# Oh My Zsh lives outside this repository; this file only keeps its settings.
export ZSH="$HOME/.oh-my-zsh"

# A small, readable theme with Git information and no extra runtime dependency.
ZSH_THEME="robbyrussell"

# Keep framework work intentionally small. Add plugins only when they are useful.
plugins=(git)

# Check for framework updates occasionally without interrupting shell startup.
zstyle ':omz:update' mode reminder
zstyle ':omz:update' frequency 14

# History shared by interactive shells.
HISTFILE="$HOME/.zsh_history"
HISTSIZE=50000
SAVEHIST=10000
setopt append_history share_history hist_ignore_dups hist_ignore_space

source "$ZSH/oh-my-zsh.sh"

# User-installed command-line tools.
export PATH="$HOME/.local/bin:$PATH"

ZSH_CONFIG_DIR="$HOME/.config/zsh"
for config_file in aliases functions options; do
  [[ -r "$ZSH_CONFIG_DIR/$config_file.zsh" ]] && source "$ZSH_CONFIG_DIR/$config_file.zsh"
done
unset config_file

# Machine-specific settings and secrets belong here, outside Git.
if [[ -r "$HOME/.zshrc.local" ]]; then
  source "$HOME/.zshrc.local"
fi
