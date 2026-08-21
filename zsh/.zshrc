# Enable the Powerlevel10k instant prompt when it has already been generated.
# Keep this close to the top of the file.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# Oh My Zsh lives outside this repository; this file only keeps its settings.
export ZSH="$HOME/.oh-my-zsh"
ZSH_CUSTOM="${ZSH_CUSTOM:-$ZSH/custom}"

# Prefer an Oh My Zsh custom installation on Linux or macOS. A Homebrew
# installation is loaded after Oh My Zsh below.
if [[ -r "$ZSH_CUSTOM/themes/powerlevel10k/powerlevel10k.zsh-theme" ]]; then
  ZSH_THEME="powerlevel10k/powerlevel10k"
else
  ZSH_THEME=""
fi
POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true

# Plugins bundled with Oh My Zsh work on both Ubuntu and macOS.
plugins=(git sudo extract z history-substring-search)

# Use custom plugin clones when present. Homebrew variants are loaded below.
[[ -r "$ZSH_CUSTOM/plugins/zsh-autosuggestions/zsh-autosuggestions.plugin.zsh" ]] &&
  plugins+=(zsh-autosuggestions)
[[ -r "$ZSH_CUSTOM/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.plugin.zsh" ]] &&
  plugins+=(zsh-syntax-highlighting)

# Show inline suggestions from shell history, falling back to command completion.
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

# Load Homebrew-installed enhancements on Apple Silicon or Intel macOS when an
# equivalent Oh My Zsh custom installation was not loaded above.
for brew_prefix in /opt/homebrew /usr/local; do
  if [[ "$ZSH_THEME" != "powerlevel10k/powerlevel10k" &&
        -r "$brew_prefix/share/powerlevel10k/powerlevel10k.zsh-theme" ]]; then
    source "$brew_prefix/share/powerlevel10k/powerlevel10k.zsh-theme"
  fi
  if (( ${plugins[(Ie)zsh-autosuggestions]} == 0 )) &&
      [[ -r "$brew_prefix/share/zsh-autosuggestions/zsh-autosuggestions.zsh" ]]; then
    source "$brew_prefix/share/zsh-autosuggestions/zsh-autosuggestions.zsh"
  fi
  if (( ${plugins[(Ie)zsh-syntax-highlighting]} == 0 )) &&
      [[ -r "$brew_prefix/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh" ]]; then
    source "$brew_prefix/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"
  fi
done
unset brew_prefix

# Search history with the up/down arrow keys using the current command prefix.
bindkey '^[[A' history-substring-search-up
bindkey '^[[B' history-substring-search-down
bindkey '^[OA' history-substring-search-up
bindkey '^[OB' history-substring-search-down

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

# Use the local proxy only on macOS.
if [[ "$OSTYPE" == darwin* ]]; then
  export HTTP_PROXY=http://127.0.0.1:8118
  export HTTPS_PROXY=http://127.0.0.1:8118
  export http_proxy="$HTTP_PROXY"
  export https_proxy="$HTTPS_PROXY"
fi
