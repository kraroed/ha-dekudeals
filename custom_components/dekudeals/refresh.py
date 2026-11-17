"""Refresh orchestration shared by collection services and tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


async def async_refresh_and_reconcile(
    entry_data: dict[str, Any], refresh_method: Callable[[], Awaitable[None]]
) -> None:
    """Serialize manual refreshes and await their inventory reconciliation."""
    lock = entry_data.setdefault("refresh_lock", asyncio.Lock())
    async with lock:
        entry_data["reconciliation_task"] = None
        await refresh_method()
        task = entry_data.get("reconciliation_task")
        if task is not None:
            await task
