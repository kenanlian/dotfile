# dotfile

Personal configuration files managed from one repository and loaded through
symbolic links.

## Packages

- `zsh`: lightweight Oh My Zsh configuration, aliases, functions, and options

Each package mirrors its destination beneath `$HOME`. Machine-specific values
and secrets should remain in local override files and must not be committed.
