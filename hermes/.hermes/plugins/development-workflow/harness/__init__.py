"""Development Workflow Harness foundation package.

Keep this module a thin package marker. Callers import concrete modules
(``errors``, ``contracts``, ``policy``, ``hermes_adapter``, ``context``)
directly so later workers can depend on frozen names without pulling the
Hermes runtime at import time.
"""

from __future__ import annotations
