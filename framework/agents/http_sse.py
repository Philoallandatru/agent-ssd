"""
framework.agents.http_sse
==========================
The shared base for any "agent that speaks HTTP + SSE to a local server".

Subclass and override the *_path class attributes. Don't use @dataclass
inheritance for path defaults — Python's MRO rules silently drop subclass
overrides. Use plain class attributes + explicit __init__ instead.

Protocol (v0):
  1. POST  {base_url}{session_create_path}     body={cwd, model, ...} -> {id}
  2. POST  {base_url}{session_message_path}    body={content: prompt}
  3. GET   {base_url}{session_event_path}?since=N     -> SSE event stream
  4. Event types: tool_call, tool_result, text, done, error

Override the *Path* strings to adapt to a specific server. The base class
does NOT make assumptions about the JSON shape of the session-create body
— subclass overrides _session_create_body() if you need to send extra
fields (e.g. model, api_key, sandbox).
"""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, List, Dict, Any

from .base import BaseAgent, AgentState, Action, Observation, AgentMetrics


class BaseHttpSseAgent(BaseAgent):
    """Reusable HTTP+SSE agent base. Subclass and override the *_path attrs."""
    name = "http-sse"   # plain class attribute; subclasses override

    # Default paths. Subclasses MUST override these (set as class attributes
    # in their own body).
    session_create_path = "/session"
    session_message_path = "/session/{sid}/message"
    session_event_path = "/session/{sid}/event"

    def __init__(self, base_url: str = None, model: str = None,
                 auth_token: str = None):
        self.base_url = base_url or os.environ.get(
            "AGENT_BASE_URL", "http://127.0.0.1:9999")
        self.model = model or os.environ.get("AGENT_MODEL", "default")
        self.auth_header: Optional[str] = None
        if auth_token:
            self.auth_header = f"Bearer {auth_token}"
        # State
        self.session_id: Optional[str] = None
        self._task_id: str = ""
        self._cwd: Path = Path()
        self._prompt_sent: bool = False
        self._metrics = AgentMetrics()
        self._turn: int = 0

    # ----- subclass extension points (override in subclasses) -----

    def _session_create_body(self, cwd: Path) -> dict:
        """Override to send extra fields (model, api_key, sandbox, etc.)."""
        return {"cwd": str(cwd), "model": self.model}

    def _build_task_prompt(self, state: AgentState) -> str:
        """Override to customize how the task is phrased to the agent.

        Default: read .issue.md from state.cwd.
        """
        issue = state.cwd / ".issue.md"
        if issue.exists():
            return issue.read_text(encoding="utf-8")
        return (
            f"You are running inside an SSD benchmark harness. "
            f"The working directory is {state.cwd}. "
            f"Complete the task and run the test command when done."
        )

    def _http_headers(self) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.auth_header:
            headers["Authorization"] = self.auth_header
        return headers

    # ----- BaseAgent interface -----

    def reset(self, task_id: str, cwd: Path) -> None:
        self._task_id = task_id
        self._cwd = cwd
        self._prompt_sent = False
        self._metrics = AgentMetrics()
        self._turn = 0
        self.session_id = self._create_session(cwd)

    def step(self, state: AgentState) -> tuple[Action, Observation]:
        if not self._prompt_sent:
            self._send_prompt(state)
            self._prompt_sent = True

        event = self._next_event(state)
        if event is None:
            return Action(type="done"), Observation(ok=True, output="agent idle")

        self._metrics.total_steps += 1
        self._turn += 1
        return self._translate_event(event)

    def trajectory_hash(self) -> str:
        import hashlib
        h = hashlib.sha256()
        h.update(self._task_id.encode())
        h.update(str(self.session_id).encode())
        h.update(str(self._turn).encode())
        return h.hexdigest()[:16]

    def metrics(self) -> AgentMetrics:
        return self._metrics

    # ----- HTTP transport -----

    def _create_session(self, cwd: Path) -> str:
        body = json.dumps(self._session_create_body(cwd)).encode()
        req = urllib.request.Request(
            f"{self.base_url}{self.session_create_path}",
            data=body, headers=self._http_headers(), method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["id"]

    def _send_prompt(self, state: AgentState) -> None:
        path = self.session_message_path.format(sid=self.session_id)
        body = json.dumps({"content": self._build_task_prompt(state)}).encode()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body, headers=self._http_headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as _:
                pass
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{self.name} send prompt failed: {e.code} {e.reason}")

    def _next_event(self, state: AgentState) -> Optional[dict]:
        path = self.session_event_path.format(sid=self.session_id)
        url = f"{self.base_url}{path}?since={self._turn}"
        try:
            req = urllib.request.Request(url, headers={
                **self._http_headers(),
                "Accept": "text/event-stream",
            })
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = resp.read(64 * 1024).decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            return {"type": "error", "message": f"{self.name} unreachable: {e}"}
        return self._parse_sse(raw)

    @staticmethod
    def _parse_sse(raw: str) -> Optional[dict]:
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

    # ----- Event translation -----

    def _translate_event(self, event: dict) -> tuple[Action, Observation]:
        kind = event.get("type", "")
        if kind == "tool_call":
            tool = event.get("tool", {})
            action = Action(type=tool.get("name", "unknown"),
                            args=tool.get("arguments", {}))
            obs = Observation(
                ok=True,
                output=f"{self.name} tool_call: {action.type}",
                io_count=1,
                io_bytes=int(tool.get("bytes", 0) or 0),
            )
            self._metrics.total_io_count += 1
            self._metrics.total_io_bytes += obs.io_bytes
            return action, obs

        if kind == "tool_result":
            tool = event.get("tool", {})
            return (Action(type=tool.get("name", "result"),
                           args={"result": tool.get("result", "")}),
                    Observation(ok=True, output=str(tool.get("result", ""))[:500]))

        if kind == "text":
            content = event.get("content", "")
            return (Action(type="text", args={"content": content}),
                    Observation(ok=True, output=content[:500]))

        if kind == "done":
            return (Action(type="done"),
                    Observation(ok=True, output=event.get("reason", "done")))

        if kind == "error":
            return (Action(type="error"),
                    Observation(ok=False, error=event.get("message", "")))

        return (Action(type=kind or "unknown"),
                Observation(ok=True, output=str(event)[:200]))
