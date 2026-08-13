"""
mixed.cargo_build
=================
A scripted "build cycle": read many small files + write a few intermediate
artifacts + fsync the final binary. Models `cargo build --release`.

v0 implementation: in-process simulation using ScriptedAgent. We don't
shell out to real cargo here because the framework must be runnable on
any box (real cargo work would be in v1 with eBPF collector).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any
import time
import os

from ..base import BaseTask, TaskContext, TaskResult
from ...agents.scripted import ScriptedAgent, ScriptStep
from ...agents.base import AgentState


@dataclass
class CargoBuildTask:
    id: str = "mixed/cargo_build"
    category: str = "mixed"
    slo_seconds: float = 30.0
    description: str = "Simulated build: read many sources, write artifacts, fsync final."

    n_source_files: int = 200
    source_size: int = 400
    n_artifacts: int = 20
    artifact_size: int = 50_000   # 50KB

    def setup(self, ctx: TaskContext) -> None:
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        src = ctx.workdir / "src"
        src.mkdir(exist_ok=True)
        for i in range(self.n_source_files):
            (src / f"mod_{i:04d}.rs").write_text(f"// crate {i}\n" + "x" * self.source_size)

    def run(self, agent, ctx: TaskContext) -> TaskResult:
        if not isinstance(agent, ScriptedAgent):
            raise TypeError("CargoBuildTask requires ScriptedAgent in v0")

        # Build a script: read all sources + write all artifacts + fsync
        script = []
        for i in range(self.n_source_files):
            script.append(ScriptStep(kind="read_file", path=f"src/mod_{i:04d}.rs"))
        for i in range(self.n_artifacts):
            script.append(ScriptStep(kind="write_file",
                                     path=f"target/mod_{i:04d}.rlib",
                                     size=self.artifact_size))
        script.append(ScriptStep(kind="fsync", path="target/final.so"))

        agent.reset(self.id, ctx.workdir)
        agent.set_script(script)

        t0 = time.perf_counter()
        max_step_ms = 0.0
        for step_idx in range(len(script) + 1):
            state = AgentState(task_id=self.id, turn=step_idx, cwd=ctx.workdir)
            action, obs = agent.step(state)
            max_step_ms = max(max_step_ms, obs.latency_ms)
            if not obs.ok:
                return TaskResult(self.id, self.category, state="FAILED",
                                  total_seconds=time.perf_counter() - t0,
                                  error=obs.error)
            if action.type == "done":
                break
        total = time.perf_counter() - t0

        result = TaskResult(
            task_id=self.id, category=self.category, state="COMPLETED",
            total_seconds=total, agent_metrics=agent.metrics(),
            trajectory_hash=agent.trajectory_hash(),
        )
        result.extra = {"n_files_read": self.n_source_files,
                        "n_files_written": self.n_artifacts,
                        "max_step_ms": max_step_ms}
        return result

    def verify(self, result: TaskResult, ctx: TaskContext) -> bool:
        if not result.passed:
            return False
        final = ctx.workdir / "target" / "final.so"
        return final.exists()
