"""
framework.tasks.realistic.repo_task
===================================
A task that runs a real agent on a real Git repository.

This is the *honest* end-to-end path: you point the framework at a
real Git URL + a real issue description, and we:
  1. git clone the repo into the SUT
  2. write the issue to .issue.md (read by OpencodeServerAgent)
  3. let the agent fix the issue
  4. run a real test command and parse pass/fail

For v0 we ship one example: a small public Python repo with a
known "fix a bug" exercise. The user can swap in any repo + any
issue via a runspec config.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..base import BaseTask, TaskContext, TaskResult
from ...agents.opencode_server import OpencodeServerAgent


@dataclass
class RealRepoTask:
    """Run an agent on a real git repo with a real issue + real tests.

    Configured via runspec.task_params or by setting fields directly
    in code. Example:
        RealRepoTask(
            repo_url="https://github.com/octocat/Hello-World",
            issue="Update the README to include a Hello section.",
            test_command="python -c \"print('ok')\"",
        )
    """
    id: str = "realistic/repo_task"
    category: str = "realistic"
    slo_seconds: float = 600.0
    description: str = "Run a real agent on a real repo with a real task."

    repo_url: str = ""
    issue: str = "Fix any issue you find in the code."
    test_command: str = "echo no-test-specified"
    expected_to_pass: bool = True
    agent_kind: str = "opencode-server"   # "opencode-server" | "scripted"
    depth: int = 1

    def setup(self, ctx: TaskContext) -> None:
        """git clone the repo into ctx.workdir. Write .issue.md."""
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        if self.repo_url:
            result = subprocess.run(
                ["git", "clone", "--depth", str(self.depth), self.repo_url, str(ctx.workdir)],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"git clone failed: {result.stderr}")
        # Always write the issue file (so the agent knows what to do)
        (ctx.workdir / ".issue.md").write_text(self.issue, encoding="utf-8")

    def run(self, agent, ctx: TaskContext) -> TaskResult:
        # Duck-type: must be a real opencode-style agent (not a scripted mock).
        if getattr(agent, "name", "") != "opencode-server":
            raise TypeError(
                f"RealRepoTask needs an OpencodeServerAgent (name='opencode-server'), "
                f"got name={getattr(agent, 'name', None)!r}. "
                "Real repos need a real agent; scripted mocks cannot edit code."
            )
        from framework.agents.base import AgentState
        agent.reset(self.id, ctx.workdir)
        t0 = time.perf_counter()
        last_action_type = None
        # The agent loops internally; we drive it until "done".
        for _ in range(500):  # safety cap
            state = AgentState(task_id=self.id, turn=agent._turn, cwd=ctx.workdir,
                               last_observation=str(agent.session_id))
            action, obs = agent.step(state)
            last_action_type = action.type
            if not obs.ok:
                return TaskResult(self.id, self.category, state="FAILED",
                                  total_seconds=time.perf_counter() - t0,
                                  error=obs.error or "agent step failed")
            if action.type == "done":
                break
        total = time.perf_counter() - t0
        result = TaskResult(
            task_id=self.id, category=self.category, state="COMPLETED",
            total_seconds=total, agent_metrics=agent.metrics(),
            trajectory_hash=agent.trajectory_hash(),
        )
        result.extra = {"final_action": last_action_type, "turns": agent._turn}
        return result

    def verify(self, result: TaskResult, ctx: TaskContext) -> bool:
        """Run the configured test command in the repo dir."""
        if not result.passed:
            return False
        try:
            proc = subprocess.run(
                self.test_command, shell=True, cwd=str(ctx.workdir),
                capture_output=True, text=True, timeout=300,
            )
            passed = (proc.returncode == 0) == self.expected_to_pass
            result.extra["test_rc"] = proc.returncode
            result.extra["test_stdout_tail"] = proc.stdout[-500:]
            return passed
        except subprocess.TimeoutExpired:
            result.error = "test_command timed out"
            return False
