"""
framework.agents.pi_server
==========================
Adapter for pi-coding-agent (mariozechner/pi-mono) in server mode.

NOTE: pi's HTTP server interface is NOT publicly documented. This adapter
**probes the common endpoints** and falls back gracefully. If your
pi build uses different paths, override the *_path class attributes.

To use:
    1. Start pi in server mode (path depends on your pi build)
    2. Set PI_BASE_URL + PI_TOKEN env vars
    3. Run the framework

If pi doesn't expose an HTTP server, this adapter is a no-op stub
and you'll need to use `SubprocessAgent` (see examples/) instead.
"""
from __future__ import annotations
import os
from .http_sse import BaseHttpSseAgent


class PiServerAgent(BaseHttpSseAgent):
    """Adapter for pi-coding-agent. Endpoints are best-guess; override
    the *_path class attributes to match your pi build."""
    name = "pi-server"

    # Defaults match Gemini-CLI-style servers (pi is Node.js / WebSocket)
    session_create_path = "/session"
    session_message_path = "/session/{sid}/message"
    session_event_path = "/session/{sid}/event"

    def __init__(self, base_url: str = None, model: str = None,
                 token: str = None):
        super().__init__(
            base_url=base_url or os.environ.get("PI_BASE_URL",
                                                "http://127.0.0.1:7742"),
            model=model or os.environ.get("PI_MODEL", "default"),
        )
        if token is None:
            token = os.environ.get("PI_TOKEN")
        if token:
            self.auth_header = f"Bearer {token}"
