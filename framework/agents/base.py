"""
framework.agents.base
=====================
The seam between "any agent" and the benchmark harness.

A user agent (opencode, pi, custom) plugs in by subclassing BaseAgent
and implementing step(). The framework never calls the agent's LLM
directly — only step(), which must be deterministic given a Trajectory.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol
from pathlib import Path
import time


@dataclass
class AgentState:
    """What the agent sees at the start of a step."""
    task_id: str
    turn: int
    cwd: Path
    last_observation: Optional[str] = None
    scratch: dict = field(default_factory=dict)


@dataclass
class Action:
    """What the agent decides to do. The runner interprets the type."""
    type: str                     # e.g. "read_file", "bash", "fsync", "edit", "done"
    args: dict = field(default_factory=dict)


@dataclass
class Observation:
    """What the agent learns after the action runs."""
    ok: bool
    output: str = ""
    io_count: int = 0
    io_bytes: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None


class BaseAgent(Protocol):
    """A pluggable agent.

    The benchmark harness calls these three methods. Anything else
    (LLM calls, file handles, subprocesses) is the agent's business.
    """
    name: str

    def reset(self, task_id: str, cwd: Path) -> None:
        """Called once at the start of a task."""
        ...

    def step(self, state: AgentState) -> tuple[Action, Observation]:
        """Called once per turn. Must be deterministic given a fixed trajectory.

        Returns the action the agent chose, and the observation of running it.
        The observation's `io_count` and `io_bytes` are recorded by the harness
        regardless of the underlying filesystem semantics.
        """
        ...


@dataclass
class AgentMetrics:
    """Cumulative per-task metrics reported back by the agent."""
    total_steps: int = 0
    total_io_count: int = 0
    total_io_bytes: int = 0
    p99_step_ms: float = 0.0
    trajectory_hash: str = ""
