#!/usr/bin/env python3
"""
examples/scripted_agent.py
==========================
The default in-process agent for v0. Used by the CLI by default.

A real opencode/pi adapter would subclass BaseAgent and call out to the
agent's actual binary (see examples/opencode_agent.py for a stub).
"""
from framework.agents import ScriptedAgent

if __name__ == "__main__":
    from framework.agents.scripted import ScriptStep
    # Demo: 5-step agent walking a small script
    script = [
        ScriptStep(kind="read_file", path="config.json"),
        ScriptStep(kind="edit_file", path="notes.md", content="\nstep 1"),
        ScriptStep(kind="fsync", path="notes.md"),
        ScriptStep(kind="edit_file", path="notes.md", content="\nstep 2"),
        ScriptStep(kind="fsync", path="notes.md"),
    ]
    agent = ScriptedAgent(script=script)
    print(f"agent={agent.name}  trajectory_hash={agent.trajectory_hash()}")
    print(f"  steps in script: {len(script)}")
