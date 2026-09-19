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

### Per-Stage agent routing (`stage_agents`)

Optional. When absent, every Stage keeps the legacy behavior: the profile
spec from `agents[profile]` with adapter `pi`. When set, `stage_agents` keys
the exact Harness Stage — not the profile — so `implement` and
`direct_implement` (which share the implementer profile) can run different
adapters:

```yaml
stage_agents:
  plan:
    adapter: cursor
    model: claude-opus-5-thinking-high
    thinking: high
  plan_review:
    adapter: pi
    model: zai-coding-cn/glm-5.3
    thinking: high
  implement:
    adapter: cursor
    model: gpt-5.6-sol-high
    thinking: high
  execute_review:
    adapter: pi
    model: zai-coding-cn/glm-5.3
    thinking: high
  direct_implement:
    adapter: cursor
    model: cursor-grok-4.6-high
    thinking: high
```

Rules:

- Allowed keys: `plan | plan_review | implement | execute_review | direct_implement`;
  `adapter`: `pi | cursor`; each entry needs a non-empty `model` and a legal
  `thinking` level.
- Precedence per Job: frozen lineage binding (see below) > `stage_agents[stage]` >
  legacy `agents[STAGE_PROFILES[stage]]` (adapter defaults to `pi` when the
  legacy spec omits it).
- **Lineage freezing:** the first Job created for a Stage in a workflow run
  freezes `{adapter, model, thinking}` into the Manifest (`stageAgents`).
  Later transport retries, business rework, and exact-session resume for that
  Stage reuse the frozen selection — editing config mid-run never reroutes an
  in-flight lineage, including after controller restarts.
- A Stage lineage never switches adapters automatically. To change the
  adapter for a Stage, start a new workflow/card lineage; a Cursor session is
  never handed to Pi and vice versa. Reviewer Stages always run fresh sessions;
  planner/implementer rework resumes the Stage adapter's exact session.
- Result consumption requires `result.adapter == job.agent.adapter` on top of
  the existing job hash, artifact, session, and verdict binding checks.

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
