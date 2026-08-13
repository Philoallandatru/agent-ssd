"""
write_heavy.session_persist
===========================
A scripted agent that runs 100 turns, each ending with an O_DSYNC fsync
on a session log file. Models "opencode --session-id xxx" running for
many turns.

Metrics captured: total_seconds, n_fsync, fsync_latency_ms, trajectory_hash.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any
import time

from ..base import BaseTask, TaskContext, TaskResult
from ...agents.scripted import ScriptedAgent, ScriptStep
from ...agents.base import AgentState


@dataclass
class SessionPersistTask:
    id: str = "write_heavy/session_persist"
    category: str = "write_heavy"
    slo_seconds: float = 30.0
    description: str = "100-turn agent with per-turn fsync — models session persistence."

    # how many turns the agent runs
    n_turns: int = 100

    def setup(self, ctx: TaskContext) -> None:
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        # Seed: create the session log file
        (ctx.workdir / "session.log").write_text("agent session log\n")
        # Seed: a small "config" file the agent will read on turn 0
        (ctx.workdir / "config.json").write_text('{"slo": 30}\n')

    def run(self, agent, ctx: TaskContext) -> TaskResult:
        if not isinstance(agent, ScriptedAgent):
            raise TypeError("SessionPersistTask requires ScriptedAgent in v0")

        # Build the script: 1 read + 99 (write + fsync) turns
        script = [ScriptStep(kind="read_file", path="config.json")]
        for i in range(self.n_turns):
            script.append(ScriptStep(kind="edit_file", path="session.log",
                                     content=f"\nturn {i}"))
            script.append(ScriptStep(kind="fsync", path="session.log"))

        agent.reset(self.id, ctx.workdir)
        agent.set_script(script)

        t0 = time.perf_counter()
        step_count = 0
        max_step_ms = 0.0
        for step_idx in range(len(script) + 1):
            state = AgentState(task_id=self.id, turn=step_idx, cwd=ctx.workdir)
            action, obs = agent.step(state)
            step_count += 1
            max_step_ms = max(max_step_ms, obs.latency_ms)
            if not obs.ok:
                return TaskResult(
                    task_id=self.id, category=self.category,
                    state="FAILED", total_seconds=time.perf_counter() - t0,
                    error=obs.error or "step failed",
                )
            if action.type == "done":
                break
        total = time.perf_counter() - t0

        result = TaskResult(
            task_id=self.id, category=self.category, state="COMPLETED",
            total_seconds=total, agent_metrics=agent.metrics(),
            trajectory_hash=agent.trajectory_hash(),
        )
        result.extra = {"n_fsync": self.n_turns, "n_turns": self.n_turns,
                        "max_step_ms": max_step_ms}
        return result

    def verify(self, result: TaskResult, ctx: TaskContext) -> bool:
        if not result.passed:
            return False
        log = ctx.workdir / "session.log"
        if not log.exists():
            result.error = "session.log missing"
            return False
        content = log.read_text()
        if f"turn {self.n_turns - 1}" not in content:
            result.error = f"session.log missing last turn"
            return False
        return True
