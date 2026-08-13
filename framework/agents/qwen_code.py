"""
framework.agents.qwen_code
==========================
A real BaseAgent that talks to `qwen serve` over HTTP + SSE.

This is the answer to "use qwen-code (already configured) to do real tests".

qwen serve command (real, from `qwen serve --help`):
  - binds to 127.0.0.1:4170 by default
  - accepts Bearer token via --token or QWEN_SERVER_TOKEN
  - binds to one workspace at startup (POST /session with mismatched cwd returns 400)
  - exposes:
      POST /session                       body={cwd}               -> {id}
      POST /session/:id/prompt            body={content: prompt}
      GET  /session/:id/events?since=N     (SSE, replays with Last-Event-ID)
      GET  /health                        (no auth)

  - Event types observed: tool_call, tool_result, text, done, error
"""
from __future__ import annotations
import os
from .http_sse import BaseHttpSseAgent


class QwenCodeAgent(BaseHttpSseAgent):
    """Adapter for `qwen serve`. Reads token from QWEN_SERVER_TOKEN env."""
    name = "qwen-code"

    # qwen-specific paths (note: /prompt and /events, not /message and /event)
    session_create_path = "/session"
    session_message_path = "/session/{sid}/prompt"
    session_event_path = "/session/{sid}/events"

    def __init__(self, base_url: str = None, model: str = None,
                 token: str = None):
        super().__init__(
            base_url=base_url or os.environ.get("QWEN_BASE_URL",
                                                "http://127.0.0.1:4170"),
            model=model or os.environ.get("QWEN_MODEL", "qwen3-coder-plus"),
        )
        if token is None:
            token = os.environ.get("QWEN_SERVER_TOKEN")
        if token:
            self.auth_header = f"Bearer {token}"
