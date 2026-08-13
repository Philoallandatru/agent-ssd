"""
framework.agents.registry
=========================
Pluggable registry of agent factories.

Adding a new agent to the framework is a one-liner:

    from framework.agents.registry import AGENT_REGISTRY
    AGENT_REGISTRY["my-agent"] = lambda: MyAgent(...)

The CLI / Runner look up `AGENT_REGISTRY[agent_name]` to build the
agent for a given RunSpec.

Three classes of agents are recognized:
  - mock / scripted  : no external dependency, deterministic
  - http-sse-server  : talks to a local HTTP+SSE server (opencode, qwen, pi, ...)
  - subprocess       : shells out to a CLI binary (a future v1 plug)
"""
from __future__ import annotations
from typing import Callable, Dict

from .base import BaseAgent
from .scripted import ScriptedAgent
from .replay import ReplayingAgent
from .opencode_server import OpencodeServerAgent
from .qwen_code import QwenCodeAgent
from .pi_server import PiServerAgent
from .claude_code import ClaudeCodeAgent


# Agent name -> factory (callable returning a fresh BaseAgent)
AGENT_REGISTRY: Dict[str, Callable[[], BaseAgent]] = {
    # Mock / scripted
    "scripted":           lambda: ScriptedAgent(),
    "replaying":          lambda: ReplayingAgent(script=[], recorded_hash=""),

    # Real HTTP+SSE agents. Each expects its corresponding serve command
    # to be running locally. See respective module docstrings.
    "opencode-server":    lambda: OpencodeServerAgent(),
    "qwen-code":          lambda: QwenCodeAgent(),
    "pi-server":          lambda: PiServerAgent(),
    "claude-code":        lambda: ClaudeCodeAgent(),
}


def get_agent_factory(name: str) -> Callable[[], BaseAgent]:
    """Return the factory for `name`, or raise ValueError if unknown."""
    if name not in AGENT_REGISTRY:
        known = ", ".join(sorted(AGENT_REGISTRY))
        raise ValueError(
            f"Unknown agent: {name!r}. Known agents: {known}. "
            f"Register your own via AGENT_REGISTRY[name] = factory."
        )
    return AGENT_REGISTRY[name]


def list_agents() -> list[str]:
    """Return the sorted list of registered agent names."""
    return sorted(AGENT_REGISTRY)
