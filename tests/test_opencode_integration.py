"""
tests/test_opencode_integration.py
===================================
End-to-end test: real agent adapter + mock opencode server.

This is the proof that the v0.2 design works: the OpencodeServerAgent
talks HTTP+SSE to a real (mock) server, parses events, and produces
Action/Observation that the Runner can drive through the state machine.
"""
from __future__ import annotations
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from framework import Runner, RunSpec
from framework.agents.opencode_server import OpencodeServerAgent
from framework.tasks.realistic.local_repo_task import LocalRepoTask
from framework.reporters import JsonReporter
from framework.testing.mock_opencode import start_mock_opencode, stop_mock_opencode


@pytest.fixture
def sut_path():
    p = Path(tempfile.mkdtemp(prefix="agentssd-real-"))
    yield p
    shutil.rmtree(p, ignore_errors=True)


@pytest.fixture
def small_repo(sut_path):
    """Create a tiny real local repo with one Python file."""
    repo = sut_path / "src_repo"
    repo.mkdir()
    (repo / "hello.py").write_text(
        'def greet(name: str) -> str:\n'
        '    return f"hi {name}"\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    print(greet("world"))\n',
        encoding="utf-8",
    )
    (repo / "test_hello.py").write_text(
        'from hello import greet\n'
        'def test_greet():\n'
        '    assert greet("world") == "hi world"\n',
        encoding="utf-8",
    )
    return repo


@pytest.fixture
def mock_server():
    server, base_url = start_mock_opencode()
    yield base_url
    stop_mock_opencode(server)


def test_opencode_agent_drives_runner(small_repo, mock_server, tmp_path):
    """End-to-end: runner + opencode server agent + local repo task."""
    # Point the agent at our mock server
    os.environ["OPENCODE_BASE_URL"] = mock_server
    os.environ["OPENCODE_MODEL"] = "mock-model"
    # Re-import the agent class so dataclass defaults re-read env
    import importlib
    import framework.agents.opencode_server as oc
    importlib.reload(oc)

    spec = RunSpec(
        run_id="real-1",
        sut_path=str(tmp_path),
        agent_name="opencode-server",
        task_ids=["realistic/local_repo"],
        slo_seconds=30.0,
        runs_per_state=1,
    )
    task = LocalRepoTask(
        local_path=str(small_repo),
        issue="Add a docstring to greet().",
        test_command="python -c \"from hello import greet; assert greet('x')=='hi x'\"",
        expected_to_pass=True,
    )
    # Patch the registry to use this configured task
    from framework.tasks import TASK_REGISTRY
    TASK_REGISTRY["realistic/local_repo"] = lambda: task

    factory = lambda: oc.OpencodeServerAgent()
    out = tmp_path / "report.json"
    runner = Runner(spec, factory, reporter=JsonReporter(str(out)))
    report = runner.run()

    # The mock server's canned events don't actually edit files, but the
    # agent path must run end-to-end without crashing. verify() may fail
    # because the test command depends on real code edits.
    assert len(report.task_results) == 1
    tr = report.task_results[0]
    # The agent looped at least one tool_call before "done"
    assert tr.extra.get("turns", 0) >= 1, f"expected at least 1 turn, got {tr.extra}"


def test_mock_server_serves_sse(small_repo, mock_server, tmp_path):
    """Direct smoke test: agent.reset() hits POST /session and succeeds."""
    os.environ["OPENCODE_BASE_URL"] = mock_server
    import importlib
    import framework.agents.opencode_server as oc
    importlib.reload(oc)
    agent = oc.OpencodeServerAgent()
    agent.reset("smoke-1", tmp_path)
    assert agent.session_id is not None
    assert agent.session_id.startswith("mock-")
    # step() should drain an event from the stream
    from framework.agents.base import AgentState
    action, obs = agent.step(AgentState(task_id="smoke-1", turn=0, cwd=tmp_path))
    assert obs.ok, f"first step failed: {obs.error}"
    assert action.type in {"read_file", "grep", "edit_file", "test_run", "text", "done", "tool_call"}
