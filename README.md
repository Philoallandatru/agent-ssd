# Agent Test Framework (v0.2)

> Status: v0.2 — real `opencode serve` integration shipped.
> The design rationale lives in `docs/PRD.md`. The throwaway design-validation
> prototype that produced this design lives at
> `../_archive-agentssd-bench-prototype-v0/`.

## What this is

A Python framework where:
- **Tasks** are pluggable (6 categories: write_heavy, read_heavy, mixed, shared, extreme, **realistic**)
- **Agents** are pluggable:
  - `ScriptedAgent` — deterministic in-process agent (mock, fast)
  - `ReplayingAgent` — asserts trajectory hash matches recorded (drift detection)
  - **`OpencodeServerAgent` — real adapter for `opencode serve`** (HTTP + SSE)
- **Reporters** are pluggable (Console + JSON shipped)
- **The runner** is a state machine that persists so a crashed run can resume

The framework is the v0.2 deliverable. v0.1 validated the plug-in seams
in isolation; **v0.2 adds the realistic end-to-end path** —
`opencode serve` (real) talking to a real git repo via a real task.

## Quick start

```bash
# 1. Run the smallest example (1 task, 3 runs, scripted agent)
python -m framework.cli --config configs/example.yaml

# 2. Or the full suite (5 tasks × 3 runs, scripted)
python -m framework.cli --config configs/full_suite.yaml

# 3. The realistic path: real opencode serve + real repo
#    Step A: install opencode-ai
#            npm i -g opencode-ai
#    Step B: in one terminal, start the server
#            opencode serve --port 9999
#    Step C: in another terminal, run the framework
#            OPENCODE_BASE_URL=http://127.0.0.1:9999 \
#                python examples/run_opencode_agent.py

# 4. No opencode installed? Use the in-process mock (no LLM needed)
python examples/run_opencode_agent.py     # uses MockOpencodeServer
```

## Architecture (v0.2)

```
User (you)
   |
   v
RunSpec (YAML) -> Runner -> per-task StateMachine
                       |
                       v
                    BaseAgent  (pluggable)
                       |
        +--------------+--------------+
        |              |              |
  ScriptedAgent  ReplayingAgent  OpencodeServerAgent
   (in-process)   (drift detect)  (real opencode serve
                                   via HTTP + SSE)
                       |
                       v
                   BaseTask   (pluggable)
                       |
   +-------+-------+-------+-------+-------+
   |       |       |       |       |       |
write  read    mixed  shared extreme realistic
                                        |
                                  real git repo
                                  (clone / local)
```

## Two ways to plug a real agent

### Way 1: real opencode-ai (production)
```bash
npm i -g opencode-ai
opencode serve --port 9999        # background
OPENCODE_BASE_URL=http://127.0.0.1:9999 python examples/run_opencode_agent.py
```

The `OpencodeServerAgent` (in `framework/agents/opencode_server.py`)
- POSTs to `/session` to create a session bound to the repo cwd
- POSTs the task prompt (from `.issue.md`) to `/session/:id/message`
- GETs `/session/:id/event` and parses the SSE stream
- Translates `tool_call` / `tool_result` / `text` / `done` events
  into `Action` / `Observation` for the framework

### Way 2: mock (no LLM, no install, fast)
`examples/run_opencode_agent.py` defaults to this. It starts an
in-process `MockOpencodeServer` that streams a canned sequence of
events. Same code path as Way 1 — just swap the URL.

## Plug in any agent (opencode / qwen-code / pi / claude-code)

The framework ships adapters for the popular CLI agents that expose an
HTTP+SSE server. They all share `BaseHttpSseAgent` — the only differences
are path templates and auth.

| Agent       | Default URL              | Auth             | Adapter                |
|-------------|--------------------------|------------------|------------------------|
| opencode    | `http://127.0.0.1:9999`  | (none)           | `OpencodeServerAgent`  |
| qwen-code   | `http://127.0.0.1:4170`  | Bearer token     | `QwenCodeAgent`        |
| pi          | `http://127.0.0.1:7742`  | (none, override) | `PiServerAgent`        |
| claude-code | `http://127.0.0.1:7842`  | `x-api-key`      | `ClaudeCodeAgent`      |

