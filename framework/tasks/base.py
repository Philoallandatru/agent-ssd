"""
framework.tasks.base
====================
The seam between "what to benchmark" and "the runner".

A task knows:
  - how to set up the SUT directory (write seed files, init git repo, etc.)
  - how to drive the agent to completion
  - how to verify the result
  - what its SLO is

Tasks are pure functions on the SUT path. They do not know about
the runner, the agent implementation, or the SSD.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Literal, Optional, Dict, Any
import time

from ..agents.base import BaseAgent, AgentMetrics, AgentState


Category = Literal["write_heavy", "read_heavy", "mixed", "shared", "extreme"]


@dataclass
class TaskContext:
    """Per-task setup state. Tasks fill this in setup()."""
    task_id: str
    sut_path: Path
    workdir: Path
    seeds: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """The verdict after a task completes."""
    task_id: str
    category: str
    state: str = "PENDING"            # COMPLETED | FAILED | MODEL_BEHAVIOR_DRIFT
    total_seconds: float = 0.0
    agent_metrics: Optional[AgentMetrics] = None
    trajectory_hash: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.state == "COMPLETED"


class BaseTask(Protocol):
    """A pluggable task. Five categories, one module per category."""
    id: str
    category: Category
    slo_seconds: float
    description: str

    def setup(self, ctx: TaskContext) -> None:
        """Write seed files, initialize state. Called once per run."""
        ...

    def run(self, agent: BaseAgent, ctx: TaskContext) -> TaskResult:
        """Drive the agent through the task. Return the verdict."""
        ...

    def verify(self, result: TaskResult, ctx: TaskContext) -> bool:
        """Sanity check: did the task actually finish, or just claim it did?"""
        ...
