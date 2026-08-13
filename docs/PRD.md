# PRD: Agent Test Framework

> Status: v0.2 (real opencode serve integration shipped)
> Source: prototype at `_archive-agentssd-bench-prototype-v0/` (7 cases, all PASS)

## Problem Statement

从用户的角度:

当前 SSD 性能评测**只看 throughput**(fio),不看真实工作负载。**没有公开的、agent 工作负载专用的 SSD benchmark**。开发者用 opencode/pi 等 agent 写代码时,被 fsync 延迟、page cache 抖动、queue depth 退化坑了,但 SSD 厂商不认账(他们的 spec 数字是稳态跑出来的)。

**核心 gap**:
- fio 跑出的 IOPS/带宽 → 跟 agent 实际场景对不上
- 真实 agent 工作负载的 IO 模式 → 没有公开数据集
- 多 agent 协同场景(共享 git index/build cache)→ 测不出来
- 模型行为变化导致 IO 漂移 → 没法跟 SSD 性能变化区分开

需要一套**用真实 agent 跑测试**的框架,让用户能:
1. 拿一个 SSD,在 5 类高 IO 场景下跑 agent 任务
2. 拿到 SLO 准入指标(类似 MLPerf 的 Models @ SLO)
3. 同一 SSD 跑两次结果可重复(CoV < 10%)
4. 模型更新时,自动检测 IO 漂移

## Solution

**一个 Python 框架**,把 SSD benchmark 重构成:
```
┌──────────────┐
│ User Agent   │  ← 用户自己写 / 接 opencode / 接 pi
│ (pluggable)  │
└──────┬───────┘
       │ tool calls
       ▼
┌──────────────┐         ┌──────────────┐
│ Task Runner  │────────▶│ SUT SSD      │
│ (harness)    │         │ (待测)        │
└──────┬───────┘         └──────────────┘
       │
       ▼
┌──────────────┐
│ 5 类 Task    │  ← write_heavy / read_heavy / mixed / shared / extreme
│ (pluggable)  │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Reporters    │  ← console / json / parquet
└──────────────┘
```

**核心 seam**: `Task` 和 `Agent` 都是接口,用户可以替换任意一边。

**不是**: 重新造 SSD benchmark,而是给**现有的 SWE-bench / monorepo build 任务**包一层 harness,加上 IO 采集和 SLO 计算。

## User Stories

1. As an **SSD engineer**, I want to run a fixed set of agent tasks against my new SSD, so that I can measure its real-world performance vs. spec sheet numbers.

2. As an **SSD engineer**, I want to find the maximum N concurrent agents @ SLO, so that I can advertise an "Agents-per-SSD" admission number in my product datasheet.

3. As a **platform engineer**, I want to compare two SSDs head-to-head on identical tasks, so that I can make a procurement decision.

4. As a **storage researcher**, I want to replay the same agent trajectory on different SSDs, so that model-version noise doesn't pollute the benchmark.

5. As an **agent developer**, I want to record my agent's IO behavior, so that I can detect when a model update changes my agent's behavior (without me knowing).

6. As an **agent developer**, I want to drop my agent into the framework without rewriting it, so that I get benchmark results for free.

7. As a **QA lead**, I want to run the same suite twice and get CoV < 10%, so that I can trust the numbers.

8. As a **QA lead**, I want a baseline JSON report of "good NVMe" / "cheap SATA" / "AI NVMe" numbers, so that I can classify a new SSD into a tier.

9. As an **agent framework author** (opencode / pi / Claude Code), I want to publish my agent as a Task plug-in, so that your benchmark exercises my agent on real IO.

10. As a **storage researcher**, I want to feed the framework with IO traces from a 450-repo monorepo, so that I can replay real-world CI load.

11. As an **SSD engineer**, I want to measure cold-read penalty separately from warm-read, so that I can quantify the cache benefit.

12. As a **storage researcher**, I want to see fsync p99 latency under concurrent agent writes, so that I can validate my vendor's "no fsync stall" claim.

13. As a **platform engineer**, I want the framework to expose a "drop page cache" hook, so that I can isolate cold vs warm runs deterministically.

14. As an **agent developer**, I want my agent's session log to be written through a single File abstraction, so that the framework can substitute an in-memory FS for fast iteration.

15. As a **storage researcher**, I want to define new task categories (e.g. RAG / web browsing) without forking the framework, so that my research stays composable.

16. As an **SSD engineer**, I want a CLI that says "run this suite against /dev/nvme0n1", so that I can script the bench.

17. As a **QA lead**, I want a JSON report that contains the full RunSpec + every metric, so that I can diff two runs in CI.

18. As a **storage researcher**, I want to control page cache state, drop_caches, and QD limits independently, so that I can attribute bottlenecks to specific SSD features.

