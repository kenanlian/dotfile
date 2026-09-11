"""Unit tests for relay blocking-wait support on the write (implement) lane.

Covers the fix for the 150-turn iteration-burn: ``devflow_start_or_inspect_relay``
must support ``wait_seconds`` on BOTH lanes so an implement worker blocks inside
one tool call instead of re-calling attach in a model loop while a ~1h write
relay runs.

Boots the real plugin package (same loader as test_finalize_intent.py); no
board DB is touched — these tests exercise the pure wait/clamp helpers and the
tool schema contract.

Run with the installed Hermes interpreter:

    ~/.hermes/hermes-agent/venv/bin/python -m unittest discover -s tests \
        -p 'test_*.py'
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent

for _entry in list(sys.path):
    try:
        if Path(_entry).resolve() == PLUGIN_DIR:
            sys.path.remove(_entry)
    except OSError:
        continue

_MODULE_NAME = "devwf_test_relay_wait"


def _load_plugin_package():
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    init_file = PLUGIN_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, init_file, submodule_search_locations=[str(PLUGIN_DIR)]
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load plugin package from {init_file}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _MODULE_NAME
    module.__path__ = [str(PLUGIN_DIR)]
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_plugin = _load_plugin_package()

# Import harness submodules through whichever package instance was loaded
# (discovery may have already loaded the plugin under the finalize-test name).
_pkg_name = _plugin.__name__
ow = importlib.import_module(f"{_pkg_name}.harness.operations_worker")
tw = importlib.import_module(f"{_pkg_name}.harness.tools_worker")
_harness_errors = importlib.import_module(f"{_pkg_name}.harness.errors")
HarnessError = _harness_errors.HarnessError


class _FallbackAdapter:
    """Adapter whose runtime probe fails -> executor ceiling falls back."""

    def _load_runtime(self):  # pragma: no cover - exercised via exception
        raise RuntimeError("no runtime in unit tests")


class RelayWaitSecondsTests(unittest.TestCase):
    """Validation + clamping shared by review and write lanes."""

    def setUp(self):
        self.adapter = _FallbackAdapter()

    def test_none_defaults_and_clamps_to_ceiling(self):
        # 1800 default clamped just below the 420s sequential-tool fallback.
        got = ow._relay_wait_seconds(self.adapter, None, None)
        self.assertEqual(got, ow._EXECUTOR_WAIT_FALLBACK_SECONDS - 30)

    def test_zero_passes_through(self):
        self.assertEqual(ow._relay_wait_seconds(self.adapter, None, 0), 0)

    def test_small_value_unchanged(self):
        self.assertEqual(ow._relay_wait_seconds(self.adapter, None, 60), 60)

    def test_over_max_rejected(self):
        with self.assertRaises(HarnessError):
            ow._relay_wait_seconds(self.adapter, None, 5000)

    def test_non_integer_rejected(self):
        for bad in ("30", 1.5, True):
            with self.assertRaises(HarnessError):
                ow._relay_wait_seconds(self.adapter, None, bad)


class RelayProcessWaitTests(unittest.TestCase):
    """Blocking wait must observe process exit and deadline, not poll-loop."""

    def test_returns_when_process_exits(self):
        child = subprocess.Popen(["sleep", "2"])
        start = time.monotonic()
        ow._wait_for_relay_process(child.pid, 30)
        elapsed = time.monotonic() - start
        self.assertEqual(child.poll(), 0)
        self.assertLess(elapsed, 10.0)

    def test_dead_pid_returns_immediately(self):
        child = subprocess.Popen(["true"])
        child.wait()
        start = time.monotonic()
        ow._wait_for_relay_process(child.pid, 30)
        self.assertLess(time.monotonic() - start, 2.0)

    def test_deadline_expires_while_process_alive(self):
        child = subprocess.Popen(["sleep", "30"])
        try:
            start = time.monotonic()
            ow._wait_for_relay_process(child.pid, 2)
            elapsed = time.monotonic() - start
            self.assertGreaterEqual(elapsed, 1.5)
            self.assertLess(elapsed, 10.0)
            self.assertIsNone(child.poll())  # wait must not kill the relay
        finally:
            child.kill()
            child.wait()

    def test_zero_wait_is_a_noop(self):
        child = subprocess.Popen(["sleep", "5"])
        try:
            start = time.monotonic()
            ow._wait_for_relay_process(child.pid, 0)
            self.assertLess(time.monotonic() - start, 1.0)
        finally:
            child.kill()
            child.wait()


class WriteLaneWaitContractTests(unittest.TestCase):
    """The tool schema must document waiting for both lanes, not review only."""

    def test_schema_description_covers_both_lanes(self):
        desc = tw.DEVFLOW_START_OR_INSPECT_RELAY_SCHEMA["parameters"][
            "properties"
        ]["wait_seconds"]["description"]
        self.assertNotIn("Review lane only", desc)
        self.assertIn("attach", desc)

    def test_write_mode_relay_accepts_wait_seconds(self):
        # Signature contract: the write-lane entry point takes wait_seconds.
        import inspect

        params = inspect.signature(ow._write_mode_relay).parameters
        self.assertIn("wait_seconds", params)
        self.assertEqual(params["wait_seconds"].default, 0)

    def test_dispatch_passes_wait_seconds_to_write_lane(self):
        # op_start_or_inspect_relay must forward wait_seconds (raw value; the
        # write branch clamps through _relay_wait_seconds itself).
        import inspect

        params = inspect.signature(ow.op_start_or_inspect_relay).parameters
        self.assertIn("wait_seconds", params)


if __name__ == "__main__":
    unittest.main()
