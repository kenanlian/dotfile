# Kanban Handoff Integrity

Use this reference when a stage completion carries structured result metadata, native file attachments, or Relay recovery evidence.

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

Why: the Kanban completion layer records native attachment paths under the run metadata's top-level `artifacts` key. Passing a bare `development-stage-result.v1` as metadata creates a key collision and can turn structured artifact records into path strings. After completion, call `kanban_show`/`runs`, extract `metadata.stage_result`, and validate it again. Validate the native attachment list independently.

## Immutable artifact ordering

For Relay-backed stages:

1. Persist the canonical run record atomically as soon as PID/session identity is known; never add non-schema convenience fields.
2. During observation, use PID identity plus result presence only as liveness evidence. A result-looking file while the process remains alive is not yet a stable terminal handoff.
3. Wait for child-process exit and a valid terminal result contract.
4. Ensure build identity and other producer-owned evidence are closed and no later collector will rewrite them.
5. Compute SHA-256 from the exact final paths.
6. Build the stage result from those hashes, read every path back, and validate before `kanban_complete`.
7. Downstream repeats path existence + digest verification before UI behavior acceptance or non-UI handoff closure.

A mismatch is `FAIL`/block, not residual risk. Independently rehashing the product executable does not repair a mismatched parent handoff for `result.json` or build identity; create a new generation with immutable artifacts.

## Live reclaim proof

To prove worker-restart continuity rather than terminal-result recovery, capture immediately before reclaim:

- worker run ID;
- valid canonical run record;
- exact session and child PID/process identity;
- `pid_alive=true`;
- `result_exists=false`;
- timestamp/process listing.

After reclaim, prove the child remains alive and the result is still absent. The replacement worker must load the unchanged run record, attach to the same PID/session/generation, emit heartbeats, and launch no second Relay. Preserve ordering evidence showing reclaim occurred before the terminal result timestamp.

## Acceptance checklist

- [ ] Parent `metadata.stage_result` validates after persistence.
- [ ] Native top-level attachment paths are readable and do not pollute structured artifacts.
- [ ] Every structured artifact path exists and matches its declared digest.
- [ ] Hashes were computed after terminal process exit and remained unchanged through downstream read-back.
- [ ] Any digest mismatch blocks transition, regardless of product behavior.
- [ ] Reclaim drill proves a live child, not merely recovery from an already-finished result.
