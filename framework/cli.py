#!/usr/bin/env python3
"""framework.cli — minimal CLI entry point for the benchmark framework.

Usage:
    python -m framework.cli --sut /mnt/sut --tasks write_heavy/session_persist \\
        --runs 3 --output report.json

Or with a YAML config:
    python -m framework.cli --config configs/example.yaml
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .harness import Runner, RunSpec
from .agents import get_agent_factory
from .reporters import ConsoleReporter, JsonReporter


def _agent_factory_from_name(name: str):
    """Pick the agent factory. Delegates to the AGENT_REGISTRY."""
    return get_agent_factory(name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="framework.cli",
        description="Agent SSD benchmark — runs agent tasks against a SUT directory.",
    )
    parser.add_argument("--config", type=str, default=None,
                        help="YAML config path. Overrides --sut/--tasks if given.")
    parser.add_argument("--sut", type=str, default="/tmp/agentssd-sut",
                        help="Path to the directory under test.")
    parser.add_argument("--tasks", nargs="+", default=["write_heavy/session_persist"],
                        help="Task IDs (use framework.tasks.TASK_REGISTRY keys).")
    parser.add_argument("--runs", type=int, default=3,
                        help="Runs per task.")
    parser.add_argument("--slo", type=float, default=30.0,
                        help="SLO seconds per task.")
    parser.add_argument("--agent", default="scripted",
                        help="Agent name. See framework.agents.list_agents()")
    parser.add_argument("--output", type=str, default=None,
                        help="JSON output path. If omitted, no JSON is written.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.config:
        try:
            import yaml
        except ImportError:
            print("ERROR: PyYAML not installed. `pip install pyyaml`", file=sys.stderr)
            return 2
        d = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
        spec = RunSpec.from_dict(d)
    else:
        spec = RunSpec(
            run_id="cli-" + str(hash(args.sut))[-6:],
            sut_path=args.sut,
            agent_name=args.agent,
            task_ids=args.tasks,
            slo_seconds=args.slo,
            runs_per_state=args.runs,
        )

    reporters = [ConsoleReporter(verbose=args.verbose)]
    if args.output:
        reporters.append(JsonReporter(args.output))

    # Use a multiplex reporter so all reporters see the same events
    class Multi:
        def __init__(self, rs): self.rs = rs
        def on_event(self, name, payload):
            for r in self.rs: r.on_event(name, payload)
        def finalize(self, report):
            for r in self.rs: r.finalize(report)

    runner = Runner(
        runspec=spec,
        agent_factory=_agent_factory_from_name(spec.agent_name),
        reporter=Multi(reporters),
    )
    report = runner.run()
    return 0 if report.aggregate_passed else 1


if __name__ == "__main__":
    sys.exit(main())
