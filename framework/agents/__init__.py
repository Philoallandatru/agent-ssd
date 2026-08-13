"""framework.agents — pluggable agent interface + built-in agents."""
from .base import BaseAgent, AgentState, Action, Observation, AgentMetrics
from .scripted import ScriptedAgent
from .replay import ReplayingAgent
from .http_sse import BaseHttpSseAgent
from .opencode_server import OpencodeServerAgent
from .qwen_code import QwenCodeAgent
from .pi_server import PiServerAgent
from .claude_code import ClaudeCodeAgent
from .registry import AGENT_REGISTRY, get_agent_factory, list_agents

__all__ = [
    "BaseAgent", "AgentState", "Action", "Observation", "AgentMetrics",
    "BaseHttpSseAgent",
    "ScriptedAgent", "ReplayingAgent",
    "OpencodeServerAgent", "QwenCodeAgent", "PiServerAgent", "ClaudeCodeAgent",
    "AGENT_REGISTRY", "get_agent_factory", "list_agents",
]
