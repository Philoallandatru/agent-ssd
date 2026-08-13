#!/usr/bin/env python3
"""
examples/run_opencode_agent.py
==============================
End-to-end demo: spin up a mock opencode server, point the framework's
real OpencodeServerAgent at it, run a LocalRepoTask on a tiny local
Python repo, print the report.

This proves the *real* integration path: agent -> HTTP -> SSE -> task.
Swap MOCK=1 for MOCK=0 and point OPENCODE_BASE_URL at a real
`opencode serve` to run against the real opencode-ai CLI.

Run:
    python examples/run_opencode_agent.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add the project root to sys.path so `framework` is importable
HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from framework import Runner, RunSpec
from framework.agents.opencode_server import OpencodeServerAgent
from framework.tasks.realistic.local_repo_task import LocalRepoTask
from framework.reporters import ConsoleReporter, JsonReporter
from framework.testing.mock_opencode import start_mock_opencode, stop_mock_opencode


def make_tiny_repo(parent: Path) -> Path:
    repo = parent / "tiny_repo"
    repo.mkdir(exist_ok=True)
    (repo / "hello.py").write_text(
        'def greet(name: str) -> str:\n'
        '    """Say hi."""\n'
        '    return f"hi {name}"\n',
        encoding="utf-8",
    )
    (repo / "test_hello.py").write_text(
        'from hello import greet\n'
        'def test_greet():\n'
        '    assert greet("world") == "hi world"\n',
        encoding="utf-8",
    )
    return repo


def main():
    work = Path(tempfile.mkdtemp(prefix="agent-demo-"))
    print(f"workdir: {work}")

    repo = make_tiny_repo(work)
    print(f"local repo: {repo}")

    # Start mock opencode server
    server, base_url = start_mock_opencode(host="127.0.0.1")
    print(f"mock opencode server at: {base_url}")

    # Configure the agent
    os.environ["OPENCODE_BASE_URL"] = base_url

    # Re-import so the dataclass field default reads env
    import importlib
    import framework.agents.opencode_server as oc
    importlib.reload(oc)

    spec = RunSpec(
        run_id="demo-001",
        sut_path=str(work),
        agent_name="opencode-server",
        task_ids=["realistic/local_repo"],
        slo_seconds=30.0,
        runs_per_state=1,
    )
    # Build a configured LocalRepoTask and inject into the registry
    task = LocalRepoTask(
        local_path=str(repo),
        issue="Add a docstring to greet() and run the tests.",
        test_command="python -c \"from hello import greet; assert greet('x')=='hi x'\"",
        expected_to_pass=True,
    )
    from framework.tasks import TASK_REGISTRY
    TASK_REGISTRY["realistic/local_repo"] = lambda: task

    try:
        runner = Runner(
            spec,
            agent_factory=lambda: oc.OpencodeServerAgent(),
            reporter=ConsoleReporter(verbose=True),
        )
        report = runner.run()
        print()
        print("=== Report ===")
        print(f"aggregate_passed: {report.aggregate_passed}")
        print(f"worst CoV across tasks: {report.co_v * 100:.2f}%")
        for r in report.task_results:
            print(f"  {r.task_id}: {r.state}  {r.total_seconds:.3f}s  turns={r.extra.get('turns')}")
    finally:
        stop_mock_opencode(server)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
