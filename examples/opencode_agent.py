"""
examples/opencode_agent.py
==========================
A STUB showing how to wrap opencode as a pluggable Agent for the
framework. This file is intentionally not runnable end-to-end — opencode
must be installed and reachable on PATH; see the opencode docs.

To use:
    from examples.opencode_agent import OpencodeAgent
    factory = lambda: OpencodeAgent(model="gpt-4o")
    runner = Runner(spec, factory)

Real opencode call pattern (v1, not v0):
    - shell out to `opencode` CLI
    - capture JSON events per turn
    - forward to BaseAgent.step() contract

The framework's `BaseAgent` interface is what the Runner depends on.
Any agent that implements step() correctly plugs in.
"""
from __future__ import annotations
from pathlib import Path
from framework.agents import BaseAgent, AgentState, Action, Observation


class OpencodeAgent(BaseAgent):
    name = "opencode"

    def __init__(self, model: str = "gpt-4o", binary: str = "opencode"):
        self.model = model
        self.binary = binary
        self._turn = 0

    def reset(self, task_id: str, cwd: Path) -> None:
        self._turn = 0
        # TODO v1: invoke `opencode --session-id <task_id> --cwd <cwd>`

    def step(self, state: AgentState) -> tuple[Action, Observation]:
        # TODO v1: read next event from opencode's JSON output
        # For v0, we just say "no real opencode, this is a stub".
        self._turn += 1
        return (
            Action(type="bash", args={"cmd": "echo opencode-stub"}),
            Observation(ok=False, error="opencode adapter is a v1 stub; "
                                       "use ScriptedAgent for v0 runs"),
        )
