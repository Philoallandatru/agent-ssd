"""
framework.agents.opencode_server
================================
A real BaseAgent that talks to `opencode serve` over HTTP + SSE.

Inherits the shared HTTP+SSE protocol from `BaseHttpSseAgent` and only
sets the opencode-specific path templates + body shape.

For the opencode v1 server (sst/opencode):
  - POST /session     body={cwd}    -> {id}
  - POST /session/:id/message
  - GET  /session/:id/event?since=N (SSE)
"""
from __future__ import annotations
import os
from .http_sse import BaseHttpSseAgent


class OpencodeServerAgent(BaseHttpSseAgent):
    """Adapter for `opencode serve` (sst/opencode)."""
    name = "opencode-server"

    # opencode-specific paths
    session_create_path = "/session"
    session_message_path = "/session/{sid}/message"
    session_event_path = "/session/{sid}/event"

    def __init__(self, base_url: str = None, model: str = None,
                 auth_token: str = None):
        super().__init__(
            base_url=base_url or os.environ.get("OPENCODE_BASE_URL",
                                                "http://127.0.0.1:9999"),
            model=model or os.environ.get("OPENCODE_MODEL", "claude-sonnet-4-5"),
        )
        if auth_token is None:
            auth_token = os.environ.get("OPENCODE_TOKEN")
        if auth_token:
            self.auth_header = f"Bearer {auth_token}"
