"""framework.reporters.console — human-readable, color-free output."""
from __future__ import annotations
import json
from typing import Any


class ConsoleReporter:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def on_event(self, name: str, payload: dict) -> None:
        if name == "state":
            print(f"  -> {payload['state']}")
        elif name == "task_start":
            print(f"  >> {payload['task_id']} run #{payload['run_idx']}")
        elif name == "task_end":
            mark = "[OK]" if payload["state"] == "COMPLETED" else "[FAIL]"
            extra = f"  ({payload['error']})" if payload.get("error") else ""
            print(f"    {mark} {payload['state']:<10}  "
                  f"{payload['total_seconds']:.3f}s{extra}")
        elif name == "run_complete":
            mark = "PASS" if payload["aggregate_passed"] else "FAIL"
            print(f"\n  Result: {mark}   CoV = {payload['co_v']*100:.2f}%")

    def finalize(self, report: Any) -> None:
        if self.verbose:
            print()
            print("  Per-task summary:")
            for r in report.task_results:
                mark = "[OK]" if r.passed else "[FAIL]"
                print(f"    {mark} {r.task_id:<32} {r.total_seconds:.3f}s")
