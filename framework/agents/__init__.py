"""framework.agents — pluggable agent interface + built-in agents."""
from .base import BaseAgent, AgentState, Action, Observation, AgentMetrics
from .scripted import ScriptedAgent
from .replay import ReplayingAgent
from .opencode_server import OpencodeServerAgent

__all__ = [
    "BaseAgent", "AgentState", "Action", "Observation", "AgentMetrics",
    "ScriptedAgent", "ReplayingAgent", "OpencodeServerAgent",
]
