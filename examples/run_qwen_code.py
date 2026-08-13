#!/usr/bin/env python3
"""
examples/run_qwen_code.py
=========================
Run the framework against a REAL `qwen serve` daemon.

What it does:
  1. Verifies qwen serve is reachable (default http://127.0.0.1:4170).
  2. Sets up QWEN_BASE_URL + QWEN_SERVER_TOKEN from env.
  3. Builds a tiny local repo (a hello-world Python file).
  4. Drives QwenCodeAgent on it via a LocalRepoTask.
  5. Prints the report.

Prerequisites:
  - qwen code installed (`npm i -g @qwen-code/qwen-code`)
  - You started a server in another terminal:
        qwen serve --port 4170 --token $MY_TOKEN
    (set QWEN_SERVER_TOKEN to the same value)
  - OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL already set in env
    (per qwen-code setup; the daemon inherits them)

Run:
    export QWEN_SERVER_TOKEN="<whatever you passed to --token>"
    python examples/run_qwen_code.py
"""
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from framework import Runner, RunSpec
from framework.agents.qwen_code import QwenCodeAgent
from framework.tasks.realistic.local_repo_task import LocalRepoTask
from framework.reporters import ConsoleReporter
from framework.tasks import TASK_REGISTRY


def check_qwen_alive(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=3) as r:
            import json as _j
            body = _j.loads(r.read())
        print(f"  qwen serve OK at {base_url}  protocol={body.get('protocol')}")
        return True
    except (urllib.error.URLError, ConnectionError) as e:
        print(f"  qwen serve NOT reachable at {base_url}: {e}")
        return False


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
    base_url = os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:4170")
    token = os.environ.get("QWEN_SERVER_TOKEN")
    if not token:
        print("ERROR: set QWEN_SERVER_TOKEN env var (must match the --token you passed to qwen serve).")
        sys.exit(2)

    print(f"QWEN_BASE_URL: {base_url}")
    print(f"QWEN_MODEL:    {os.environ.get('QWEN_MODEL', 'qwen3-coder-plus')}")
    print(f"QWEN_TOKEN:    {'set (' + str(len(token)) + ' chars)' if token else 'MISSING'}")
    if not check_qwen_alive(base_url):
        print("\nStart qwen serve in another terminal, e.g.:")
        print(f"  qwen serve --port 4170 --token {token[:4]}...")
        sys.exit(3)

    work = Path(tempfile.mkdtemp(prefix="agent-qwen-demo-"))
    print(f"\nworkdir: {work}")
    repo = make_tiny_repo(work)
    print(f"local repo: {repo}")

    spec = RunSpec(
        run_id="qwen-demo-001",
        sut_path=str(work),
        agent_name="qwen-code",
        task_ids=["realistic/local_repo"],
        slo_seconds=120.0,
        runs_per_state=1,
    )
    task = LocalRepoTask(
        local_path=str(repo),
        issue="Add a docstring to greet() explaining what it does.",
        test_command="python -c \"from hello import greet; assert greet('x')=='hi x'\"",
        expected_to_pass=True,
    )
    TASK_REGISTRY["realistic/local_repo"] = lambda: task

    try:
        runner = Runner(
            spec,
            agent_factory=lambda: QwenCodeAgent(),
            reporter=ConsoleReporter(verbose=True),
        )
        report = runner.run()
        print()
        print("=== Report ===")
        print(f"aggregate_passed: {report.aggregate_passed}")
        for r in report.task_results:
            print(f"  {r.task_id}: {r.state}  {r.total_seconds:.2f}s  "
                  f"turns={r.extra.get('turns')}  err={r.error or 'ok'}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
