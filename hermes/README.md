# Hermes text assets (stow package `hermes`)

Stows to `~/.hermes/` (default profile) and `~/.hermes/profiles/executor/`
(小龙). Managed via file-level symlinks for single files and directory-level
symlinks per custom skill:

- `SOUL.md` (both profiles), `memories/MEMORY.md` + `USER.md` (both profiles)
- `scripts/feishu.py`, `scripts/development_external_guard.py`
- focused workflow tests under `tests/`
- standalone Harness plugin `plugins/development-workflow/` (`devflow_*` tools + safety hook)
- self-authored/overridden skills under `skills/<category>/<name>/`
- `profiles/executor/skills/devops/feishu-messaging/`

## Apply / refresh

```sh
stow --dir "$PWD" --target "$HOME" hermes
```

## Development workflow Harness

Hermes Kanban remains the sole lifecycle control plane: statuses, runs, claims,
heartbeats, stale reclaim, retries, dependencies, native review lane, handoff,
and notifications are not copied. The standalone Development Workflow Harness
reads those facts, derives Origin/Implement/Review/non-owning role, validates
`development-stage.v2` contracts and evidence, and performs managed creation,
finalization, Relay commissioning, UI leases, implementation handoff, and review
verdicts through `devflow_*` tools. A `pre_tool_call` hook blocks known bypasses
and non-owning mutations without changing unrelated Hermes behavior.

The fail-closed external guard (`scripts/development_external_guard.py`) owns only
write-mode Relay attempt/session/result plus immutable Git baseline and landing
lineage. Its canonical `development-external-execution.v2` state is
`~/Secret-Projects/development-artifacts/<board>/tasks/<card-id>/external-execution.json`;
v1 migrates losslessly on the first exclusive managed write. Ambiguous state
(`uncertain`) blocks and is never automatically reset or retried.

There is no Goal Mode, auto-decompose, per-Card Cron, monitor, generic workflow
DSL, duplicate phase database, or Hermes Core patch. Execute review is one fresh
read-only `review-execute-candidate` Relay with separate Patch and Plan
Conformance gates. Required UI acceptance is performed once by the Implement
Worker against the frozen candidate under a run-bound UI lease; review validates
the evidence instead of driving the renderer again. Policy lives in
`development-orchestrator`; mechanics live in `hermes-kanban-workflows`.

## User plugin compatibility

`plugins/development-workflow/` is stowed to
`~/.hermes/plugins/development-workflow` and enabled with
`hermes plugins enable development-workflow`. All version-coupled Hermes access
is concentrated in its `hermes_adapter.py`; the plugin does not patch Core or
duplicate native state machines. Mutating Devflow tools fail closed when a
required API capability is absent, while read-only inspect returns diagnostics
when possible. Rerun focused tests plus a temporary-`HERMES_HOME` real plugin
load after each Hermes update.

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
