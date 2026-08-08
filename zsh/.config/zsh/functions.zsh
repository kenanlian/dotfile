# Create a directory and enter it.
mkcd() {
  [[ $# -eq 1 ]] || { print -u2 'usage: mkcd <directory>'; return 2; }
  mkdir -p -- "$1" && cd -- "$1"
}

# Extract common archive formats with one command.
extract() {
  [[ -f "$1" ]] || { print -u2 "extract: file not found: $1"; return 1; }
  case "$1" in
    *.tar.bz2|*.tbz2) tar xjf "$1" ;;
    *.tar.gz|*.tgz)   tar xzf "$1" ;;
    *.tar.xz|*.txz)   tar xJf "$1" ;;
    *.tar)            tar xf "$1" ;;
    *.zip)            unzip "$1" ;;
    *.gz)             gunzip "$1" ;;
    *.bz2)            bunzip2 "$1" ;;
    *.7z)             7z x "$1" ;;
    *) print -u2 "extract: unsupported archive: $1"; return 2 ;;
  esac
}
