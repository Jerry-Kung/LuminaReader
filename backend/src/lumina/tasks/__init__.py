from lumina.tasks.base import Task, TaskContext, TaskResult, UnsupportedTaskError
from lumina.tasks.translate import TranslateTask

TASK_REGISTRY: dict[str, Task] = {
    "translate": TranslateTask(),
}


def get_task(task_type: str) -> Task:
    if task_type not in TASK_REGISTRY:
        raise UnsupportedTaskError(task_type)
    return TASK_REGISTRY[task_type]


__all__ = [
    "TASK_REGISTRY",
    "Task",
    "TaskContext",
    "TaskResult",
    "TranslateTask",
    "UnsupportedTaskError",
    "get_task",
]
