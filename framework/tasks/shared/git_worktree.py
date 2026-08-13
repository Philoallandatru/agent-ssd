"""
shared.git_worktree
===================
N scripted agents each in their own `git worktree`, all building from
the same shared git index. Models "multi-agent swarm" concurrent edits.

v0 implementation: in-process N ScriptedAgents operating on isolated
subdirectories (no real git needed for v0; the test is concurrency, not git).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List
import time
import shutil

from ..base import BaseTask, TaskContext, TaskResult
from ...agents.scripted import ScriptedAgent, ScriptStep
from ...agents.base import AgentState


@dataclass
class GitWorktreeSwarmTask:
    id: str = "shared/git_worktree"
    category: str = "shared"
    slo_seconds: float = 60.0
    description: str = "N agents build in parallel subdirs — models swarm contention."

    n_agents: int = 4
    per_agent_steps: int = 50     # build steps per agent

    def setup(self, ctx: TaskContext) -> None:
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        for a in range(self.n_agents):
            sub = ctx.workdir / f"agent_{a:02d}"
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "shared.lock").write_text("0")  # fake lock file
            for i in range(10):
                (sub / f"src_{i}.rs").write_text(f"// agent {a} src {i}\n" + "x" * 200)

    def run(self, agent, ctx: TaskContext) -> TaskResult:
        """The runner passes ONE agent. We clone it N times via set_script —
        each agent in its own workdir."""
        t0 = time.perf_counter()
        per_agent_times: List[float] = []
        per_agent_lockwaits: List[float] = []

        for a in range(self.n_agents):
            sub = ctx.workdir / f"agent_{a:02d}"
            # Each agent: read shared.lock + 10 src files + write back + fsync
            script = [ScriptStep(kind="read_file", path="shared.lock")]
            for i in range(10):
                script.append(ScriptStep(kind="read_file", path=f"src_{i}.rs"))
            script.append(ScriptStep(kind="edit_file", path="shared.lock", content="x"))
            script.append(ScriptStep(kind="fsync", path="shared.lock"))
            for _ in range(self.per_agent_steps - 12):
                script.append(ScriptStep(kind="bash", path="cargo check"))

            agent.reset(self.id, sub)
            agent.set_script(script)

            agent_t0 = time.perf_counter()
            for step_idx in range(len(script) + 1):
                state = AgentState(task_id=self.id, turn=step_idx, cwd=sub)
                action, obs = agent.step(state)
                if not obs.ok:
                    return TaskResult(self.id, self.category, state="FAILED",
                                      total_seconds=time.perf_counter() - t0,
                                      error=obs.error or f"agent {a} failed")
                if action.type == "done":
                    break
            per_agent_times.append(time.perf_counter() - agent_t0)
            per_agent_lockwaits.append(0.0)  # v0: no real lock

        total = time.perf_counter() - t0
        max_time = max(per_agent_times)
        # swarm SLO uses the slowest agent, not the sum
        result = TaskResult(
            task_id=self.id, category=self.category, state="COMPLETED",
            total_seconds=max_time, agent_metrics=None,
            trajectory_hash="",
        )
        result.extra = {"n_agents": self.n_agents,
                        "per_agent_seconds": per_agent_times,
                        "max_agent_seconds": max_time,
                        "wall_total_seconds": total}
        return result

    def verify(self, result: TaskResult, ctx: TaskContext) -> bool:
        if not result.passed:
            return False
        # Check each agent subdir is intact
        for a in range(self.n_agents):
            sub = ctx.workdir / f"agent_{a:02d}"
            if not (sub / "shared.lock").exists():
                result.error = f"agent_{a:02d}/shared.lock missing"
                return False
        return True
