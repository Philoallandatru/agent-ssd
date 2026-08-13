"""framework.reporters.json_reporter — machine-readable output."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


class JsonReporter:
    def __init__(self, output_path: str):
        self.output_path = Path(output_path)
        self.events: list = []

    def on_event(self, name: str, payload: dict) -> None:
        self.events.append({"event": name, **payload})

    def finalize(self, report: Any) -> None:
        full = {
            "events": self.events,
            "report": report.to_dict(),
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(full, indent=2, default=str))
