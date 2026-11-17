"""Helpers for tracking background collection reconciliation tasks."""

from __future__ import annotations

import asyncio


class ReconciliationTaskTracker:
    """Track reconciliation work so refreshes and unloads can await it."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()
        self.latest_task: asyncio.Task | None = None

    def add(self, task: asyncio.Task) -> None:
        """Register a task and consume its exception when it finishes."""
        self.latest_task = task
        self.tasks.add(task)

        def _finished(done_task: asyncio.Task) -> None:
            self.tasks.discard(done_task)
            if not done_task.cancelled():
                done_task.exception()

        task.add_done_callback(_finished)

    async def async_wait(self) -> None:
        """Wait until every currently running reconciliation has settled."""
        while self.tasks:
            pending = tuple(self.tasks)
            await asyncio.gather(*pending, return_exceptions=True)
            # A task's gather callback can wake this coroutine before the
            # tracker's done callback runs. Remove the completed snapshot here
            # as well, otherwise the loop can repeatedly gather the same task.
            self.tasks.difference_update(task for task in pending if task.done())
