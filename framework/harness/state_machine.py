"""
framework.harness.state_machine
==============================
PREPARING → STAGING → RUNNING → VERIFYING → COLLECTING → ANALYZING → COMPLETED|FAILED

State persists to disk as run_state.json so a crashed Runner can resume.
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class State(str, Enum):
    PENDING    = "PENDING"
    PREPARING  = "PREPARING"
    STAGING    = "STAGING"
    RUNNING    = "RUNNING"
    VERIFYING  = "VERIFYING"
    COLLECTING = "COLLECTING"
    ANALYZING  = "ANALYZING"
    COMPLETED  = "COMPLETED"
    FAILED     = "FAILED"


# Legal forward transitions
_FORWARD = {
    State.PENDING:    {State.PREPARING, State.FAILED},
    State.PREPARING:  {State.STAGING, State.FAILED},
    State.STAGING:    {State.RUNNING, State.FAILED},
    State.RUNNING:    {State.VERIFYING, State.FAILED},
    State.VERIFYING:  {State.COLLECTING, State.FAILED},
    State.COLLECTING: {State.ANALYZING, State.FAILED},
    State.ANALYZING:  {State.COMPLETED, State.FAILED},
    State.COMPLETED:  set(),
    State.FAILED:     set(),
}


@dataclass
class StateMachine:
    """Persistent state machine. Persistable to run_state.json."""
    run_id: str
    state: State = State.PENDING
    history: list = None
    last_transition_at: float = 0.0

    def __post_init__(self):
        if self.history is None:
            self.history = []

    def transition(self, target: State, note: str = "") -> None:
        if target not in _FORWARD[self.state]:
            raise ValueError(f"illegal transition: {self.state.value} → {target.value}")
        self.history.append({"from": self.state.value, "to": target.value,
                             "at": time.time(), "note": note})
        self.state = target
        self.last_transition_at = time.time()

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({
            "run_id": self.run_id,
            "state": self.state.value,
            "history": self.history,
            "last_transition_at": self.last_transition_at,
        }, indent=2))

    @classmethod
    def load(cls, path: Path) -> "StateMachine":
        d = json.loads(path.read_text())
        sm = cls(run_id=d["run_id"])
        sm.state = State(d["state"])
        sm.history = d["history"]
        sm.last_transition_at = d["last_transition_at"]
        return sm