19. As an **agent developer**, I want to feed recorded trajectories (turn-by-turn IO plan) to the runner, so that the same model behavior is replayed on every SSD.

20. As an **SSD engineer**, I want a dashboard link to plot p99 latency per phase, so that I can see which phase (read / edit / build / test) breaks.

## Implementation Decisions

### Module structure

- `framework/agents/` — pluggable Agent interface. `BaseAgent` exposes `step(state) -> (action, observation)`. Concrete subclasses: `LocalCmdAgent` (shells out), `ReplayingAgent` (replays a recorded trajectory), `ScriptedAgent` (drives IO directly for prototype mode).
- `framework/tasks/` — pluggable Task interface. `BaseTask.setup(sut_path) -> ctx`, `BaseTask.run(agent, ctx) -> TaskResult`. Five categories, one module per category: `write_heavy/`, `read_heavy/`, `mixed/`, `shared/`, `extreme/`.
- `framework/harness/` — orchestration. `Runner` drives `prepare → run → verify → collect` state machine. `Collector` (eBPF / `iotop` wrapper — initially mocked).
- `framework/reporters/` — output. `JsonReporter` writes a complete `RunSpec + metrics` JSON, `ConsoleReporter` prints human-readable.
- `examples/` — concrete Agents. `opencode_agent.py`, `pi_agent.py`, `scripted_agent.py`.
- `configs/` — `runspec.yaml` examples.

### Key contracts (interfaces)

```python
class BaseAgent(Protocol):
    name: str
    def reset(self, task_ctx: TaskContext) -> None: ...
    def step(self, state: AgentState) -> tuple[Action, Observation]: ...

class BaseTask(Protocol):
    id: str
    category: Literal["write_heavy", "read_heavy", "mixed", "shared", "extreme"]
    slo_seconds: float
    def setup(self, sut_path: Path) -> TaskContext: ...
    def run(self, agent: BaseAgent, ctx: TaskContext) -> TaskResult: ...
    def verify(self, result: TaskResult) -> bool: ...
```

### State machine

Same as prototype: `PREPARING → STAGING → RUNNING → VERIFYING → COLLECTING → ANALYZING → COMPLETED|FAILED`. Crash recovery: any state can resume from disk (`run_state.json`).

### Trajectory (replay anchor)

`Trajectory = {task_id, model_card, model_version, turns: [(turn_id, tool, io_count, io_bytes, decision)]}`. Hash = `sha256(turns)[:16]`. **Model drift detection**: same RunSpec across days → if `hash(recorded) != hash(current)`, mark `MODEL_BEHAVIOR_DRIFT`.

### Metrics captured per task

- `total_seconds`, `p50/p95/p99/p99.9 io latency`
- `bytes_read`, `bytes_written`, `n_fsync`, `n_ios`
- `co_v` (CoV across 3+ runs)
- `trajectory_hash`, `trajectory_match`
- `page_cache_state` (COLD / WARM_CLEAN / WARM_DIRTY)
- `qd` (queue depth observed)

### SLO admission metric

`Agents-per-SSD @ p99 SLO` — find N* = max concurrent agents such that p99 task completion time ≤ SLO. Sweep N = 1, 2, 4, 8, 16, 32, 64, 128.

### Design decisions inherited from prototype v0

- **Trajectory > model card**: model card is a label, trajectory hash is the truth. A model update that doesn't change IO behavior is OK; one that does is detected.
- **Page cache states are independent**: cold / warm_clean / warm_dirty each report their own SLO; no averaging.
- **Placement profiles not mixed**: workspace-only / full-agent / multi-agent-swarm rank separately.
- **QD degradation is quadratic**: 1 / QD² scaling from prototype v0 case G2, not linear. Reflects real NVMe command-queue saturation.

### Concrete Task plugs (initial v0)

- **write_heavy/session_persist**: 100-turn scripted agent + per-turn `open(O_CREAT|O_SYNC)` fsync. Metrics: `n_fsync, fsync_p99`.
- **read_heavy/monorepo_search**: `ripgrep` over a generated 50k-file monorepo. Metrics: `read_iops, dirent_cache_misses`.
- **mixed/cargo_build**: spawn `cargo check` on a 1k-crate synthetic project. Metrics: `mixed_r_w_ratio, peak_bandwidth`.
- **shared/git_worktree**: 4 scripted agents each in their own `git worktree` running concurrent `cargo check`. Metrics: `lock_wait_ms, throughput_degradation`.
- **extreme/checkpoint_load**: 1-shot 7GB sequential read. Metrics: `seq_read_mbps, p99_latency`.

### Configuration

