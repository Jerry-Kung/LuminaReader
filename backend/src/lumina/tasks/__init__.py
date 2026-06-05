from lumina.tasks.base import Task, TaskContext, TaskResult, UnsupportedTaskError
from lumina.tasks.extract import ExtractTask

# V1.1.1: thin compatibility map for _run_core legacy task_type fallback only.
# Task abstraction and ExtractTask remain; user-visible tasks moved to plugins.
TASK_REGISTRY: dict[str, str] = {
    "translate": "translate",
    "explain": "explain",
}


def resolve_legacy_task_type(task_type: str) -> str | None:
    """Map legacy task_type to plugin_id. None means unknown → UNSUPPORTED_TASK."""
    return TASK_REGISTRY.get(task_type)


__all__ = [
    "Task",
    "TaskContext",
    "TaskResult",
    "UnsupportedTaskError",
    "ExtractTask",
    "TASK_REGISTRY",
    "resolve_legacy_task_type",
]
