"""
framework.testing.mock_opencode
================================
A tiny in-process HTTP server that mimics agent `serve` commands.

Supports TWO protocol variants via path templates:
  - opencode / Gemini CLI style: /session, /session/:id/message, /session/:id/event
  - qwen serve style:           /session, /session/:id/prompt,  /session/:id/events

Set `protocol="qwen"` or `protocol="opencode"` when starting.

Also supports Bearer token auth (qwen serve uses --token / QWEN_SERVER_TOKEN).
"""
from __future__ import annotations
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Dict, Any, Optional


def _make_canned_events(task_id: str) -> List[Dict[str, Any]]:
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


class _Handler(BaseHTTPRequestHandler):
    protocol: str = "opencode"   # "opencode" or "qwen"
    server_canned: List[Dict[str, Any]] = []
    server_sessions: Dict[str, int] = {}
    auth_token: Optional[str] = None

    def log_message(self, fmt, *args):
        return

    def _check_auth(self) -> bool:
        if not self.auth_token:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {self.auth_token}"

    def do_POST(self):
        if not self._check_auth():
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "unauthorized"}).encode())
            return

        if self.path == "/session" or self.path == "/v1/session":
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            sid = f"mock-{len(self.server_sessions) + 1}"
            self.server_sessions[sid] = 0
            body = json.dumps({"id": sid}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # /session/:id/message (opencode) OR /session/:id/prompt (qwen)
        if (("/message" in self.path) or ("/prompt" in self.path)) and self.path.startswith("/session/"):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "not found", "path": self.path}).encode())

    def do_GET(self):
        # /health is always public (k8s/Compose probes don't carry bearer)
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            body = json.dumps({"status": "ok", "protocol": self.protocol}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not self._check_auth():
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "unauthorized"}).encode())
            return

        # /session/:id/event  (opencode)  OR  /session/:id/events  (qwen)
        if (("/event" in self.path) or ("/events" in self.path)) and self.path.startswith("/session/"):
            parts = self.path.split("/")
            sid = parts[2] if len(parts) >= 4 else "?"
            cursor = self.server_sessions.get(sid, 0)
            events = self.server_canned
            if cursor >= len(events):
                self._send_sse({"type": "done", "reason": "stream end"})
                return
            ev = events[cursor]
            self.server_sessions[sid] = cursor + 1
            self._send_sse(ev)
            return

        if self.path == "/health":
            # handled above; keep here for clarity if flow changes
            pass

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
                        host: str = "127.0.0.1", port: int = 0,
                        protocol: str = "opencode",
                        auth_token: Optional[str] = None
                        ) -> tuple[ThreadingHTTPServer, str]:
    """Start a mock agent server. Returns (server, base_url)."""
    h = _Handler
    h.protocol = protocol
    h.server_canned = canned if canned is not None else _make_canned_events("default")
    h.server_sessions = {}
    h.auth_token = auth_token
    server = ThreadingHTTPServer((host, port), h)
    base_url = f"http://{host}:{server.server_address[1]}"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, base_url


def stop_mock_opencode(server) -> None:
    server.shutdown()
    server.server_close()
