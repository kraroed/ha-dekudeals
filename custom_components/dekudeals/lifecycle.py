"""Helpers for tracking background collection reconciliation tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


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
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
