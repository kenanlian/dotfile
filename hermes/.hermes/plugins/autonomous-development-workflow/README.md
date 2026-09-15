# Autonomous development workflow

Out-of-tree Hermes plugin that runs a durable development workflow **outside**
Kanban: Manifest, Job, Result, Artifact, and repo lease live in the plugin
Store. Hermes Kanban remains the only Worker/run/lane authority. The plugin
never writes `kanban.db` and never starts its own Dispatcher.

Canonical source: `hermes/.hermes/plugins/autonomous-development-workflow/` in
this dotfiles repo. Stow it with the `hermes` package. Do not copy runtime
state into the plugin directory.

## What this milestone did and did not do

This tree includes two allowlisted templates (`autonomous-development.v1` / `--flow full`
and `direct-implementation.v1` / `--flow direct`), typed product acceptance for the
full template, the bypass guard, mock-harness smoke, and the `autodev` CLI
(`status` / `doctor` / `reconcile` / `abandon`).

**Profile integration and a real Dispatcher end-to-end pass are not done
here.** A coordinator will create the isolated Worker Profile, enable the
plugin on control and Worker profiles, and run a live Dispatcher pass later.
Do not treat plugin unit/smoke tests as that E2E.

## Enable

After Profile setup (coordinator step, not this milestone):

```bash
# Control profile: plugin + CLI, no model-facing toolset
hermes plugins enable autonomous-development-workflow --no-allow-tool-override
hermes tools disable autonomous_development_workflow --platform cli

# Worker profile: same plugin source, model-facing tools enabled
hermes -p autodev plugins enable autonomous-development-workflow --no-allow-tool-override
hermes -p autodev tools enable autonomous_development_workflow --platform cli
```

Both profiles must share the same absolute `state_root` and
`harness_command` argv. Set those through Hermes plugin config, not by editing
`config.yaml` by hand. Required config:

| Key | Meaning |
| --- | --- |
| `state_root` | Absolute Store directory (Manifest/Job/Artifact/lease SQLite + files) |
| `harness_command` | Non-empty argv for the coding-agent harness (`run --job … --out-dir …`) |
| `profile` | Worker profile name used as Kanban assignee (default `autodev`) |
| `main_branch` | Required clean branch at enqueue (default `main`) |

See [references/operations.md](references/operations.md) for enqueue, status,
human unblock/abandon, Hermes-upgrade checks, harness-failure recovery, and
unsupported work.

## Worker tools

Manifest-bound Dispatcher Workers may call:

- `autodev_workflow_status`
- `autodev_workflow_advance`
- `autodev_workflow_submit_acceptance` (full template only; rejected for `direct-implementation.v1`)

Follow `skills/autonomous-development-workflow/SKILL.md`. Ordinary sessions
without a Manifest are ignored by the `pre_tool_call` guard. `abandon` is
operator CLI only; it is not a model tool.

## Tests

```bash
PY=/Users/kenan/.hermes/hermes-agent/venv/bin/python3
$PY -m unittest discover \
  -s hermes/.hermes/plugins/autonomous-development-workflow/tests \
  -p 'test_*.py'
```
