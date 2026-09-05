# Kanban Pilot Drills

Use a named temporary Board with an absolute disposable Git workdir. Keep the default Board empty and preserve evidence before archiving.

## Lifecycle and task-scoped tools

Create a no-side-effect worker card that must call `kanban_show`, emit an explicit `kanban_heartbeat`, and finish with `kanban_complete`. Read back task events and run metadata; a final summary alone is not proof.

## Task-pinned fail-closed Skill

Pin the real runner Skill to a card that intentionally omits its structured contract. Expected result: `blocked` with the runner's typed reason before any external process starts. This proves both Skill routing and fail-closed validation without inventing a contract that could accidentally launch a Relay.

## Per-board concurrency

Create two ready cards for the same profile and run one `dispatch --max 2`. Require exactly one spawn and one `skipped_per_profile_capped` entry with `current: 1`. Then let both terminate before the next drill.

## Terminal-tool protocol enforcement

Use a bounded card that intentionally returns final text without `kanban_complete`/`kanban_block`. Verify the worker log shows terminal-tool nudges; after the retry limit, verify the run outcome and `gave_up` event. Board status alone may say `crashed`, so the log is the decisive protocol evidence.

## Reclaim and retry

Start a card that heartbeats and enters a harmless bounded wait. After the explicit heartbeat, reclaim it with a reason. Verify the reclaim event reports local termination fields, append a recovery comment, dispatch again, and require a new run ID that reads the comment and completes. Preserve both run records.

## Notification delivery

Subscribe a disposable card with passive `notify`, complete it, and wait for the subscription cursor to advance. Do not equate cursor advancement with user-visible delivery: read back the target platform's message history and verify the exact task ID, board, status, and concise summary. Avoid using the notification text as workflow authority.

## Cleanup

Confirm no ready/running tasks remain, copy evidence out of the Board DB, archive the drill cards (do not purge), and re-check default-Board isolation and config read-back.
