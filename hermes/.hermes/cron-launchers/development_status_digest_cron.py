#!/usr/bin/env python3
"""Cron-safe launcher for the tracked development status digest.

Hermes Cron rejects script symlinks whose resolved target is outside
~/.hermes/scripts. The digest itself remains dotfile-managed; this regular-file
launcher is deployed byte-for-byte from the repository and executes it.
"""

from pathlib import Path
import runpy


def main() -> None:
    target = Path(__file__).with_name("development_status_digest.py")
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
