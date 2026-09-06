# Hermes text assets (stow package `hermes`)

Stows to `~/.hermes/` (default profile) and `~/.hermes/profiles/executor/`
(小龙). Managed via file-level symlinks for single files and directory-level
symlinks per custom skill:

- `SOUL.md` (both profiles), `memories/MEMORY.md` + `USER.md` (both profiles)
- `scripts/feishu.py`, `scripts/development_relay_gate.py`
- user plugin `plugins/development-workflow/` (`kanban_finalize_intent`)
- 23 self-authored skills under `skills/<category>/<name>/`
- `profiles/executor/skills/devops/feishu-messaging/`

## Apply / refresh

```sh
stow --dir "$PWD" --target "$HOME" hermes
```

## User plugin compatibility

`plugins/development-workflow/` is stowed to
`~/.hermes/plugins/development-workflow` and enabled with
`hermes plugins enable development-workflow`. It wraps Hermes' internal
`hermes_cli.kanban_db.specify_triage_task()` API rather than patching Core or
writing SQLite directly. The files survive `hermes update`, but the internal
API is version-coupled: rerun the plugin's focused temporary-`HERMES_HOME`
tests after each Hermes update and adapt the plugin if the API changes.

## Deliberately NOT managed here

- `.env`, `auth.json` — secrets; belong to the encrypted DR archive only
- `state.db`, `sessions/`, `kanban.db`, `logs/`, caches — data, not text
- `config.yaml` — machine-local; DR archive covers it
- Bundled skills (82) — reinstallable; tracked by `.bundled_manifest`

## Known limitations (verified 2026-09-06)

Hermes' session scanner uses `os.walk(followlinks=True)`, so loading,
`skills_list`, and `skill_view` work through symlinks, and memory writes
follow symlinks into this repo (`atomic_replace` resolves links, GitHub
#16743). However `skill_manage` patch/delete resolve skills via
`Path.rglob`, which does not follow symlinked directories:

- **patch / write_file / delete on a symlinked skill fail with "not found"**
  (delete is additionally refused by an explicit symlink guard — it can never
  wipe the repo). Edit these skills with ordinary file tools (`patch`,
  `write_file`) instead, which follow symlinks fine.
- **New skills** created via `skill_manage` land as real dirs in
  `~/.hermes/skills/`. Adopt them:

  ```sh
  mv ~/.hermes/skills/<cat>/<name> hermes/.hermes/skills/<cat>/<name>
  ln -s "../../../Secret-Projects/dotfile/hermes/.hermes/skills/<cat>/<name>" \
     ~/.hermes/skills/<cat>/<name>
  ```
