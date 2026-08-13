"""
framework.reporters.base
========================
The reporter contract. Reporters consume events from the Runner.
"""

from __future__ import annotations
from typing import Protocol, Any


class Reporter(Protocol):
    def on_event(self, name: str, payload: dict) -> None: ...
    def finalize(self, report: Any) -> None: ...
