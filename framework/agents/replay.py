"""
framework.agents.replay
=======================
Wraps a ScriptedAgent, asserts the trajectory hash matches a recorded one.
Used to detect model drift.
"""

from __future__ import annotations
from pathlib import Path
from typing import List

from .base import BaseAgent, AgentState, Action, Observation
from .scripted import ScriptedAgent, ScriptStep


class ReplayingAgent(BaseAgent):
    """A ScriptedAgent that asserts trajectory hash matches a recorded run.

    If the recorded hash differs from the in-flight hash, the agent
    marks the step as a MODEL_BEHAVIOR_DRIFT and the task will fail.
    """
    name = "replaying"

    def __init__(self, script: List[ScriptStep], recorded_hash: str):
        self._inner = ScriptedAgent(script)
        self._recorded = recorded_hash
        self.drifted = False

    def reset(self, task_id: str, cwd: Path) -> None:
        self._inner.reset(task_id, cwd)

    def step(self, state: AgentState) -> tuple[Action, Observation]:
        action, obs = self._inner.step(state)
        # Check trajectory after every step (cheap: hash is local)
        current = self._inner.trajectory_hash()
        if not self.drifted and current != self._recorded:
            self.drifted = True
            obs.ok = False
            obs.error = f"MODEL_BEHAVIOR_DRIFT: expected {self._recorded} got {current}"
        return action, obs

    def trajectory_hash(self) -> str:
        return self._inner.trajectory_hash()

    def metrics(self):
        return self._inner.metrics()
