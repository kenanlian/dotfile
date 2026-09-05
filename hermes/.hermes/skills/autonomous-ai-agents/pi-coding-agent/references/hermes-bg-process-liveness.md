# Hermes background-process liveness vs fully-redirected commands

Verified 2026-09-05 via incident forensics (t_46522855 dual-writer incident) + a controlled experiment. Governs ANY long-running command launched through Hermes `terminal(background=true)` whose output is fully redirected to files — pi direct runs, relay runs, monitors.

## Symptom

`process(action="poll")` reports `status:"exited"` seconds after launch while the process is demonstrably alive (same PID visible in `ps` minutes/hours later; its events file keeps growing). Incident signature:

```
status: "exited", uptime_seconds: 7, exit_code: null,
completion_reason: "exited",
output_preview: <zsh startup noise only (setopt / gitstatus errors), zero task output>
```

Acting on that report (same `--session-id` relaunch) caused the dual-writer incident documented in SKILL.md Pitfalls.

## Mechanism (tools/process_registry.py, hermes-agent source)

- Liveness = the stdout PIPE, not the process. A reader thread (`_reader_loop`) select()-polls the pipe; its `finally` block sets `session.exited = True` and `exit_code = process.returncode` **unconditionally** whenever the loop ends (EOF, fd closed, or reader exception).
- With fully-redirected output (`pi … > events.jsonl 2> stderr.txt`), the Hermes pipe's write-end is held only by the intermediate zsh; real task output never crosses the pipe.
- zsh exec-optimizes the final command of a `-c` string: it replaces itself with pi (**same PID** — `ps` COMMAND changes zsh→pi), closing its pipe write-end → kernel EOF → reader ends → `exited=True` while pi is still starting.
- `_reconcile_local_exit` (called from poll) only flips running→exited when `Popen.poll()` returns a code — it never reverses a false exited. Once the false report exists, it is permanent for that session entry.
- **fork-vs-exec is not predictable**: in the control experiment a bare `sleep 60 > f 2> e` forked (report stayed `running`), while the incident's `cd repo && pi … > f 2> e` exec'd. Never assume either; use the defenses below.

## Fingerprint of the false report

1. `status:"exited"` with **`exit_code: null`** — `returncode` is None while the child lives; a real exit yields an integer. This pair is the system self-reporting "reader ended before the child did".
2. `output_preview` contains only shell startup noise; the task's real output sits in the redirect target file, growing.

## Defenses

1. **Sentinel echo (structural)**: append `… > out 2> err; echo "TASK_RC=$?"` to any Hermes-backgrounded command. A shell cannot exec-optimize a non-final command — it must survive until the task ends, so pipe EOF ⇔ true task death, and the real rc arrives through the pipe. Experiment verified: sentinel variant reported exited at exactly the task duration with `exit_code: 0` and `TASK_RC=0` visible in output_preview.
2. **Interpretation rule**: `exited` + `exit_code:null` = unverified until `ps -p <pid>` (and `pgrep -f <session-id>`) says otherwise. Encode in scripts, not habit.
3. **Writer check**: `lsof <events-file>` — a live file writer means the task is alive regardless of what poll said.

## Relay chain (delegate_agent → relay.mjs → pi) — structurally immune

- The relay spawns pi with `stdio: ["ignore","pipe","pipe"]` and consumes the event stream itself; pi's stdout pipe IS the relay's lifeline. It waits on `child.once("close")` and gates `completed` on the four-part contract (process exit + rc 0 + `agent_settled` + result.json). The Hermes process registry is not in the loop — its false-exit failure mode does not apply to the delegate→relay path.
- Two edges that DO apply:
  - Launching the relay itself via Hermes background WITH full output redirection reintroduces the trap one level up (zsh exec-optimizes into node). Same sentinel-echo fix.
  - `detached: true`: if the relay is killed externally (not via its own watchdog), pi is not signaled with it and keeps running/writing the worktree. pgrep-verify before re-dispatch or resume.
- A relay exiting non-zero (`failed`/`timeout`) still wrote `result.json` + artifacts with the working tree preserved — read it before choosing fresh vs exact-session resume; resume is usually the cheap path.

## Forensic one-shots

```bash
lsof <events.jsonl>                          # any live writer? task is alive
pgrep -f "<session-id>"                      # any pi process on this logical session
grep -c '"type":"agent_settled"' <events.jsonl>   # ≥2 with agent_start==1 → dual writer
python3 <this-skill>/scripts/pi-run-forensics.py <events.jsonl>   # bundled triage
```
