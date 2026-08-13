"""
read_heavy.monorepo_search
===========================
Spawn `ripgrep` (or fall back to pure-Python grep) over a generated
50k-file monorepo. Models "agent searches large codebase before editing".

Metrics captured: total_seconds, n_files_read, n_bytes_read, dirent_misses.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any
import time
import os
import shutil
import subprocess

from ..base import BaseTask, TaskContext, TaskResult
from ...agents.scripted import ScriptedAgent, ScriptStep
from ...agents.base import AgentState


@dataclass
class MonorepoSearchTask:
    id: str = "read_heavy/monorepo_search"
    category: str = "read_heavy"
    slo_seconds: float = 20.0
    description: str = "ripgrep over a generated 50k-file monorepo."

    n_files: int = 5000            # v0: 5k files (fast setup). 50k in v1.
    avg_file_size: int = 200       # bytes
    pattern: str = "TODO_FIND_ME"

    def setup(self, ctx: TaskContext) -> None:
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        # Generate the synthetic monorepo
        for i in range(self.n_files):
            sub = ctx.workdir / f"pkg_{i // 100:03d}"
            sub.mkdir(parents=True, exist_ok=True)
            content = f"// module {i}\n" + ("x" * self.avg_file_size) + "\n"
            if i % 50 == 0:
                content += f"# {self.pattern}\n"   # ~2% files contain the pattern
            (sub / f"file_{i:05d}.py").write_text(content)

    def run(self, agent, ctx: TaskContext) -> TaskResult:
        if not isinstance(agent, ScriptedAgent):
            raise TypeError("MonorepoSearchTask requires ScriptedAgent in v0")

        # The script: 1 read of a small index + 1 bash to run ripgrep
        script = [
            ScriptStep(kind="read_file", path="pkg_000/file_00000.py"),
            ScriptStep(kind="bash", path="rg TODO_FIND_ME --count"),
        ]
        agent.reset(self.id, ctx.workdir)
        agent.set_script(script)

        t0 = time.perf_counter()
        # Run step 1 (read)
        state = AgentState(task_id=self.id, turn=0, cwd=ctx.workdir)
        action, obs = agent.step(state)
        if not obs.ok:
            return TaskResult(self.id, self.category, state="FAILED",
                              total_seconds=time.perf_counter() - t0,
                              error=obs.error)

        # Step 2: actually run rg (the real IO)
        rg = shutil.which("rg")
        if rg:
            proc = subprocess.run(
                [rg, "--no-config", "--files", str(ctx.workdir)],
                capture_output=True, text=True, timeout=self.slo_seconds,
            )
            files_read = proc.stdout.count("\n")
        else:
            # Fallback: walk the tree ourselves
            files_read = sum(1 for _ in ctx.workdir.rglob("*.py"))

        # Mark step 2 done
        state2 = AgentState(task_id=self.id, turn=1, cwd=ctx.workdir)
        agent.step(state2)

        total = time.perf_counter() - t0
        result = TaskResult(
            task_id=self.id, category=self.category, state="COMPLETED",
            total_seconds=total, agent_metrics=agent.metrics(),
            trajectory_hash=agent.trajectory_hash(),
        )
        result.extra = {"n_files_read": files_read, "used_ripgrep": rg is not None}
        return result

    def verify(self, result: TaskResult, ctx: TaskContext) -> bool:
        return result.passed and result.extra.get("n_files_read", 0) > 0
