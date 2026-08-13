"""
framework.testing.mock_opencode
================================
A tiny in-process HTTP server that mimics `opencode serve`.

Why: writing a real opencode integration requires npm + opencode-ai
installed + an LLM API key. The mock lets us run the integration
*end-to-end* (agent → HTTP → SSE → Action/Observation) on any box
without those dependencies.

What it mocks:
  - POST /session     → returns {"id": "mock-<n>"}
  - POST /session/:id/message → no-op
  - GET  /session/:id/event   → SSE stream of canned tool_call events
                                 (a small but realistic-looking sequence)

This is a *test double*, not a fuzzer. Its job is to give the
integration test a server to talk to so we can prove the agent's
HTTP+SSE parsing works.
"""
from __future__ import annotations
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Dict, Any


def _make_canned_events(task_id: str) -> List[Dict[str, Any]]:
    """A deterministic sequence of events the mock streams.

    Models a simple opencode run: read a few files, edit one, run a test.
    """
    return [
        {"type": "tool_call", "tool": {"name": "read_file",
                                       "arguments": {"path": "src/main.py"},
                                       "bytes": 2048}},
        {"type": "tool_call", "tool": {"name": "grep",
                                       "arguments": {"pattern": "TODO"},
                                       "bytes": 0}},
        {"type": "tool_call", "tool": {"name": "edit_file",
                                       "arguments": {"path": "src/main.py", "old": "x", "new": "y"},
                                       "bytes": 64}},
        {"type": "tool_result", "tool": {"name": "test_run",
                                          "result": "3 passed, 0 failed"}},
        {"type": "text", "content": "I think the fix is in place. Running tests."},
        {"type": "done", "reason": "all done"},
    ]


class MockOpencodeHandler(BaseHTTPRequestHandler):
    server_canned: List[Dict[str, Any]] = []    # set by start_mock_opencode
    server_sessions: Dict[str, int] = {}        # session_id -> event cursor

    def log_message(self, fmt, *args):  # silence default logging
        return

    def do_POST(self):
        if self.path == "/session":
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)              # discard body
            sid = f"mock-{len(self.server_sessions) + 1}"
            self.server_sessions[sid] = 0
            body = json.dumps({"id": sid}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/session/") and self.path.endswith("/message"):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404); self.end_headers()

    def do_GET(self):
        # /session/:id/event
        if "/event" in self.path:
            # path like /session/mock-1/event?since=N
            parts = self.path.split("/")
            # parts: ['', 'session', '<sid>', 'event']
            sid = parts[2] if len(parts) >= 4 else "?"
            cursor = self.server_sessions.get(sid, 0)
            events = self.server_canned
            if cursor >= len(events):
                # Stream a "done" heartbeat every poll so the client gets
                # *something* and can detect end-of-stream eventually
                self._send_sse({"type": "done", "reason": "stream end"})
                return
            ev = events[cursor]
            self.server_sessions[sid] = cursor + 1
            self._send_sse(ev)
            return
        self.send_response(404); self.end_headers()

    def _send_sse(self, payload: dict) -> None:
        body = (f"event: {payload.get('type', 'message')}\n"
                f"data: {json.dumps(payload)}\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_mock_opencode(canned: List[Dict[str, Any]] = None,
                        host: str = "127.0.0.1", port: int = 0
                        ) -> tuple[ThreadingHTTPServer, str]:
    """Start a mock opencode server. Returns (server, base_url).

    `port=0` lets the OS pick a free port.
    """
    handler = MockOpencodeHandler
    handler.server_canned = canned if canned is not None else _make_canned_events("default")
    handler.server_sessions = {}
    server = ThreadingHTTPServer((host, port), handler)
    base_url = f"http://{host}:{server.server_address[1]}"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, base_url


def stop_mock_opencode(server) -> None:
    server.shutdown()
    server.server_close()
