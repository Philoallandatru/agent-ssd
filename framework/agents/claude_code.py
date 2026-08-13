"""
framework.agents.claude_code
============================
Adapter for Claude Code in --serve / --bridge mode.

NOTE: Claude Code's HTTP server interface is experimental and varies
between versions. The defaults below are best-guess based on
Anthropic's official bridge mode.
"""
from __future__ import annotations
import os
from .http_sse import BaseHttpSseAgent


class ClaudeCodeAgent(BaseHttpSseAgent):
    """Adapter for Claude Code --serve / --bridge."""
    name = "claude-code"

    # Anthropic's bridge mode paths (best-guess; verify against your build)
    session_create_path = "/v1/session"
    session_message_path = "/v1/session/{sid}/message"
    session_event_path = "/v1/session/{sid}/events"

    def __init__(self, base_url: str = None, model: str = None,
                 token: str = None):
        super().__init__(
            base_url=base_url or os.environ.get("CLAUDE_CODE_BASE_URL",
                                                "http://127.0.0.1:7842"),
            model=model or os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-5"),
        )
        if token is None:
            token = os.environ.get("ANTHROPIC_API_KEY")
        if token:
            # Anthropic uses x-api-key header, not Bearer
            self.auth_header = token
