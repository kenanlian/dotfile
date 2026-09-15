"""Supervise coding-agent-harness processes without treating lock/PID as truth."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .protocol import require_absolute_path
from .types import RESULT_SCHEMA, WorkflowProtocolError

MAX_WAIT_SECONDS = 300
HEARTBEAT_EVERY_SECONDS = 60
IdentityFn = Callable[[int], str | None]
PopenFn = Callable[..., Any]
HeartbeatFn = Callable[[], None]
SleepFn = Callable[[float], None]
MonotonicFn = Callable[[], float]


@dataclass(frozen=True)
class HarnessObservation:
    kind: str
    result: Mapping[str, Any] | None = None
    pid: int | None = None
    process_identity: str | None = None
    lock: Mapping[str, Any] | None = None
    lock_bound_to_job: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class HarnessHandle:
    observation: HarnessObservation
    pid: int | None = None
    process_identity: str | None = None
    started_at: int | None = None
    proc: Any | None = None


def build_harness_argv(harness_command: Any, *, job_path: str, out_dir: str) -> list[str]:
    if isinstance(harness_command, str) or not isinstance(harness_command, (list, tuple)) or not harness_command:
        raise WorkflowProtocolError("harness_command must be a non-empty argv list, not a shell string")
    argv = [item for item in harness_command]
    if any(not isinstance(item, str) or not item for item in argv):
        raise WorkflowProtocolError("harness_command items must be non-empty strings")
    job = require_absolute_path(job_path, "job_path")
    run_dir = require_absolute_path(out_dir, "out_dir")
    return [*argv, "run", "--job", job, "--out-dir", run_dir]


def process_start_identity(pid: int) -> str | None:
    if not isinstance(pid, int) or pid <= 0:
        return None
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    text = completed.stdout.strip()
    if completed.returncode != 0 or not text:
        return None
    return f"{pid}:{text}"


def read_run_lock(run_dir: str) -> dict[str, Any] | None:
    path = Path(require_absolute_path(run_dir, "run_dir")) / "run.lock"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw, "pid": None, "jobSha256": None, "jobId": None}
    if not isinstance(payload, dict):
        return {"raw": raw, "pid": None, "jobSha256": None, "jobId": None}
    return payload


def read_result(run_dir: str) -> dict[str, Any] | None:
    path = Path(require_absolute_path(run_dir, "run_dir")) / "result.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def result_matches_job(result: Mapping[str, Any], *, job_id: str, job_sha256: str) -> bool:
    return (
        result.get("schema") == RESULT_SCHEMA
        and result.get("jobId") == job_id
        and result.get("jobSha256") == job_sha256
    )


def lock_bound_to_job(lock: Mapping[str, Any] | None, *, job_id: str, job_sha256: str, run_dir: str) -> bool:
    if not lock:
        return False
    if lock.get("jobSha256") != job_sha256 or lock.get("jobId") != job_id:
        return False
    out_dir = lock.get("outDir")
    if out_dir and Path(str(out_dir)) != Path(run_dir):
        return False
    return True


def observe_harness_run(
    *,
    run_dir: str,
    job_id: str,
    job_sha256: str,
    recorded_pid: int | None = None,
    recorded_identity: str | None = None,
    identity_fn: IdentityFn | None = None,
) -> HarnessObservation:
    identity_fn = identity_fn or process_start_identity
    result = read_result(run_dir)
    if result is not None and result_matches_job(result, job_id=job_id, job_sha256=job_sha256):
        return HarnessObservation(kind="terminal_result", result=result, reason="identity-matched result")

    lock = read_run_lock(run_dir)
    bound = lock_bound_to_job(lock, job_id=job_id, job_sha256=job_sha256, run_dir=run_dir)
    pid = recorded_pid
    if pid is None and isinstance(lock, Mapping) and isinstance(lock.get("pid"), int):
        pid = lock["pid"]
    live_identity = identity_fn(pid) if isinstance(pid, int) else None
    if (
        live_identity
        and recorded_identity
        and live_identity == recorded_identity
        and bound
    ):
        return HarnessObservation(
            kind="live_process",
            pid=pid,
            process_identity=live_identity,
            lock=lock,
            lock_bound_to_job=True,
            reason="identity-matched live process",
        )
    if lock is not None:
        return HarnessObservation(
            kind="orphan_lock",
            pid=pid,
            process_identity=recorded_identity,
            lock=lock,
            lock_bound_to_job=bound,
            reason="orphan lock or process identity mismatch",
        )
    return HarnessObservation(kind="not_started")


def start_harness_run(
    *,
    harness_command: Any,
    job_path: str,
    out_dir: str,
    job_id: str,
    job_sha256: str,
    recorded_pid: int | None = None,
    recorded_identity: str | None = None,
    env: Mapping[str, str] | None = None,
    popen: PopenFn | None = None,
    identity_fn: IdentityFn | None = None,
) -> HarnessHandle:
    identity_fn = identity_fn or process_start_identity
    observed = observe_harness_run(
        run_dir=out_dir,
        job_id=job_id,
        job_sha256=job_sha256,
        recorded_pid=recorded_pid,
        recorded_identity=recorded_identity,
        identity_fn=identity_fn,
    )
    if observed.kind != "not_started":
        return HarnessHandle(
            observation=observed,
            pid=observed.pid,
            process_identity=observed.process_identity,
        )
    argv = build_harness_argv(harness_command, job_path=job_path, out_dir=out_dir)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    launcher = popen or subprocess.Popen
    proc = launcher(
        argv,
        shell=False,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=None if env is None else dict(env),
    )
    identity = identity_fn(proc.pid)
    live = HarnessObservation(
        kind="live_process",
        pid=proc.pid,
        process_identity=identity,
        lock_bound_to_job=True,
        reason="started",
    )
    return HarnessHandle(
        observation=live,
        pid=proc.pid,
        process_identity=identity,
        started_at=int(time.time()),
        proc=proc,
    )


def wait_on_harness(
    *,
    run_dir: str,
    job_id: str,
    job_sha256: str,
    wait_seconds: int,
    poll_interval_seconds: int = 5,
    recorded_pid: int | None = None,
    recorded_identity: str | None = None,
    heartbeat: HeartbeatFn | None = None,
    sleep_fn: SleepFn | None = None,
    monotonic_fn: MonotonicFn | None = None,
    identity_fn: IdentityFn | None = None,
) -> HarnessObservation:
    if not isinstance(wait_seconds, int) or wait_seconds < 0 or wait_seconds > MAX_WAIT_SECONDS:
        raise WorkflowProtocolError("wait_seconds must be between 0 and 300")
    if poll_interval_seconds < 1:
        raise WorkflowProtocolError("poll_interval_seconds must be >= 1")
    sleep_fn = sleep_fn or time.sleep
    monotonic_fn = monotonic_fn or time.monotonic
    started = monotonic_fn()
    last_beat = started - HEARTBEAT_EVERY_SECONDS
    deadline = started + wait_seconds
    while True:
        now = monotonic_fn()
        if heartbeat is not None and now - last_beat >= HEARTBEAT_EVERY_SECONDS:
            heartbeat()
            last_beat = now
        observed = observe_harness_run(
            run_dir=run_dir,
            job_id=job_id,
            job_sha256=job_sha256,
            recorded_pid=recorded_pid,
            recorded_identity=recorded_identity,
            identity_fn=identity_fn,
        )
        if observed.kind in {"terminal_result", "orphan_lock"}:
            return observed
        if now >= deadline:
            return observed
        remaining = deadline - now
        sleep_fn(min(float(poll_interval_seconds), remaining))


def terminate_process_group(
    pid: int,
    *,
    getpgid_fn: Callable[[int], int] | None = None,
    killpg_fn: Callable[[int, int], None] | None = None,
    sig: int = signal.SIGTERM,
) -> None:
    getpgid = getpgid_fn or os.getpgid
    killpg = killpg_fn or os.killpg
    pgid = getpgid(pid)
    killpg(pgid, sig)
