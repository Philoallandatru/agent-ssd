"""
examples/pi_agent.py
====================
STUB for the pi agent (pi-mono minimal coding agent).

Same shape as opencode_agent.py — the framework only needs BaseAgent to
work. Real pi integration is a v1 task.
"""
from __future__ import annotations
from pathlib import Path
from framework.agents import BaseAgent, AgentState, Action, Observation


class PiAgent(BaseAgent):
    name = "pi"

    def __init__(self, model: str = "gpt-4o", binary: str = "pi"):
        self.model = model
        self.binary = binary

    def reset(self, task_id: str, cwd: Path) -> None:
        # TODO v1
        pass

    def step(self, state: AgentState) -> tuple[Action, Observation]:
        return (
            Action(type="bash"),
            Observation(ok=False, error="pi adapter is a v1 stub; "
                                       "use ScriptedAgent for v0 runs"),
        )
