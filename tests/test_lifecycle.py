"""Tests for reconciliation task lifecycle and unload behavior."""

import asyncio

from custom_components.dekudeals.lifecycle import ReconciliationTaskTracker


def test_unload_waits_for_in_flight_reconciliation_tasks():
    async def run():
        tracker = ReconciliationTaskTracker()
        started = asyncio.Event()
        release = asyncio.Event()
        finished = []

        async def reconcile(label):
            started.set()
            await release.wait()
            finished.append(label)

        tracker.add(asyncio.create_task(reconcile("first")))
        tracker.add(asyncio.create_task(reconcile("second")))
        await started.wait()

        unload = asyncio.create_task(tracker.async_wait())
        await asyncio.sleep(0)
        assert not unload.done()

        release.set()
        await unload
        assert sorted(finished) == ["first", "second"]
        assert not tracker.tasks

    asyncio.run(run())


def test_unload_drains_failed_tasks_without_leaking_task_exceptions():
    async def run():
        tracker = ReconciliationTaskTracker()

        async def fail():
            raise RuntimeError("simulated reconciliation failure")

        tracker.add(asyncio.create_task(fail()))
        await asyncio.sleep(0)
        await tracker.async_wait()
        assert not tracker.tasks

    asyncio.run(run())
