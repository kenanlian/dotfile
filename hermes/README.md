# Hermes text assets (stow package `hermes`)

Stows to `~/.hermes/` (default profile) and `~/.hermes/profiles/executor/`
(小龙). Managed via file-level symlinks for single files and directory-level
symlinks per custom skill:

- `SOUL.md` (both profiles), `memories/MEMORY.md` + `USER.md` (both profiles)
- `scripts/feishu.py`, `scripts/development_external_guard.py`
- focused workflow tests under `tests/`
- standalone Harness plugin `plugins/development-workflow/` (`devflow_*` tools + safety hook)
- remaining legacy custom/overridden skills under `skills/<category>/<name>/`
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
Conformance gates; review relays finish via `submit_plan_review` /
`submit_execute_review` captured into `delegate-relay.result.v1`
`structuredOutput`. Execute-plan required UI is Implement-owned candidate-bound
critical smoke, then Review-owned formal acceptance under a post-dual-gate
lease, then authorized exact-SHA publication. Direct keeps Implement-owned
formal acceptance. The plugin surface is ten `devflow_*` tools. Policy lives in
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

## Default-profile custom skills

The sibling `hermes-skills` checkout is the source for newly created Skills and
the migrated `project-taskflow` and `delegated-development-acceptance` Skills.
Configure `skills.create_dir` in the default profile to point to that checkout's
`skills/` directory; Hermes discovers it directly. Do not add Stow copies or
profile-local copies of these Skills: a same-named profile-local Skill takes
precedence. See the `hermes-skills` repository's `README.md` for setup and
verification.

The remaining legacy skills stay in their existing locations until individually
reviewed. This change does not migrate the executor profile or change bundled
and Hub skill management.
