"""Typed subprocess client for the v2 External Execution Guard (design §15).

Wraps ``development_external_guard.py`` as a CLI. Never imports ``hermes_cli``.
Guard exit codes are returned, not raised; only client-side unavailability
(timeout / spawn failure) raises ``HarnessError(HARNESS_STATE_UNAVAILABLE)``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .errors import HARNESS_STATE_UNAVAILABLE, HarnessError

_UNPARSEABLE = "guard-output-unparseable"


class GuardClient:
    """Keyword-only client bound to one board/card artifacts namespace."""

    def __init__(
        self,
        *,
        script_path,
        home,
        board: str,
        card_id: str,
        artifacts_root,
    ) -> None:
        self.script_path = Path(script_path)
        self.home = Path(home)
        self.board = str(board)
        self.card_id = str(card_id)
        self.artifacts_root = Path(artifacts_root)

    def state_path(self) -> Path:
        return (
            self.artifacts_root / self.board / "tasks" / self.card_id
            / "external-execution.json"
        )

    def read_state(self) -> dict | None:
        """Tolerant direct read. ``None`` when the file is absent or corrupt."""
        path = self.state_path()
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def run(
        self, command: str, *argv: str, timeout: float = 120.0
    ) -> tuple[int, dict]:
        """Invoke the guard CLI. Never raises for guard exit codes."""
        cmd = [
            sys.executable,
            str(self.script_path),
            "--artifacts-root",
            str(self.artifacts_root),
            "--home",
            str(self.home),
            "--board",
            self.board,
            "--card",
            self.card_id,
            command,
            *argv,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise HarnessError(
                HARNESS_STATE_UNAVAILABLE,
                f"guard command {command!r} timed out after {timeout}s",
                command=command,
                timeout=timeout,
            ) from exc
        except OSError as exc:
            raise HarnessError(
                HARNESS_STATE_UNAVAILABLE,
                f"guard command {command!r} could not be started: {exc}",
                command=command,
            ) from exc
        payload = _parse_guard_stdout(proc.stdout, proc.stderr)
        return proc.returncode, payload

    def init(self, repo) -> tuple[int, dict]:
        return self.run("init", "--repo", str(repo))

    def start_or_inspect(
        self,
        *,
        operation,
        out_dir,
        result_path,
        cmd_json: list,
        cwd=None,
        plan_artifact=None,
        new_attempt: bool = False,
    ) -> tuple[int, dict]:
        argv = [
            "--operation",
            str(operation),
            "--out-dir",
            str(out_dir),
            "--result-path",
            str(result_path),
            "--cmd-json",
            json.dumps(list(cmd_json)),
        ]
        if cwd is not None:
            argv.extend(["--cwd", str(cwd)])
        if plan_artifact is not None:
            argv.extend(["--plan-artifact", str(plan_artifact)])
        if new_attempt:
            argv.append("--new-attempt")
        return self.run("start-or-inspect", *argv)

    def inspect(self) -> tuple[int, dict]:
        return self.run("inspect")

    def record_terminal(self, result_path, session_id=None) -> tuple[int, dict]:
        argv = ["--result-path", str(result_path)]
        if session_id is not None:
            argv.extend(["--session-id", str(session_id)])
        return self.run("record-terminal", *argv)

    def check_run(self) -> tuple[int, dict]:
        """Current process env is inherited untouched (task/run ids)."""
        return self.run("check-run")

    def record_commit(self, commit: str) -> tuple[int, dict]:
        return self.run("record-commit", "--commit", str(commit))


def _parse_guard_stdout(stdout: str, stderr: str) -> dict[str, Any]:
    """Parse the single JSON object. Last non-empty stdout line wins."""
    text = (stdout or "").strip()
    candidates: list[str] = []
    if text:
        candidates.append(text.splitlines()[-1])
        if text not in candidates:
            candidates.append(text)
    for blob in candidates:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raw = stdout if stdout else stderr
    return {"ok": False, "reason": _UNPARSEABLE, "raw": raw}
