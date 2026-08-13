"""
framework
=========
A pluggable harness for running agent workloads against an SSD under test.

Public API:
    from framework import Runner, RunSpec
    from framework.agents import ScriptedAgent, OpencodeServerAgent
    from framework.tasks import TASK_REGISTRY
    from framework.reporters import ConsoleReporter, JsonReporter
"""
from .harness import Runner, RunSpec, RunReport, StateMachine, State
from .agents import ScriptedAgent, ReplayingAgent, OpencodeServerAgent, BaseAgent
from .tasks import TASK_REGISTRY, BaseTask, TaskContext, TaskResult

__all__ = [
    "Runner", "RunSpec", "RunReport", "StateMachine", "State",
    "ScriptedAgent", "ReplayingAgent", "OpencodeServerAgent", "BaseAgent",
    "TASK_REGISTRY", "BaseTask", "TaskContext", "TaskResult",
]
