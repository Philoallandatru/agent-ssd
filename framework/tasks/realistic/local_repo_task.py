"""
framework.tasks.realistic.local_repo_task
=========================================
A RealRepoTask variant that uses a *local* checkout of a repo instead
of git clone. Useful for testing the agent path without network.

Usage:
    local_repo = LocalRepoTask(
        local_path="/path/to/your/local/checkout",
        issue="Fix the bug in src/foo.py",
        test_command="pytest -q",
    )
"""
from __future__ import annotations
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ..base import BaseTask, TaskContext, TaskResult
from ...agents.opencode_server import OpencodeServerAgent
from ...agents.base import AgentState


@dataclass
class LocalRepoTask:
    """Run a real agent on a LOCAL repo. No network needed.

    The local repo is COPIED (not symlinked) into the SUT workdir so
    the agent's edits don't pollute the user's source tree.
    """
    id: str = "realistic/local_repo"
    category: str = "realistic"
    slo_seconds: float = 300.0
    description: str = "Run a real agent on a locally-checked-out repo."

    local_path: str = ""                    # absolute path to a real repo
    issue: str = "Inspect the code and tell me what it does."
    test_command: str = "echo no-test"
    expected_to_pass: bool = True

    def setup(self, ctx: TaskContext) -> None:
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        src = Path(self.local_path)
        if not src.exists():
            raise FileNotFoundError(f"local_path does not exist: {src}")
        # Copy the source tree into workdir (shallow, non-git)
        for item in src.iterdir():
            if item.name == ".git":
                continue
            target = ctx.workdir / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules"))
            else:
                shutil.copy2(item, target)
        (ctx.workdir / ".issue.md").write_text(self.issue, encoding="utf-8")

    def run(self, agent, ctx: TaskContext) -> TaskResult:
        # Duck-type: any agent with reset/step/trajectory_hash methods is OK.
        # We only require a `name` attribute to be an OpencodeServerAgent-like
        # (avoids running scripted mocks on real code).
        if getattr(agent, "name", "") != "opencode-server":
            raise TypeError(
                f"LocalRepoTask needs an OpencodeServerAgent (name='opencode-server'), "
                f"got name={getattr(agent, 'name', None)!r}"
            )
        agent.reset(self.id, ctx.workdir)
        t0 = time.perf_counter()
        last_action = None
        for _ in range(500):
            state = AgentState(task_id=self.id, turn=agent._turn,
                               cwd=ctx.workdir, last_observation=str(agent.session_id))
            action, obs = agent.step(state)
            last_action = action.type
            if not obs.ok:
                return TaskResult(self.id, self.category, state="FAILED",
                                  total_seconds=time.perf_counter() - t0,
                                  error=obs.error or "step failed")
            if action.type == "done":
                break
        total = time.perf_counter() - t0
        result = TaskResult(
            task_id=self.id, category=self.category, state="COMPLETED",
            total_seconds=total, agent_metrics=agent.metrics(),
            trajectory_hash=agent.trajectory_hash(),
        )
        result.extra = {"final_action": last_action, "turns": agent._turn}
        return result

    def verify(self, result: TaskResult, ctx: TaskContext) -> bool:
        if not result.passed:
            return False
        try:
            proc = subprocess.run(
                self.test_command, shell=True, cwd=str(ctx.workdir),
                capture_output=True, text=True, timeout=120,
            )
            passed = (proc.returncode == 0) == self.expected_to_pass
            result.extra["test_rc"] = proc.returncode
            result.extra["test_stdout_tail"] = proc.stdout[-500:]
            return passed
        except subprocess.TimeoutExpired:
            result.error = "test_command timed out"
            return False