```yaml
# configs/runspec.example.yaml
run_id: nvme-ai-core12-001
sut_path: /mnt/sut
agent: scripted
tasks:
  - write_heavy/session_persist
  - read_heavy/monorepo_search
  - mixed/cargo_build
slo_seconds: 30
concurrency_sweep: [1, 2, 4, 8, 16]
page_cache_states: [COLD, WARM_CLEAN]
runs_per_state: 3
replay_trajectory: null   # path to recorded trajectory, or null
```

### Schema: `RunSpec` JSON

```json
{
  "schema": "runspec/v1",
  "run_id": "...",
  "sut_path": "...",
  "agent": {"name": "opencode", "version": "1.2.3"},
  "tasks": ["..."],
  "slo_seconds": 30.0,
  "concurrency": 1,
  "page_cache_state": "COLD",
  "replay": {"trajectory_path": null, "model_card": "gpt-4o-2024-08"}
}
```

## Testing Decisions

### What "good" means

- External behavior only. Test the **state machine transitions** and the **pluggable contracts**, not the IO statistics of a specific SSD.
- A test must pass on any Linux box with a synthetic SUT directory under `/tmp/agentssd-test-*` — no real SSD required.
- A test must NOT depend on opencode/pi being installed (mock the Agent).

### Modules tested

- `framework/agents/base.py` — interface contract
- `framework/tasks/base.py` — interface contract
- `framework/harness/runner.py` — state machine, crash recovery
- `framework/tasks/write_heavy/session_persist.py` — fsync counting
- `framework/tasks/read_heavy/monorepo_search.py` — IO counting, dirent cache miss logic

### Prior art

- prototype v0's `test_repeatability` (CoV < 10% across 3 runs)
- prototype v0's `test_model_drift` (hash divergence on v1 → v2)
- prototype v0's `test_replay_fidelity` (3 replays, identical hash)

## Out of Scope (v0.2 → v1)

- **Real eBPF collector** — v0.2 mocks via `iotop` wrapper. Real `bcc` / `bpftrace` integration is v1.
- **Real NVMe telemetry** — v0.2 reads `iotop` output. Vendor log (`nvme smart-log`) parsing is v1.
- **Windows support** — Linux only. Page cache drop is via `drop_caches` (Linux) or `SetSystemFileCacheSize` (Windows, v1).
- **Distributed controller** — v0.2 is single-host. v1: N workers.
- **Dashboard** — v0.2 emits JSON + console. Streamlit dashboard is v1.
- **MLPerf Storage compatibility** — v0.2 is a separate suite. Cross-mapping is a research project.

## v0.2 Changelog (incremental, on top of v0.1)

- **NEW** `framework/agents/opencode_server.py` — real adapter for `opencode serve`. POSTs to `/session`, GETs `/session/:id/event` SSE, parses `tool_call` / `tool_result` / `text` / `done`. Configurable via `OPENCODE_BASE_URL` env var.
- **NEW** `framework/testing/mock_opencode.py` — in-process `ThreadingHTTPServer` that mimics `opencode serve`. Streams canned `tool_call` events. Used for CI / local testing without an LLM.
- **NEW** `framework/tasks/realistic/repo_task.py` — `RealRepoTask`: `git clone` a real repo, write `.issue.md`, let a real agent fix it, run a real test command.
- **NEW** `framework/tasks/realistic/local_repo_task.py` — `LocalRepoTask`: same as above but uses a local checkout (no network). Copies the repo into the SUT.
- **NEW** `examples/run_opencode_agent.py` — end-to-end demo: starts mock server, points `OpencodeServerAgent` at it, runs `LocalRepoTask` on a tiny repo, prints the report.
- **NEW** `configs/real_opencode.yaml` — runspec for the realistic path.
- **NEW** `tests/test_opencode_integration.py` — 2 pytest tests: agent E2E through runner + direct mock-server smoke.
- **CHANGE** `framework/agents/__init__.py` / `framework/__init__.py` — re-export `OpencodeServerAgent`.
- **CHANGE** `framework/tasks/__init__.py` — register `realistic/repo_task` and `realistic/local_repo`.
- **CHANGE** `TASK_REGISTRY` now has 7 task IDs across 6 categories.

## Further Notes

- **Source of truth for design**: prototype v0 (`_archive-agentssd-bench-prototype-v0/NOTES.md`) — 7 design questions, all answered PASS. Read that first.
- **Source of truth for IO patterns**: external benchmarks enumerated in `agentssd-bench-prototype/NOTES.md` §5 (ContextBench IO profile, MLPerf Storage v2.0 checkpoints, ooderAgent Skills, AIDev PR distribution, Block monorepo).
- **Why v0 isn't production-grade**: by design. The goal is to validate the **pluggable seams** before any eBPF / vendor integration.
- **Where to start**: `examples/scripted_agent.py` + `framework/tasks/write_heavy/session_persist.py` + a one-task `runspec.yaml`. That combination exercises Agent + Task + Runner end-to-end.
