"""
framework.agents.scripted
=========================
A deterministic, in-process agent that drives IO directly.

This is the default for v0. It:
  - reads a "script" of (tool, args) actions
  - performs the corresponding IO on the SUT directory
  - records per-step io_count / io_bytes
  - yields a stable trajectory hash for replay

Real agents (opencode, pi) plug in by subclassing BaseAgent.
"""

from __future__ import annotations
import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from .base import BaseAgent, AgentState, Action, Observation, AgentMetrics


@dataclass
class ScriptStep:
    """One scripted action. `kind` matches Action.type."""
    kind: str                      # "read_file" | "write_file" | "fsync" | "edit_file" | "bash" | "done"
    path: str = ""
    content: str = ""
    size: int = 0                  # for synthetic content


class ScriptedAgent(BaseAgent):
    """An agent that walks a fixed script. Replayable, deterministic."""

    name = "scripted"

    def __init__(self, script: List[ScriptStep] = None):
        self.script = script or []
        self._cursor = 0
        self._metrics = AgentMetrics()
        self._cwd: Path = Path(".")
        self._task_id: str = ""

    def set_script(self, script: List[ScriptStep]) -> None:
        """Replace the script. Cursor is reset to 0 by reset() — call reset() next."""
        self.script = script
        self._cursor = 0

    def reset(self, task_id: str, cwd: Path) -> None:
        self._task_id = task_id
        self._cwd = cwd
        self._cursor = 0
        self._metrics = AgentMetrics()

    def step(self, state: AgentState) -> tuple[Action, Observation]:
        if self._cursor >= len(self.script):
            return Action(type="done"), Observation(ok=True)

        s = self.script[self._cursor]
        t0 = time.perf_counter()
        io_count = 0
        io_bytes = 0
        output = ""
        ok = True
        err = None

        try:
            if s.kind == "read_file":
                p = self._cwd / s.path
                with open(p, "rb") as f:
                    data = f.read()
                io_count = 1
                io_bytes = len(data)
                output = f"read {len(data)} bytes"
            elif s.kind == "write_file":
                p = self._cwd / s.path
                p.parent.mkdir(parents=True, exist_ok=True)
                content = s.content.encode() if s.content else os.urandom(s.size or 64)
                with open(p, "wb") as f:
                    f.write(content)
                io_count = 1
                io_bytes = len(content)
                output = f"wrote {len(content)} bytes"
            elif s.kind == "fsync":
                # Open + write + fsync. Portable across Windows + Linux.
                # On Linux this maps to a real fsync(2). On Windows, FlushFileBuffers.
                p = self._cwd / s.path
                p.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(p), os.O_WRONLY | os.O_CREAT, 0o644)
                try:
                    os.write(fd, b"\0" * 4)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                io_count = 1
                io_bytes = 4
                output = "fsync 4 bytes"
            elif s.kind == "edit_file":
                # Read + write  →  2 io
                p = self._cwd / s.path
                with open(p, "rb") as f:
                    data = f.read()
                with open(p, "wb") as f:
                    f.write(data + s.content.encode())
                io_count = 2
                io_bytes = len(data) + len(s.content)
                output = f"edit {len(data)}→{len(data)+len(s.content)}"
            elif s.kind == "bash":
                # The agent "ran a command" — we just record it; harness adds real IO
                io_count = 0
                output = f"bash: {s.path}"
            elif s.kind == "done":
                output = "task complete"
            else:
                ok = False
                err = f"unknown step kind: {s.kind}"
        except FileNotFoundError as e:
            ok = False
            err = str(e)
            output = ""

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self._metrics.total_steps += 1
        self._metrics.total_io_count += io_count
        self._metrics.total_io_bytes += io_bytes

        self._cursor += 1
        return (
            Action(type=s.kind, args={"path": s.path, "content": s.content}),
            Observation(ok=ok, output=output, io_count=io_count, io_bytes=io_bytes,
                        latency_ms=elapsed_ms, error=err),
        )

    def trajectory_hash(self) -> str:
        """Stable hash over the script + task. Used for model-drift detection."""
        h = hashlib.sha256()
        h.update(self._task_id.encode())
        for s in self.script:
            h.update(f"{s.kind}|{s.path}|{s.size}|{len(s.content)}".encode())
        return h.hexdigest()[:16]

    def metrics(self) -> AgentMetrics:
        return self._metrics
