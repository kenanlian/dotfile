# Kanban Mechanics — Verified Evidence Bank (Hermes v0.20.6, 2026.8.27, local ac6c8028)

Verified 2026-09-01 against live source, CLI, and official docs. Re-verify after `hermes update` (upstream was already 658 commits ahead; Kanban is the most actively patched subsystem — issue refs below like #38696 are recent).

## Enablement & Tool Gating

- `kanban` is NOT in `CONFIGURABLE_TOOLSETS` (`hermes_cli/tools_config.py`); `hermes tools list` omits it and `hermes tools enable kanban` prints `Unknown toolset 'kanban'` (validation at `tools_disable_enable_command`).
- Real gate: `tools/kanban_tools.py::_profile_has_kanban_toolset()` → `"kanban" in cfg.get("toolsets", [])` (top-level list; default `["hermes-cli"]` in `config_defaults.py`).
- `hermes config set` YAML-parses list/mapping values (`_looks_structured_value`), so `hermes config set toolsets '["hermes-cli", "kanban"]'` writes a real list.
- Worker tools auto-load when `HERMES_KANBAN_TASK` + dispatcher-owned; orchestrator tools (`kanban_list`, `kanban_unblock`) additionally hidden from task-scoped workers; delegate_task children are refused lifecycle mutations.
- Official docs confirm: "orchestrator profiles that enable `kanban` in their toolsets config"; recommended orchestrator restriction example `(kanban, gateway, memory)`.

## Dispatcher Topology

- Board DB resolution (`kanban_db_path`): `HERMES_KANBAN_DB` env → `HERMES_KANBAN_BOARD`/current symlink → `<home>/kanban.db` / `<home>/kanban/boards/<slug>/kanban.db`. Boards are per-HERMES_HOME; executor-profile home had zero kanban files (verified on disk).
- Gateway dispatcher holds a host singleton lock; per-board dispatch tick lock (#35240) makes two dispatchers on one DB safe (loser skips tick).
- Dispatcher spawns `hermes -p <assignee> chat -q ...` injecting `HERMES_KANBAN_DB/BOARD/TASK` ("defense in depth" per source comment), so workers of any profile operate the board-owner's DB.
- Board-observed 2026-09-05 (obsidian-card-workspace): dispatch claims require `ready` + non-null assignee. All 5 cards unassigned → zero dispatcher claims ever; the loop provably runs because a manual claim was stale-`reclaimed` exactly 4h0m34s later (14400s timeout + next tick).
- Manual/interactive claims emit the same `claimed` event as dispatcher claims; distinguish via the run row — dispatcher spawns carry `worker_pid`/`claim_lock`, while run rows written by terminal tool calls (complete/review-request) from unclaimed contexts have empty pid/lock (all 7 runs on that board).
- Parent-gated promotion is same-second with the parent's `completed` write, not tick-driven: 3/3 child `promoted` events share the exact timestamp of the parent completion.
- Verified 2026-09-05 (`hermes_cli/kanban_db.py` ~10830): full cmd = `-p <assignee> --cli --accept-hooks [--skills X]… [-m model] [--provider p] [--toolsets t1,t2] chat -q <prompt>`, plus `-Q` for goal-mode (without it the worker takes one turn, exits rc=0 → "protocol violation"; incident 2026-06-09 t_d9cbe312). Env adds `HERMES_KANBAN_WORKSPACES_ROOT` and `HERMES_PROFILE` (comment attribution); `HERMES_TUI` popped. Worker stdout redirects to a per-task log under `<board-root>/logs/` (`hermes kanban log`) — a worker has NO platform/chat binding, so its prose never reaches the user's chat; only lifecycle notifications and card comments do.

## Concurrency Semantics

- `max_in_progress_per_profile` (#21582): counted by `SELECT assignee, COUNT(*) FROM tasks WHERE status='running' GROUP BY assignee` on the CURRENT board connection → per-board scope.
- `max_in_progress` (#33488/OOF-30): host-wide; `count_running_tasks_other_boards()` sums every other board's running rows. Unset → memory-derived (MemTotal/512MiB clamp [2,8]; macOS → no cap).
- Board-scoped caps compose: per-profile cap 1 + global 2 still allows 2 workers of one profile across 2 boards.

## Heartbeat / Reclaim

- Auto bridge (#31752): `_touch_activity` → board `last_heartbeat_at`, rate-limited 1 write/60s, no-op outside dispatcher workers; explicit `kanban_heartbeat` still available for notes/long-op pre-emption.
- `dispatch_stale_timeout_seconds` default 14400 (4h); stale reclaim SIGTERMs host-local worker, resets to ready, does NOT tick failure counter.
- Long external waits: bounded slices (5–15 min) keep the agent loop ticking; a single multi-hour blocking call risks stale reclaim.

## Lifecycle Primitives (CLI-verified)

- `create`: `--idempotency-key` (returns existing non-archived task id), `--parent` (repeatable), `--workspace scratch|worktree|worktree:<p>|dir:<p>`, `--skill` (repeatable), `--model/--provider`, `--max-runtime`, `--max-retries`, `--goal/--goal-max-turns`, `--initial-status {blocked,running}`.
- `block --kind`: `dependency` waits in todo + auto-promotes when parents done (native rework-graph primitive); `needs_input`/`capability` → human; repeated same-kind re-blocks → triage (`BLOCK_RECURRENCE_LIMIT` default 2, counter survives unblock, resets on complete).
- `unblock` restores review/ready/todo by parent gating; never routes to triage directly.
- Circuit breaker: `gave_up` after consecutive non-success attempts; limit resolves task `max_retries` → `kanban.failure_limit` (default 2) → built-in. Respawn guard defers on `blocker_auth`/`recent_success`/`active_pr`.
- Goal mode: judge gates BOTH `kanban_complete` (#38367) and `kanban_block` (#38696); no assignee/skill/stage switching — unsuitable as a stage-runner primitive.

## Handoff Surfaces

- `kanban_show`: task (body/result/run ids/workspace/model override), parents, children, comments, last 50 events, runs[] with `metadata`, plus pre-formatted `worker_context`.
- `kanban_complete(summary|result, metadata dict, artifacts[], created_cards[])`: summary/result/metadata force-redacted; artifacts merged into `metadata.artifacts`, copied to durable per-task attachment storage, uploaded as native attachments in completion notifications; missing declared scratch artifact keeps task in-flight.
- `_stamp_worker_session_metadata` auto-adds worker session identity to completion metadata.
- Comment injection: comments added after run start are steered into the running worker (watermarked, skips own-author), so a human can PASS/FAIL a running acceptance worker via task comment.
- Creator wake: `kanban.auto_subscribe_on_create: true` subscribes the creating gateway session to completion+block events.

## Review Lane & Triage

- `kanban.review_dispatch: true` (default) auto-claims `review`-column tasks and spawns the assignee with bundled `sdlc-review` skill.
- `kanban.auto_decompose: true` (default) + `auto_decompose_per_tick: 3`: triage cards get aux-LLM decomposition every tick.
- `request-review` / `request-changes` / `reopen-review` CLI + `kanban_request_review`/`kanban_request_changes` tools form the native same-card review loop — distinct from any in-card external review protocol.

## Dead-but-Present Metadata

- `tasks.workflow_template_id`, `tasks.current_step_key` columns exist (with migration), surfaced in list/dashboard filters; dispatcher does not route on them; `create` exposes no write flag. Forward-compatible only.

## Cron Delivery Envelope (verified 2026-09-05, `cron/scheduler.py::_deliver_result`)

- Envelope is hardcoded Python at delivery time: `Cronjob Response: {task_name}\n(job_id: {id})\n---\n\n{content}\n\nTo stop or manage this job…` — the model produces only `{content}`; identity labeling never depends on model compliance.
- `cron.wrap_response` (default true) toggles the whole envelope on/off; no custom template exists. Deterministic labels must ride the job NAME, which is interpolated verbatim (e.g. `[monitor] t_xxx development-monitor`).
- Envelope text is load-bearing: the yuanbao adapter branches on `content.startswith("Cronjob Response: ")`.
- Chat-side lane identity (observed 2026-09-05, t_46522855): monitor reports arrive enveloped (session ids prefixed `cron_`); dispatcher-worker prose never reaches chat (stdout → `<board-root>/logs/`); a quote-reply to an enveloped cron message is delivered to the interactive session, not the cron session — never treat it as resuming the cron worker.

## Old-Asset Baseline (this machine)

- Dev-monitoring suite: `~/.hermes/tests/test_development_monitor_state.py` + `test_development_resume.py` — slim `development-monitor.v2` (one monotonic `generation`, silent healthy RUNNING, historical `--resume --check` only).
