"""Set of dispatchable tasks, and a convenience function to clean them up.
https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task

Only manage_task is exported; the task set itself is opaque to callers.
"""

import asyncio
from typing import Set

__all__ = ["manage_task"]

tasks: Set[asyncio.Task] = set()


def manage_task(task: asyncio.Task) -> None:
    tasks.add(task)
    task.add_done_callback(tasks.discard)
