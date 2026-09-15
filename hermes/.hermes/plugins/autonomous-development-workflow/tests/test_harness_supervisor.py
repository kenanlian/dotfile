"""Harness supervisor: argv spawn, identity-bound recovery, heartbeat, process group teardown."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from plugin_imports import import_plugin

_harness = import_plugin("controller.harness")
_types = import_plugin("controller.types")

WorkflowProtocolError = _types.WorkflowProtocolError
RESULT_SCHEMA = _types.RESULT_SCHEMA
build_harness_argv = _harness.build_harness_argv
observe_harness_run = _harness.observe_harness_run
read_run_lock = _harness.read_run_lock
start_harness_run = _harness.start_harness_run
terminate_process_group = _harness.terminate_process_group
wait_on_harness = _harness.wait_on_harness


def _result(**overrides) -> dict:
    data = {
        "schema": RESULT_SCHEMA,
        "jobId": "job_plan1",
        "idempotencyKey": "b:t:plan:1:0:deadbeef",
        "jobSha256": "a" * 64,
        "taskId": "t_abc",
        "stage": "plan",
        "status": "completed",
        "adapter": "pi",
        "sessionId": "sess",
        "startedAt": "2026-09-14T00:00:00Z",
        "finishedAt": "2026-09-14T00:01:00Z",
        "structuredOutput": {"kind": "plan", "payload": {"schema": "plan.v1"}},
        "artifacts": [],
        "touchedFiles": [],
        "checks": [],
        "usage": {},
        "workspace": {
            "repoRoot": "/abs/repo",
            "branchBefore": "main",
            "branchAfter": "main",
            "headBefore": "a" * 40,
            "headAfter": "a" * 40,
            "snapshotBeforeSha256": "c" * 64,
            "snapshotAfterSha256": "c" * 64,
        },
        "error": None,
        "paths": {
            "events": "/abs/events.jsonl",
            "stderr": "/abs/stderr.log",
            "final": "/abs/final.txt",
            "adapterRuns": [],
        },
    }
    data.update(overrides)
    return data


class ArgvTests(unittest.TestCase):
    def test_argv_is_run_job_and_out_dir_without_a_shell_string(self) -> None:
        argv = build_harness_argv(
            ("node", "/abs/harness.mjs"),
            job_path="/abs/job.json",
            out_dir="/abs/run",
        )
        self.assertEqual(
            argv,
            ["node", "/abs/harness.mjs", "run", "--job", "/abs/job.json", "--out-dir", "/abs/run"],
        )
        with self.assertRaises(WorkflowProtocolError):
            build_harness_argv("node /abs/harness.mjs", job_path="/abs/job.json", out_dir="/abs/run")
        with self.assertRaises(WorkflowProtocolError):
            build_harness_argv(("node",), job_path="job.json", out_dir="/abs/run")


class ObserveRecoveryOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-harness-")
        self.run_dir = Path(self._tmp.name) / "run"
        self.run_dir.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_identity_matched_result_wins_over_lock_and_pid(self) -> None:
        (self.run_dir / "result.json").write_text(json.dumps(_result()), encoding="utf-8")
        (self.run_dir / "run.lock").write_text(
            json.dumps({"pid": 1, "startedAt": "t", "jobSha256": "a" * 64, "jobId": "job_plan1"}),
            encoding="utf-8",
        )
        (self.run_dir / "events.jsonl").write_text(
            json.dumps({"type": "run_finished", "data": {"status": "completed"}}) + "\n",
            encoding="utf-8",
        )
        observed = observe_harness_run(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
            recorded_pid=1,
            recorded_identity="1:alive",
            identity_fn=lambda pid: "1:alive",
        )
        self.assertEqual(observed.kind, "terminal_result")
        self.assertEqual(observed.result["jobId"], "job_plan1")

    def test_events_alone_are_not_terminal_truth(self) -> None:
        (self.run_dir / "events.jsonl").write_text(
            json.dumps({"type": "run_finished", "data": {"status": "completed"}}) + "\n",
            encoding="utf-8",
        )
        observed = observe_harness_run(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
        )
        self.assertEqual(observed.kind, "not_started")

    def test_mismatched_result_is_not_consumed_as_terminal(self) -> None:
        (self.run_dir / "result.json").write_text(
            json.dumps(_result(jobSha256="b" * 64, jobId="job_other")),
            encoding="utf-8",
        )
        observed = observe_harness_run(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
        )
        self.assertNotEqual(observed.kind, "terminal_result")

    def test_live_process_requires_pid_start_identity_and_job_binding(self) -> None:
        lock = {
            "pid": 42,
            "startedAt": "Mon Sep 14 00:00:00 2026",
            "jobSha256": "a" * 64,
            "jobId": "job_plan1",
            "outDir": str(self.run_dir),
        }
        (self.run_dir / "run.lock").write_text(json.dumps(lock), encoding="utf-8")
        live = observe_harness_run(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
            recorded_pid=42,
            recorded_identity="42:Mon Sep 14 00:00:00 2026",
            identity_fn=lambda pid: "42:Mon Sep 14 00:00:00 2026" if pid == 42 else None,
        )
        self.assertEqual(live.kind, "live_process")
        recycled = observe_harness_run(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
            recorded_pid=42,
            recorded_identity="42:Mon Sep 14 00:00:00 2026",
            identity_fn=lambda pid: "42:DIFFERENT-START" if pid == 42 else None,
        )
        self.assertEqual(recycled.kind, "orphan_lock")
        pid_only_alive = observe_harness_run(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
            recorded_pid=42,
            recorded_identity=None,
            identity_fn=lambda pid: "42:now",
        )
        self.assertEqual(pid_only_alive.kind, "orphan_lock")

    def test_orphan_lock_is_not_silently_deleted(self) -> None:
        lock_path = self.run_dir / "run.lock"
        lock_path.write_text(
            json.dumps(
                {
                    "pid": 999999,
                    "startedAt": "t",
                    "jobSha256": "a" * 64,
                    "jobId": "job_plan1",
                }
            ),
            encoding="utf-8",
        )
        observed = observe_harness_run(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
            recorded_pid=999999,
            recorded_identity="999999:old",
            identity_fn=lambda pid: None,
        )
        self.assertEqual(observed.kind, "orphan_lock")
        self.assertTrue(observed.lock_bound_to_job)
        self.assertTrue(lock_path.is_file())

    def test_unbound_orphan_lock_is_still_not_deleted(self) -> None:
        lock_path = self.run_dir / "run.lock"
        lock_path.write_text("orphan\n", encoding="utf-8")
        observed = observe_harness_run(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
        )
        self.assertEqual(observed.kind, "orphan_lock")
        self.assertFalse(observed.lock_bound_to_job)
        self.assertTrue(lock_path.is_file())
        parsed = read_run_lock(str(self.run_dir))
        self.assertIsNotNone(parsed)

    def test_empty_run_dir_is_not_started(self) -> None:
        observed = observe_harness_run(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
        )
        self.assertEqual(observed.kind, "not_started")


class StartAndWaitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autodev-start-")
        self.run_dir = Path(self._tmp.name) / "run"
        self.run_dir.mkdir()
        self.job_path = Path(self._tmp.name) / "job.json"
        self.job_path.write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_existing_result_does_not_spawn(self) -> None:
        (self.run_dir / "result.json").write_text(json.dumps(_result()), encoding="utf-8")
        popen = Mock(side_effect=AssertionError("must not spawn"))
        handle = start_harness_run(
            harness_command=("node", "/abs/harness.mjs"),
            job_path=str(self.job_path),
            out_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
            popen=popen,
        )
        self.assertEqual(handle.observation.kind, "terminal_result")
        popen.assert_not_called()

    def test_orphan_lock_does_not_spawn_or_delete(self) -> None:
        lock_path = self.run_dir / "run.lock"
        lock_path.write_text(
            json.dumps({"pid": 1, "jobSha256": "a" * 64, "jobId": "job_plan1"}),
            encoding="utf-8",
        )
        popen = Mock(side_effect=AssertionError("must not spawn"))
        handle = start_harness_run(
            harness_command=("node", "/abs/harness.mjs"),
            job_path=str(self.job_path),
            out_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
            popen=popen,
            identity_fn=lambda pid: None,
        )
        self.assertEqual(handle.observation.kind, "orphan_lock")
        popen.assert_not_called()
        self.assertTrue(lock_path.is_file())

    def test_not_started_spawns_with_argv_shell_false_and_new_session(self) -> None:
        captured = {}

        def fake_popen(argv, **kwargs):
            captured["argv"] = list(argv)
            captured["kwargs"] = kwargs
            proc = Mock()
            proc.pid = 77
            return proc

        handle = start_harness_run(
            harness_command=("node", "/abs/harness.mjs"),
            job_path=str(self.job_path),
            out_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
            popen=fake_popen,
            identity_fn=lambda pid: f"{pid}:start",
        )
        self.assertEqual(handle.observation.kind, "live_process")
        self.assertEqual(handle.pid, 77)
        self.assertEqual(handle.process_identity, "77:start")
        self.assertEqual(captured["kwargs"]["shell"], False)
        self.assertTrue(captured["kwargs"]["start_new_session"])
        self.assertEqual(
            captured["argv"][:4],
            ["node", "/abs/harness.mjs", "run", "--job"],
        )

    def test_wait_clamps_to_300_and_heartbeats_within_60s(self) -> None:
        with self.assertRaises(WorkflowProtocolError):
            wait_on_harness(
                run_dir=str(self.run_dir),
                job_id="job_plan1",
                job_sha256="a" * 64,
                wait_seconds=301,
            )
        beats: list[float] = []
        clock = {"t": 0.0}

        def fake_sleep(seconds: float) -> None:
            clock["t"] += seconds
            if clock["t"] >= 5:
                (self.run_dir / "result.json").write_text(json.dumps(_result()), encoding="utf-8")

        observed = wait_on_harness(
            run_dir=str(self.run_dir),
            job_id="job_plan1",
            job_sha256="a" * 64,
            wait_seconds=60,
            poll_interval_seconds=5,
            heartbeat=lambda: beats.append(clock["t"]),
            sleep_fn=fake_sleep,
            monotonic_fn=lambda: clock["t"],
        )
        self.assertEqual(observed.kind, "terminal_result")
        self.assertGreaterEqual(len(beats), 1)
        self.assertLessEqual(beats[0], 60)

    def test_terminate_sends_sigterm_to_process_group(self) -> None:
        import signal

        kills: list[tuple[int, int]] = []

        def fake_killpg(pgid: int, sig: int) -> None:
            kills.append((pgid, sig))

        terminate_process_group(12, getpgid_fn=lambda pid: pid, killpg_fn=fake_killpg)
        self.assertEqual(kills, [(12, signal.SIGTERM)])


if __name__ == "__main__":
    unittest.main()
