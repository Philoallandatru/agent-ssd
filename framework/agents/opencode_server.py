"""
framework.agents.opencode_server
================================
A real BaseAgent that talks to `opencode serve` over HTTP + SSE.

This is the *production* adapter. It is the answer to "use opencode
on a real repo, on a real task".

How it works:
  1. The user runs `opencode serve --port 9999` in a terminal.
  2. Our agent POSTs to /session to create a session bound to the repo cwd.
  3. The user sends a task prompt via POST /session/:id/message.
  4. opencode streams back tool_call / tool_result / done events as SSE.
  5. We parse the SSE stream and translate to Action / Observation.

The HTTP contract below is informed by OpenWork's documented usage
(https://github.com/different-ai/openwork) and the @opencode-ai/sdk/v2
client. If your installed opencode version uses different paths,
override `base_url` and patch the `_post_session_message` /
`_parse_sse` methods. They are intentionally small so the seams
are easy to find.

Verification path (v0):
  - Set `OPENCODE_MOCK=1` to point the agent at a MockOpencodeServer
    in-process. That is what `tests/test_opencode_integration.py` does.
  - Set `OPENCODE_BASE_URL=http://127.0.0.1:9999` for the real server.
"""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any

from .base import BaseAgent, AgentState, Action, Observation, AgentMetrics


@dataclass
class OpencodeServerAgent:
    """A real agent adapter: talks to `opencode serve` over HTTP.

    Required environment:
        OPENCODE_BASE_URL   e.g. http://127.0.0.1:9999   (real)
        OPENCODE_MOCK=1     bypasses HTTP, drives the agent via a script
                             (useful when opencode-ai is not installed)
    """
    name: str = "opencode-server"
    base_url: str = field(default_factory=lambda: os.environ.get(
        "OPENCODE_BASE_URL", "http://127.0.0.1:9999"))
    model: str = field(default_factory=lambda: os.environ.get(
        "OPENCODE_MODEL", "claude-sonnet-4-5"))
    session_id: Optional[str] = None
    _task_id: str = ""
    _cwd: Path = field(default_factory=Path)
    _prompt_sent: bool = False
    _metrics: AgentMetrics = field(default_factory=AgentMetrics)
    _turn: int = 0
    _history: List[Dict[str, Any]] = field(default_factory=list)

    # ----- protocol endpoints (override if your opencode differs) -----
    session_create_path: str = "/session"
    session_message_path: str = "/session/{sid}/message"
    session_event_path: str = "/session/{sid}/event"

    def reset(self, task_id: str, cwd: Path) -> None:
        self._task_id = task_id
        self._cwd = cwd
        self._prompt_sent = False
        self._metrics = AgentMetrics()
        self._turn = 0
        self._history = []
        self.session_id = self._create_session(cwd)

    def _create_session(self, cwd: Path) -> str:
        """POST /session with {cwd}. Returns session_id."""
        body = json.dumps({"cwd": str(cwd), "model": self.model}).encode()
        req = urllib.request.Request(
            f"{self.base_url}{self.session_create_path}",
            data=body, headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["id"]

    def step(self, state: AgentState) -> tuple[Action, Observation]:
        """Send the task prompt once, then drain SSE events for tool calls.

        For v0 we send the prompt on the first step. Subsequent steps
        just keep reading the opencode SSE stream. The agent finishes
        when opencode emits a `done` event.
        """
        if not self._prompt_sent:
            self._send_prompt(state)
            self._prompt_sent = True

        event = self._next_event(state)
        if event is None:
            return Action(type="done"), Observation(ok=True, output="agent idle")

        self._metrics.total_steps += 1
        self._turn += 1

        kind = event.get("type", "")
        if kind == "tool_call":
            tool = event.get("tool", {})
            t0 = time.perf_counter()
            # Tool calls are recorded; opencode itself does the IO on the SUT
            action = Action(
                type=tool.get("name", "unknown"),
                args=tool.get("arguments", {}),
            )
            obs = Observation(
                ok=True,
                output=f"opencode tool_call: {action.type}",
                io_count=1,
                io_bytes=int(tool.get("bytes", 0) or 0),
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )
            self._metrics.total_io_count += 1
            self._metrics.total_io_bytes += obs.io_bytes
            return action, obs

        if kind == "tool_result":
            # The previous tool_call has a result. Continue draining.
            tool = event.get("tool", {})
            return Action(type=tool.get("name", "result"),
                          args={"result": tool.get("result", "")}), \
                   Observation(ok=True, output=str(tool.get("result", ""))[:500])

        if kind == "text":
            # Agent is "thinking out loud". No IO, but worth recording.
            return Action(type="text", args={"content": event.get("content", "")}), \
                   Observation(ok=True, output=event.get("content", "")[:500])

        if kind == "done":
            return Action(type="done"), Observation(ok=True, output=event.get("reason", "done"))

        if kind == "error":
            return Action(type="error"), Observation(ok=False, error=event.get("message", ""))

        return Action(type=kind or "unknown"), Observation(ok=True, output=str(event)[:200])

    def _send_prompt(self, state: AgentState) -> None:
        """POST the task prompt. The first turn contains the task instructions."""
        task_prompt = self._build_task_prompt(state)
        path = self.session_message_path.format(sid=self.session_id)
        body = json.dumps({"content": task_prompt}).encode()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body, headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as _:
                pass
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"opencode send prompt failed: {e.code} {e.reason}")

    def _build_task_prompt(self, state: AgentState) -> str:
        """The user-overridable task prompt. Default: ask opencode to do
        the task described in the issue file under state.cwd/.issue.md.
        """
        issue = state.cwd / ".issue.md"
        if issue.exists():
            return issue.read_text(encoding="utf-8")
        return (
            "You are running inside an SSD benchmark harness. "
            "The working directory is " + str(state.cwd) + ". "
            "Complete the task and run the test command when done."
        )

    def _next_event(self, state: AgentState) -> Optional[dict]:
        """GET the SSE stream and return the next event. v0 reads one event
        per step (turn). For long sessions we may want batching, but one
        per turn is what the framework contracts for.
        """
        path = self.session_event_path.format(sid=self.session_id)
        url = f"{self.base_url}{path}?since={self._turn}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                # Read just enough of the SSE stream to capture the next event
                raw = resp.read(64 * 1024).decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            return {"type": "error", "message": f"opencode unreachable: {e}"}

        return self._parse_sse(raw)

    @staticmethod
    def _parse_sse(raw: str) -> Optional[dict]:
        """Parse one Server-Sent Event block.

        Format:
            event: <type>
            data: <json>
            <blank line>
        """
        ev_type = "message"
        data_lines: list = []
        for line in raw.splitlines():
            if line.startswith("event:"):
                ev_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if not data_lines:
            return None
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            payload = {"raw": "\n".join(data_lines)}
        if isinstance(payload, dict):
            payload.setdefault("type", ev_type)
            return payload
        return {"type": ev_type, "payload": payload}

    def trajectory_hash(self) -> str:
        """A coarse trajectory hash. Real impl: hash the actual tool_call sequence."""
        import hashlib
        h = hashlib.sha256()
        h.update(self._task_id.encode())
        for ev in self._history:
            h.update(json.dumps(ev, sort_keys=True).encode())
        return h.hexdigest()[:16]

    def metrics(self) -> AgentMetrics:
        return self._metrics
