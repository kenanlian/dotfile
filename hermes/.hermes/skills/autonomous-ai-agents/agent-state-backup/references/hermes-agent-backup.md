# Hermes Agent: Verified Backup and Migration Notes

## Authoritative commands

- `hermes backup [-o OUTPUT] [--quick]` creates a ZIP from the current Hermes home. Its CLI help describes full backups as configuration, skills, sessions, and data while excluding the Hermes codebase.
- `hermes import [--force] ZIPFILE` overlays a previously created ZIP into the current Hermes home.
- `hermes profile export PROFILE` and `hermes profile import ARCHIVE` are profile-sharing/move helpers, but profile export deliberately strips API keys. Do not use it as the only disaster-recovery artifact when credentials and full history matter.

## Relevant state

The default profile is `~/.hermes`; named profiles have independent homes under `~/.hermes/profiles/<name>/`. Per profile, durable state commonly includes:

- `config.yaml` — nonsecret settings
- `.env` — API keys and platform secrets
- `auth.json` — OAuth/credential-pool state
- `SOUL.md` — persistent persona
- `memories/MEMORY.md` and `memories/USER.md` — curated long-term memory
- `skills/`, `cron/`, `plugins/`, `hooks/`, `scripts/`, skins/layout assets
- `state.db` plus `sessions/` — conversation/session data and search state

## Why use `hermes backup`

Hermes’ backup code creates consistent SQLite snapshots and skips live database WAL/shared-memory sidecars. It also excludes regenerable/risky data including the `hermes-agent` source checkout, dependencies, caches, browser profiles, runtime PIDs/locks, old backup folders, checkpoints, and state snapshots. This avoids recursive archives and inconsistent copies from a running gateway.

## Quick vs full and updates

`hermes backup --quick` is a small critical-state snapshot (documented as config, state DB, `.env`, auth, and cron). It is useful before risky work but is not sufficient when the user requires skills/memories/full migration fidelity.

For update-time local safety, configure through the CLI rather than editing YAML directly:

```bash
hermes config set updates.pre_update_backup full
hermes config set updates.backup_keep 5
```

These local pre-update archives are a rollback aid, not an off-device backup.

## Restore drill pattern

After decrypting a full backup, restore it into a separate temporary home, for example:

```bash
HERMES_HOME=/private/var/tmp/hermes-restore-drill/home \
  hermes import /private/var/tmp/hermes-restore-drill/hermes-full.zip
```

Then inspect the isolated home with profile/session/skills commands. Do not start a gateway from the drill profile. Test actual decrypt + import before relying on the archive.

## Profile scope

Before assuming one archive covers every agent, enumerate named profiles and verify archive contents or run a full backup explicitly under each profile (`hermes -p <name> backup`). Named profiles have their own config, memory, skills, sessions, and credentials.
