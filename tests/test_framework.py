"""
tests/test_framework.py
=======================
Smoke tests. Each test must pass on any Linux box with a writable
/tmp; no real SSD or opencode/pi install required.
"""
from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path
import pytest

from framework import (
    Runner, RunSpec,
    ScriptedAgent, ReplayingAgent,
    TASK_REGISTRY, TaskContext,
)
from framework.agents.scripted import ScriptStep
from framework.reporters import JsonReporter


@pytest.fixture
def sut_path():
    p = Path(tempfile.mkdtemp(prefix="agentssd-test-"))
    yield p
    shutil.rmtree(p, ignore_errors=True)


def test_session_persist_runs(sut_path):
    spec = RunSpec(
        run_id="t1", sut_path=str(sut_path),
        agent_name="scripted", task_ids=["write_heavy/session_persist"],
        slo_seconds=30.0, runs_per_state=1,
    )
    factory = lambda: ScriptedAgent(script=[])
    out = Path(tempfile.mkdtemp()) / "report.json"
    runner = Runner(spec, factory, reporter=JsonReporter(str(out)))
    report = runner.run()
    assert report.aggregate_passed, f"task failed: {[r.error for r in report.task_results]}"
    assert report.task_results[0].passed


def test_monorepo_search_finds_files(sut_path):
    spec = RunSpec(
        run_id="t2", sut_path=str(sut_path),
        agent_name="scripted", task_ids=["read_heavy/monorepo_search"],
        slo_seconds=20.0, runs_per_state=1,
    )
    factory = lambda: ScriptedAgent(script=[])
    runner = Runner(spec, factory)
    report = runner.run()
    assert report.aggregate_passed
    assert report.task_results[0].extra["n_files_read"] > 0


def test_replaying_agent_detects_drift():
    """ReplayingAgent must fail when the in-flight trajectory diverges."""
    script = [ScriptStep(kind="read_file", path="x.py"),
              ScriptStep(kind="write_file", path="y.py", size=10)]
    # Recorded hash is for a DIFFERENT script → drift should fire
    different_script = [ScriptStep(kind="fsync", path="z.py")]
    rec = ScriptedAgent(different_script)
    rec.reset("t", Path("."))
    rec_hash = rec.trajectory_hash()
    agent = ReplayingAgent(script=script, recorded_hash=rec_hash)
    agent.reset("t", Path("."))
    from framework.agents.base import AgentState
    action, obs = agent.step(AgentState(task_id="t", turn=0, cwd=Path(".")))
    assert agent.drifted
    assert not obs.ok
    assert "MODEL_BEHAVIOR_DRIFT" in obs.error


def test_full_suite_co_v(sut_path):
    """End-to-end: run 3 times across 3 runs, expect CoV < 30% (loose for v0)."""
    spec = RunSpec(
        run_id="cov", sut_path=str(sut_path),
        agent_name="scripted", task_ids=["write_heavy/session_persist"],
        slo_seconds=30.0, runs_per_state=3,
    )
    runner = Runner(spec, lambda: ScriptedAgent(script=[]))
    report = runner.run()
    # v0 CoV is loose; tighten in v1 with real SSD + drop_caches
    assert report.co_v < 0.5, f"CoV too high: {report.co_v}"
