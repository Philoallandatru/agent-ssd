"""framework.tasks — pluggable task interface + 5-category task family."""
from .base import BaseTask, TaskContext, TaskResult, Category

# v0 ships two reference tasks; more live under each category package.
from .write_heavy.session_persist import SessionPersistTask
from .read_heavy.monorepo_search import MonorepoSearchTask
from .mixed.cargo_build import CargoBuildTask
from .shared.git_worktree import GitWorktreeSwarmTask
from .extreme.checkpoint_load import CheckpointLoadTask
from .realistic.repo_task import RealRepoTask
from .realistic.local_repo_task import LocalRepoTask

# Registry: id → class
TASK_REGISTRY = {
    "write_heavy/session_persist":     SessionPersistTask,
    "read_heavy/monorepo_search":      MonorepoSearchTask,
    "mixed/cargo_build":               CargoBuildTask,
    "shared/git_worktree":             GitWorktreeSwarmTask,
    "extreme/checkpoint_load":         CheckpointLoadTask,
    "realistic/repo_task":             RealRepoTask,
    "realistic/local_repo":            LocalRepoTask,
}

__all__ = [
    "BaseTask", "TaskContext", "TaskResult", "Category",
    "TASK_REGISTRY",
    "SessionPersistTask", "MonorepoSearchTask", "CargoBuildTask",
    "GitWorktreeSwarmTask", "CheckpointLoadTask",
    "RealRepoTask", "LocalRepoTask",
]
