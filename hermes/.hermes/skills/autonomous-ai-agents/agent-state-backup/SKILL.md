---
name: agent-state-backup
description: "Use when backing up or migrating agent state securely."
version: 1.0.0
platforms: [macos, linux, windows]
metadata:
  hermes:
    tags: [backup, disaster-recovery, migration, secrets, sessions, skills, memory]
---

# Agent State Backup & Migration

## When to Use

Use when a user needs to back up, transfer, version, restore, or disaster-recover a local AI-agent setup: configuration, persona, persistent memory, skills, sessions, automation, plugins, or credentials.

Use the agent-specific documentation and CLI as the authority for exact paths and commands. Load `references/hermes-agent-backup.md` for verified Hermes Agent details.

## Core Model: Separate Three Kinds of Data

Do not design one storage mechanism for everything.

1. **Disaster-recovery archive** — faithful, point-in-time recovery of all irreplaceable state, including secrets and conversation data when the user wants them. It must be encrypted and kept off-device.
2. **Versioned intent** — human-reviewable configuration, persona, custom skills, cron definitions, scripts, and plugins. Keep this in a private Git repository so changes have diffs and history.
3. **Secret source of truth** — API keys, tokens, recovery keys, and service credentials. Keep these in a password manager or dedicated secret manager, independent of the backup archive.

A Git mirror is not a substitute for a recovery archive; an encrypted binary archive is not a good substitute for readable configuration history.

## Discovery Before Designing

1. Identify the active agent home/profile and enumerate any named profiles.
2. Consult the current official documentation and `--help` for backup/export/import commands; do not infer feature behavior from directory names.
3. Inventory durable state (config, persona, memory, skills, scheduled jobs, plugins, session database/transcripts, credentials) separately from regenerable state (source checkout, dependencies, caches, locks, PID files).
4. Establish the threat model: laptop loss, disk failure, mistaken deletion, provider-token expiry, accidental secret publication, and migration to a new computer.
5. Determine whether the source disk and every cloud/off-device target are encrypted. If local disk encryption is absent, call out the temporary-plaintext risk explicitly.
6. Confirm that the planned destination is genuinely independent of the source device and has an owner-accessible recovery path.

## Recommended Architecture

Use a 3-2-1-inspired arrangement:

- **Primary:** periodic full agent-native backup.
- **Encryption:** encrypt the archive *before* it reaches an ordinary sync folder or cloud provider. Use public-key encryption where automated backup needs only a public recipient; keep the private recovery identity out of scripts and launchers.
- **Off-device copy:** encrypted cloud storage and, when feasible, a separately stored encrypted external drive.
- **Version mirror:** private Git repository for nonsecret intent assets.
- **Local update safety net:** enable the agent's own pre-update backup mechanism when available, but never call it off-device disaster recovery.
- **Recovery drill:** restore an archive into an isolated home/profile at least quarterly.

## Automation Rules

- Prefer the agent's native backup command over `cp`, Finder drag-and-drop, or a raw `rsync` of a live home directory. Agent homes often contain SQLite databases in WAL mode; a raw copy can be internally inconsistent.
- Stage any temporary unencrypted archive in a permission-restricted temporary directory, clean it with traps on every exit path, and keep its lifetime short.
- A scheduled encryption job should need only a public encryption recipient. It must never contain an encryption private key, password-manager master password, or API key in its script, plist/service unit, logs, or Git repository.
- Use absolute executable paths and explicit environment variables in scheduled jobs; launchd/systemd do not inherit an interactive shell environment.
- Write nonsecret structured logs and failure notifications. Do not log archive contents, environment variables, keys, or tokens.
- Apply a stated retention policy and delete archive/manifest pairs together. Avoid recursive backup directories.

## Version-Control Rules

A private Git repository may include:

- nonsecret configuration
- persona/instructions
- custom or modified skills
- cron definitions
- plugins, hooks, scripts, skins, layouts, and templates
- automation source and recovery runbook

Never commit unless deliberately encrypted and reviewed:

- `.env` / secret files
- OAuth stores or auth tokens
- encryption private keys
- memory files containing personal or confidential information
- session databases/transcripts
- logs, caches, browser profiles, lock/PID/runtime files

Keep the Git mirror outside the live agent home. It should stage/export selected files rather than turn the runtime directory itself into a repository.

## Recovery Verification

A backup is not complete until a restore drill proves it.

1. Choose a recent archive and verify its manifest/checksum.
2. Retrieve the decryption identity from its independent recovery location only for the attended drill.
3. Decrypt into a restricted temporary directory; validate the archive format.
4. Import/restore into a new isolated agent home, never the production home.
5. Verify the identity/config, persistent-memory files, installed skills, scheduled jobs, session list/search, and plugin state appropriate to the agent.
6. Do not start production-facing gateways/bots from the drill home.
7. Remove decrypted drill material and record only the archive ID/date and pass/fail result.

## Migration Runbook

On the replacement computer:

1. Install a compatible/current agent version.
2. Retrieve and decrypt the off-device archive.
3. Import the archive into the target home; only use force-overwrite after confirming the target state may be replaced.
4. Run the agent's health/configuration checks.
5. Expect OAuth/device-bound sessions to sometimes require reauthentication even if credential state was archived.
6. Reinstall or re-enable machine-local services (gateway launch agents, system services, local browser integrations) rather than restoring stale PIDs, locks, and runtime state.
7. Verify the new installation before retiring the old device.

## Pitfalls

- **Using an export intended for sharing as a backup:** profile/share exports often strip credentials and sometimes history. Verify their scope; do not assume a successful export is full recovery.
- **Relying on a quick snapshot:** quick/pre-update snapshots can omit skills, memory, histories, or large files. Use full backups for migration and disaster recovery.
- **Uploading raw archives:** a ZIP containing `.env`, auth state, session history, or memory is sensitive even in a private cloud folder. Encrypt it first.
- **No independent recovery key:** an encrypted backup whose only private key remains on the lost laptop is unrecoverable.
- **Skipping the restore drill:** archive creation success proves only that bytes were written, not that the backup can restore.
- **Treating one profile as all profiles:** enumerate profiles and verify scope/contents explicitly when multiple profiles exist.

## Completion Checklist

- [ ] Full backup scope is documented and verified against current CLI/docs.
- [ ] Credentials and private recovery material have an independent secret-manager/home-offline recovery path.
- [ ] Off-device archive is encrypted before sync.
- [ ] Retention, logging, and failure handling are configured.
- [ ] A private Git mirror excludes secrets and runtime/user-data stores.
- [ ] Restore drill passed in an isolated agent home.
- [ ] Migration instructions are documented and machine-local services are re-enabled deliberately.
