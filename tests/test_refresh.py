"""Tests for manual refresh/reconciliation service sequencing."""

import asyncio

import pytest

from custom_components.dekudeals.refresh import async_refresh_and_reconcile


def test_refresh_service_waits_for_inventory_reconciliation():
    async def run():
        entry_data = {}
        started = asyncio.Event()
        release = asyncio.Event()
        completed = []

        async def refresh():
            async def reconcile():
                started.set()
                await release.wait()
                completed.append(True)

            task = asyncio.create_task(reconcile())
            entry_data["reconciliation_task"] = task

        service = asyncio.create_task(async_refresh_and_reconcile(entry_data, refresh))
        await started.wait()
        await asyncio.sleep(0)
        assert not service.done()
        assert completed == []

        release.set()
        await service
        assert completed == [True]

    asyncio.run(run())


def test_refresh_service_propagates_reconciliation_failure():
    async def run():
        entry_data = {}

        async def refresh():
            async def reconcile():
                raise OSError("storage write failed")

            entry_data["reconciliation_task"] = asyncio.create_task(reconcile())

        with pytest.raises(OSError, match="storage write failed"):
            await async_refresh_and_reconcile(entry_data, refresh)

    asyncio.run(run())


def test_overlapping_manual_refreshes_are_serialized():
    async def run():
        entry_data = {}
        active = 0
        maximum_active = 0
        order = []

        async def refresh():
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            order.append("start")
            await asyncio.sleep(0)
            order.append("end")
            active -= 1

        await asyncio.gather(
            async_refresh_and_reconcile(entry_data, refresh),
            async_refresh_and_reconcile(entry_data, refresh),
        )
        assert maximum_active == 1
        assert order == ["start", "end", "start", "end"]

    asyncio.run(run())
