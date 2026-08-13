"""
framework.harness.runner
========================
The orchestrator. Drives a single Task through the state machine.

This is intentionally small. The interesting logic lives in
  - state_machine.py (transitions, persistence)
  - reporters/ (output)
  - tasks/*/        (the actual work)
"""

from __future__ import annotations
import json
import shutil
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any

from .state_machine import StateMachine, State
from ..tasks.base import TaskContext, TaskResult
from ..tasks import TASK_REGISTRY, BaseTask
from ..agents.base import BaseAgent


@dataclass
class RunSpec:
    """The input to a runner. Plain dict-like for YAML loading."""
    run_id: str
    sut_path: str                          # path to the disk under test
    agent_name: str                        # "scripted" | "replaying" | "opencode" | "pi"
    task_ids: List[str]                    # e.g. ["write_heavy/session_persist"]
    slo_seconds: float = 30.0
    page_cache_state: str = "WARM_CLEAN"   # COLD | WARM_CLEAN | WARM_DIRTY
    runs_per_state: int = 3
    replay_trajectory_path: Optional[str] = None
    model_card: str = "scripted-v0"

    @classmethod
    def from_dict(cls, d: dict) -> "RunSpec":
        return cls(**d)


@dataclass
class RunReport:
    """The full output of a run. One per RunSpec."""
    run_id: str
    runspec: Dict[str, Any]
    started_at: float
    finished_at: float = 0.0
    state_machine_history: List[Dict] = field(default_factory=list)
    task_results: List[TaskResult] = field(default_factory=list)
    co_v: float = 0.0                       # worst CoV across tasks
    co_v_by_task: Dict[str, float] = field(default_factory=dict)
    aggregate_passed: bool = False

    def to_dict(self) -> Dict:
        d = {
            "run_id": self.run_id,
            "runspec": self.runspec,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "co_v": self.co_v,
            "aggregate_passed": self.aggregate_passed,
            "state_history": self.state_machine_history,
            "task_results": [
                {
                    "task_id": r.task_id, "category": r.category,
                    "state": r.state, "total_seconds": r.total_seconds,
                    "trajectory_hash": r.trajectory_hash,
                    "error": r.error, "extra": r.extra,
                } for r in self.task_results
            ],
        }
        return d


class Runner:
    """Drives one RunSpec through the state machine and produces a RunReport."""

    def __init__(self, runspec: RunSpec, agent_factory, reporter=None):
        """
        agent_factory: callable() -> BaseAgent
        reporter: optional reporter implementing `on_event(name, payload)`
        """
        self.runspec = runspec
        self.agent_factory = agent_factory
        self.reporter = reporter

    def _emit(self, name: str, payload: dict) -> None:
        if self.reporter is not None:
            self.reporter.on_event(name, payload)

    def run(self) -> RunReport:
        report = RunReport(
            run_id=self.runspec.run_id,
            runspec=asdict(self.runspec),
            started_at=time.time(),
        )

        # Resolve tasks once
        tasks: List[BaseTask] = [TASK_REGISTRY[tid]() for tid in self.runspec.task_ids]

        # Per-task-run state machine. Each task-run = one full lifecycle.
        # The runner itself doesn't share state across task-runs.
        all_times: List[float] = []
        for task in tasks:
            for run_idx in range(self.runspec.runs_per_state):
                sm = StateMachine(run_id=f"{self.runspec.run_id}/{task.id}#{run_idx}")
                ctx = TaskContext(
                    task_id=task.id,
                    sut_path=Path(self.runspec.sut_path),
                    workdir=Path(tempfile.mkdtemp(prefix=f"agentssd-{task.id.replace('/', '_')}-")),
                )
                try:
                    sm.transition(State.PREPARING, note="start")
                    self._emit("state", {"state": State.PREPARING.value})
                    sm.transition(State.STAGING, note="setup")
                    self._emit("state", {"state": State.STAGING.value})
                    self._emit("task_start", {"task_id": task.id, "run_idx": run_idx})
                    task.setup(ctx)

                    sm.transition(State.RUNNING, note=f"run #{run_idx}")
                    self._emit("state", {"state": State.RUNNING.value})
                    agent = self.agent_factory()
                    result = task.run(agent, ctx)

                    sm.transition(State.VERIFYING, note=f"verify")
                    self._emit("state", {"state": State.VERIFYING.value})
                    ok = task.verify(result, ctx)
                    if not ok and result.error is None:
                        result.error = "verify() returned False"
                    if not ok:
                        result.state = "FAILED"

                    sm.transition(State.COLLECTING, note="collect")
                    sm.transition(State.ANALYZING, note="analyze")
                    sm.transition(State.COMPLETED if result.passed else State.FAILED,
                                  note="end of task-run")
                    all_times.append(result.total_seconds)
                    report.task_results.append(result)
                    report.state_machine_history.append(
                        {"task": task.id, "run": run_idx, "transitions": sm.history}
                    )
                    self._emit("task_end", {
                        "task_id": task.id, "run_idx": run_idx,
                        "state": result.state,
                        "total_seconds": result.total_seconds,
                        "error": result.error,
                    })
                finally:
                    # Clean up the per-run workdir (the SUT itself is preserved)
                    shutil.rmtree(ctx.workdir, ignore_errors=True)

        report.finished_at = time.time()
        # Compute CoV per task. Mixing all task times into one CoV is meaningless
        # because they have different orders of magnitude.
        by_task: Dict[str, List[float]] = {}
        for r in report.task_results:
            by_task.setdefault(r.task_id, []).append(r.total_seconds)
        worst_cov = 0.0
        for tid, times in by_task.items():
            if len(times) >= 2:
                mean = sum(times) / len(times)
                if mean > 0:
                    variance = sum((t - mean) ** 2 for t in times) / len(times)
                    cov = (variance ** 0.5) / mean
                    report.co_v_by_task[tid] = cov
                    worst_cov = max(worst_cov, cov)
        report.co_v = worst_cov
        report.aggregate_passed = all(r.passed for r in report.task_results)
        self._emit("run_complete", {
            "run_id": self.runspec.run_id,
            "aggregate_passed": report.aggregate_passed,
            "co_v": report.co_v,
        })
        return report
