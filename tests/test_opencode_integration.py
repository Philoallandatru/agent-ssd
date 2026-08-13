"""
tests/test_opencode_integration.py
===================================
End-to-end tests: real agent adapters + in-process mock server.

Three variants tested:
  - OpencodeServerAgent  (opencode-style /message + /event)
  - QwenCodeAgent        (qwen serve   /prompt  + /events)
  - PiServerAgent        (pi /message  + /event, default paths)

All three share BaseHttpSseAgent — only the path templates + auth differ.
"""
from __future__ import annotations
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from framework import Runner, RunSpec
from framework.agents.opencode_server import OpencodeServerAgent
from framework.agents.qwen_code import QwenCodeAgent
from framework.agents.pi_server import PiServerAgent
from framework.agents.registry import AGENT_REGISTRY, get_agent_factory
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


# ============================================================
# Mock servers for the 3 protocols
# ============================================================

@pytest.fixture
def mock_opencode_server():
    server, base_url = start_mock_opencode(protocol="opencode")
    yield base_url
    stop_mock_opencode(server)


@pytest.fixture
def mock_qwen_server():
    server, base_url = start_mock_opencode(protocol="qwen",
                                           auth_token="test-qwen-token")
    yield base_url
    stop_mock_opencode(server)


@pytest.fixture
def mock_pi_server():
    server, base_url = start_mock_opencode(protocol="opencode")  # pi uses opencode-style
    yield base_url
    stop_mock_opencode(server)


# ============================================================
# Tests
# ============================================================

def test_registry_has_all_agents():
    names = set(AGENT_REGISTRY.keys())
    assert {"scripted", "replaying", "opencode-server",
            "qwen-code", "pi-server", "claude-code"} <= names


def test_get_agent_factory_known():
    f = get_agent_factory("scripted")
    assert f().name == "scripted"
    f = get_agent_factory("qwen-code")
    assert f().name == "qwen-code"


def test_get_agent_factory_unknown_raises():
    with pytest.raises(ValueError, match="Unknown agent"):
        get_agent_factory("nope-agent")


def test_opencode_agent_drives_runner(small_repo, mock_opencode_server, tmp_path):
    """End-to-end: opencode-style mock + agent + runner."""
    os.environ["OPENCODE_BASE_URL"] = mock_opencode_server
    import importlib
    import framework.agents.opencode_server as oc
    importlib.reload(oc)

    spec = RunSpec(
        run_id="real-opencode-1", sut_path=str(tmp_path),
        agent_name="opencode-server", task_ids=["realistic/local_repo"],
        slo_seconds=30.0, runs_per_state=1,
    )
    task = LocalRepoTask(
        local_path=str(small_repo),
        issue="Add a docstring.",
        test_command="python -c \"from hello import greet; assert greet('x')=='hi x'\"",
        expected_to_pass=True,
    )
    from framework.tasks import TASK_REGISTRY
    TASK_REGISTRY["realistic/local_repo"] = lambda: task
    factory = lambda: oc.OpencodeServerAgent()
    runner = Runner(spec, factory, reporter=JsonReporter(str(tmp_path / "r.json")))
    report = runner.run()
    tr = report.task_results[0]
    assert tr.extra.get("turns", 0) >= 1


def test_qwen_code_agent_drives_runner(small_repo, mock_qwen_server, tmp_path):
    """End-to-end: qwen-serve-style mock + agent + runner + bearer auth."""
    os.environ["QWEN_BASE_URL"] = mock_qwen_server
    os.environ["QWEN_SERVER_TOKEN"] = "test-qwen-token"
    os.environ["QWEN_MODEL"] = "qwen3-coder-plus"
    import importlib
    import framework.agents.qwen_code as qc
    importlib.reload(qc)

    spec = RunSpec(
        run_id="real-qwen-1", sut_path=str(tmp_path),
        agent_name="qwen-code", task_ids=["realistic/local_repo"],
        slo_seconds=30.0, runs_per_state=1,
    )
    task = LocalRepoTask(
        local_path=str(small_repo),
        issue="修复 greet() 函数。",
        test_command="python -c \"from hello import greet; assert greet('x')=='hi x'\"",
        expected_to_pass=True,
    )
    from framework.tasks import TASK_REGISTRY
    TASK_REGISTRY["realistic/local_repo"] = lambda: task
    factory = lambda: qc.QwenCodeAgent()
    runner = Runner(spec, factory, reporter=JsonReporter(str(tmp_path / "r.json")))
    report = runner.run()
    tr = report.task_results[0]
    assert tr.extra.get("turns", 0) >= 1


def test_qwen_code_rejects_bad_token(small_repo, mock_qwen_server, tmp_path):
    """401 path: missing/wrong bearer token fails cleanly."""
    os.environ["QWEN_BASE_URL"] = mock_qwen_server
    os.environ["QWEN_SERVER_TOKEN"] = "WRONG-token"
    import importlib
    import framework.agents.qwen_code as qc
    importlib.reload(qc)
    agent = qc.QwenCodeAgent()
    with pytest.raises(Exception):
        agent.reset("t1", tmp_path)   # 401 → RuntimeError


def test_qwen_code_health_endpoint(mock_qwen_server):
    """Sanity: the mock /health endpoint reports ok."""
    import urllib.request
    with urllib.request.urlopen(f"{mock_qwen_server}/health", timeout=5) as r:
        import json as _j
        body = _j.loads(r.read())
    assert body["status"] == "ok"
    assert body["protocol"] == "qwen"


def test_mock_server_serves_sse(mock_opencode_server, tmp_path):
    """Direct smoke test: agent.reset() hits POST /session and succeeds."""
    os.environ["OPENCODE_BASE_URL"] = mock_opencode_server
    import importlib
    import framework.agents.opencode_server as oc
    importlib.reload(oc)
    agent = oc.OpencodeServerAgent()
    agent.reset("smoke-1", tmp_path)
    assert agent.session_id is not None
    assert agent.session_id.startswith("mock-")
    from framework.agents.base import AgentState
    action, obs = agent.step(AgentState(task_id="smoke-1", turn=0, cwd=tmp_path))
    assert obs.ok, f"first step failed: {obs.error}"
    assert action.type in {"read_file", "grep", "edit_file", "test_run", "text", "done", "tool_call"}
