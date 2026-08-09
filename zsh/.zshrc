# Oh My Zsh lives outside this repository; this file only keeps its settings.
export ZSH="$HOME/.oh-my-zsh"

# Powerlevel10k is loaded from Homebrew below.
ZSH_THEME=""

# Show inline suggestions from shell history, falling back to command completion.
plugins=(git)
ZSH_AUTOSUGGEST_STRATEGY=(history completion)

# Check for framework updates occasionally without interrupting shell startup.
zstyle ':omz:update' mode reminder
zstyle ':omz:update' frequency 14

# History shared by interactive shells.
HISTFILE="$HOME/.zsh_history"
HISTSIZE=50000
SAVEHIST=10000
setopt append_history share_history hist_ignore_dups hist_ignore_space

source "$ZSH/oh-my-zsh.sh"

# Load Homebrew-installed interactive shell enhancements on either Apple Silicon
# or Intel macOS.
for brew_prefix in /opt/homebrew /usr/local; do
  if [[ -r "$brew_prefix/share/powerlevel10k/powerlevel10k.zsh-theme" ]]; then
    source "$brew_prefix/share/powerlevel10k/powerlevel10k.zsh-theme"
  fi
  if [[ -r "$brew_prefix/share/zsh-autosuggestions/zsh-autosuggestions.zsh" ]]; then
    source "$brew_prefix/share/zsh-autosuggestions/zsh-autosuggestions.zsh"
  fi
done
unset brew_prefix

# Powerlevel10k configuration is tracked with the rest of the shell setup.
[[ -r "$HOME/.p10k.zsh" ]] && source "$HOME/.p10k.zsh"

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