**Pick at runtime** via `--agent` (CLI) or `RunSpec.agent_name`:

```bash
# Mock mode (no LLM, no install, fast)
python examples/run_opencode_agent.py

# Real opencode serve
OPENCODE_BASE_URL=http://127.0.0.1:9999 python examples/run_opencode_agent.py

# Real qwen-code (you've got it installed already)
export QWEN_SERVER_TOKEN="<your --token>"
qwen serve --port 4170 --token "$QWEN_SERVER_TOKEN"   # another terminal
python examples/run_qwen_code.py
```

**Adding a new agent** is a one-liner — subclass `BaseHttpSseAgent`
and override the 3 path class attributes:

```python
from framework.agents.http_sse import BaseHttpSseAgent

class MyAgent(BaseHttpSseAgent):
    name = "my-agent"
    session_create_path  = "/api/new_session"
    session_message_path = "/api/new_session/{sid}/send"
    session_event_path   = "/api/new_session/{sid}/stream"
    def __init__(self): super().__init__(base_url="http://localhost:9000")

from framework.agents.registry import AGENT_REGISTRY
AGENT_REGISTRY["my-agent"] = MyAgent
```

That's it. Now `--agent my-agent` works everywhere.

## Plug a new task in

```python
# framework/tasks/realistic/my_swe_bench.py
from framework.tasks.base import BaseTask, TaskContext, TaskResult
from dataclasses import dataclass

@dataclass
class MySweBenchTask:
    id: str = "realistic/swe_bench_001"
    category: str = "realistic"
    slo_seconds: float = 600.0
    description: str = "Fix a SWE-bench issue."

    instance_id: str = "django__django-12345"

    def setup(self, ctx): ...   # git checkout the SWE-bench repo
    def run(self, agent, ctx) -> TaskResult: ...
    def verify(self, result, ctx) -> bool: ...   # run SWE-bench's tests

# framework/tasks/__init__.py:
# TASK_REGISTRY["realistic/swe_bench_001"] = MySweBenchTask
```

## Test it

```bash
pip install -e .[dev]
pytest tests/ -v
# 6/6 PASS: 4 framework smoke tests + 2 opencode-integration tests
```

## Layout

```
agent-test-framework/
├── docs/PRD.md                       # design rationale
├── framework/
│   ├── agents/                       # BaseAgent + ScriptedAgent
│   │                                 # + ReplayingAgent
│   │                                 # + OpencodeServerAgent   (v0.2)
│   ├── tasks/
│   │   ├── write_heavy/              # session_persist
│   │   ├── read_heavy/               # monorepo_search
│   │   ├── mixed/                    # cargo_build
│   │   ├── shared/                   # git_worktree
│   │   ├── extreme/                  # checkpoint_load
│   │   └── realistic/                # repo_task, local_repo_task (v0.2)
│   ├── harness/                      # state machine + runner
│   ├── reporters/                    # console + json
│   ├── testing/                      # MockOpencodeServer (v0.2)
│   └── cli.py
├── examples/                         # opencode/pi/scripted adapters
│                                     # + run_opencode_agent.py (v0.2)
├── configs/                          # YAML runspecs (incl. real_opencode.yaml)
└── tests/
    ├── test_framework.py            # smoke (4 tests)
    └── test_opencode_integration.py # mock-server E2E (2 tests)
```

## What v0.2 does NOT do (yet)

- **Real eBPF collector** — v0.2: iotop / sub-process IO counts. Real
  `bcc`/`bpftrace` integration is v1.
- **Real NVMe telemetry** — v0.2: filesystem metrics only. Vendor
  log (`nvme smart-log`) parsing is v1.
- **Windows support** — v0.2: Linux only. Page cache drop is via
  `drop_caches` (Linux) or `SetSystemFileCacheSize` (Windows, v1).
- **Distributed controller** — v0.2: single host. v1: N workers.
- **Streamlit dashboard** — v0.2: JSON output + console. v1: dashboard.
- **Opencode SDK upgrade** — v0.2 uses raw urllib + SSE. v1 may switch
  to the official `@opencode-ai/sdk/v2` client (JS shim or HTTP copy).

These are explicit in `docs/PRD.md` § "Out of Scope".
# agent-ssd
