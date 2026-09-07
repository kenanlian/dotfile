# Kanban Handoff Integrity

Use this reference when an engineering step completes with structured result metadata, native file attachments, or external-guard Relay evidence.

## Completion payload shape

Keep two artifact channels separate:

```python
kanban_complete(
    summary="concise human handoff",
    metadata={
        "stage_result": validated_development_stage_result,
        "verification_notes": {...},
    },
    artifacts=["/absolute/evidence.json", "/absolute/screenshot.png"],
)
```

Why: the Kanban completion layer records native attachment paths under the run metadata's top-level `artifacts` key. Passing a bare structured result as metadata creates a key collision and can turn structured records into path strings. After completion, call `kanban_show`/`runs`, extract the nested metadata key, and validate it again. Validate the native attachment list independently.

## Terminal Relay truth

A completed-looking Relay is incomplete if the process is live or the terminal result is malformed or missing. This applies both to guard-owned write-mode attempts and native-review-owned read-only attempts. The terminal contract is the adapter's `delegate-relay.result.v1`:

- expected schema and status; `exitCode=0` for success;
- process exit truth — a result-looking file while the process remains alive is not yet a stable terminal handoff;
- the pi relay reports `sessionId`; record it through the guard's `record-terminal` so exact-session rework is possible;
- relays emit a normalized `unavailable` status with `sourceStatus` when the Coding Agent binary is missing;
- relays never commit; the Worker performs the Card-trailer landing rule.

Only `status: completed` with `exitCode: 0` may advance a stage. `failed`, `timeout`, `aborted`, and `unavailable` are terminal evidence but not successful handoffs. Missing stage-required fields also fail closed. An unexpected Pi-created commit/push is an authority-boundary violation that blocks attribution; it is not silently accepted as Worker landing.

A streamed fragment, progress display, or self-report without the adapter's terminal result contract is not completion.

## Load-bearing paths only

Validate only the paths the guard itself depends on:

- the canonical `external-execution.json` state path;
- the current attempt's `out_dir` and `result_path`;
- the accepted planning artifact when the operation is `planning`.

Do not build generic artifact manifests or hash-validate every declared file in the MVP. Final deliverables ride native Kanban attachments (`artifacts=[]` on `kanban_complete`), which the completion layer copies to durable per-task storage and uploads with the terminal notification.

## Acceptance checklist

- [ ] Process exited and `delegate-relay.result.v1` validates (schema, status, exitCode).
- [ ] Terminal session ID recorded via `record-terminal` when present.
- [ ] Load-bearing paths exist and are readable.
- [ ] Deliverables attached through native `kanban_complete` artifacts, not custom manifests.
- [ ] Any malformed/missing terminal evidence blocks the Card instead of proceeding.
