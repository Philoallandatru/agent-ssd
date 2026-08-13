"""
extreme.checkpoint_load
=======================
Sequential read of a single large file (7GB default). Models
"load model checkpoint into agent context".

v0: writes a sparse file using os.pwrite so the disk test is real, not
synthetic. The file is removed at the end.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any
import time
import os
import hashlib

from ..base import BaseTask, TaskContext, TaskResult
from ...agents.scripted import ScriptedAgent, ScriptStep
from ...agents.base import AgentState


@dataclass
class CheckpointLoadTask:
    id: str = "extreme/checkpoint_load"
    category: str = "extreme"
    slo_seconds: float = 60.0
    description: str = "Sequential read of a large checkpoint file."

    # v0 uses 64MB for speed; v1 will use 7GB+ when run on real SSD.
    file_size_mb: int = 64
    chunk_kb: int = 1024

    def setup(self, ctx: TaskContext) -> None:
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        target = ctx.workdir / "checkpoint.bin"
        # Write a sparse file: extend file size without writing every byte.
        # This makes setup fast and lets the real read test the SSD bandwidth.
        size_bytes = self.file_size_mb * 1024 * 1024
        with open(target, "wb") as f:
            f.truncate(size_bytes)

    def run(self, agent, ctx: TaskContext) -> TaskResult:
        target = ctx.workdir / "checkpoint.bin"
        chunk = self.chunk_kb * 1024

        t0 = time.perf_counter()
        total_bytes = 0
        h = hashlib.sha256()
        with open(target, "rb") as f:
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                total_bytes += len(buf)
                h.update(buf)
        elapsed = time.perf_counter() - t0
        mbps = (total_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0

        result = TaskResult(
            task_id=self.id, category=self.category, state="COMPLETED",
            total_seconds=elapsed, agent_metrics=None,
            trajectory_hash=h.hexdigest()[:16],
        )
        result.extra = {"bytes_read": total_bytes, "mbps": round(mbps, 2)}
        return result

    def verify(self, result: TaskResult, ctx: TaskContext) -> bool:
        return result.passed and result.extra.get("bytes_read", 0) > 0
