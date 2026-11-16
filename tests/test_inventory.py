"""Tests for persistent physical-copy inventory behavior."""

import asyncio
from copy import deepcopy

import pytest

from custom_components.dekudeals import inventory as inventory_module
from custom_components.dekudeals.inventory import GameInventory, InventoryError

STORE_DATA = {}
FAIL_SAVE = set()


class FakeStore:
    """Small in-memory stand-in for Home Assistant Store."""

    def __init__(self, hass, version, key):
        self.key = key

    async def async_load(self):
        return deepcopy(STORE_DATA.get(self.key))

    async def async_save(self, data):
        if self.key in FAIL_SAVE:
            raise OSError("simulated storage failure")
        STORE_DATA[self.key] = deepcopy(data)


@pytest.fixture(autouse=True)
def reset_store(monkeypatch):
    STORE_DATA.clear()
    FAIL_SAVE.clear()
    monkeypatch.setattr(inventory_module, "Store", FakeStore)


def _new_inventory(entry_id="test"):
    inventory = GameInventory(None, entry_id)
    asyncio.run(inventory.async_load())
    return inventory


def test_duplicate_titles_receive_distinct_copy_ids():
    inventory = _new_inventory()

    first = asyncio.run(inventory.async_register_copy("Same Game", "Switch"))
    second = asyncio.run(inventory.async_register_copy("Same Game", "Switch"))

    assert first != second
    assert len(inventory.snapshot()["copies"]) == 2


def test_lending_and_return_preserve_permanent_history():
    inventory = _new_inventory()
    copy_id = asyncio.run(inventory.async_register_copy("Example"))

    asyncio.run(
        inventory.async_lend_copy(
            copy_id, "Alex", "2026-12-01", "Bring it back safely"
        )
    )
    assert inventory.snapshot()["copies"][copy_id]["active_loan"]["borrower"] == "Alex"

    asyncio.run(inventory.async_return_copy(copy_id))
    snapshot = inventory.snapshot()

    assert snapshot["copies"][copy_id]["active_loan"] is None
    assert [event["event"] for event in snapshot["history"]] == ["lent", "returned"]
    assert snapshot["history"][-1]["borrower"] == "Alex"


def test_rejects_invalid_due_date_without_mutation():
    inventory = _new_inventory()
    copy_id = asyncio.run(inventory.async_register_copy("Example"))
    before = inventory.snapshot()

    with pytest.raises(InventoryError):
        asyncio.run(inventory.async_lend_copy(copy_id, "Alex", "12/01/2026"))

    assert inventory.snapshot() == before


def test_rejects_duplicate_lending_and_return_without_loan():
    inventory = _new_inventory()
    copy_id = asyncio.run(inventory.async_register_copy("Example"))
    asyncio.run(inventory.async_lend_copy(copy_id, "Alex"))

    with pytest.raises(InventoryError):
        asyncio.run(inventory.async_lend_copy(copy_id, "Jordan"))

    asyncio.run(inventory.async_return_copy(copy_id))
    with pytest.raises(InventoryError):
        asyncio.run(inventory.async_return_copy(copy_id))


def test_failed_storage_save_rolls_back_memory():
    inventory = _new_inventory()
    before = inventory.snapshot()
    FAIL_SAVE.add("dekudeals_test_inventory")

    with pytest.raises(OSError):
        asyncio.run(inventory.async_register_copy("Example"))

    assert inventory.snapshot() == before
    assert "dekudeals_test_inventory" not in STORE_DATA


def test_inventory_survives_reload():
    first = _new_inventory()
    copy_id = asyncio.run(first.async_register_copy("Example", "Switch 2"))

    second = _new_inventory()

    assert copy_id in second.snapshot()["copies"]
    assert second.snapshot()["copies"][copy_id]["platform"] == "Switch 2"


def test_concurrent_lend_attempts_allow_only_one_active_loan():
    inventory = _new_inventory()
    copy_id = asyncio.run(inventory.async_register_copy("Example"))

    async def attempt_both():
        results = await asyncio.gather(
            inventory.async_lend_copy(copy_id, "Alex"),
            inventory.async_lend_copy(copy_id, "Jordan"),
            return_exceptions=True,
        )
        return results

    results = asyncio.run(attempt_both())

    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, InventoryError) for result in results) == 1
    assert len(inventory.snapshot()["history"]) == 1


def test_rejects_malformed_persisted_inventory():
    STORE_DATA["dekudeals_broken_inventory"] = {
        "schema_version": 1,
        "copies": {
            "broken": {
                "copy_id": "broken",
                "game": "Example",
                "platform": "Switch",
                "format": "digital",
                "source": "manual",
                "active_loan": None,
            }
        },
        "history": [],
    }

    with pytest.raises(InventoryError):
        _new_inventory("broken")


def test_malformed_storage_is_not_overwritten_during_load():
    malformed = {
        "schema_version": 1,
        "copies": {"broken": {"copy_id": "broken", "format": "digital"}},
        "history": [],
    }
    STORE_DATA["dekudeals_broken_inventory"] = deepcopy(malformed)

    with pytest.raises(InventoryError):
        _new_inventory("broken")

    assert STORE_DATA["dekudeals_broken_inventory"] == malformed


def test_removed_imported_copy_retains_active_loan_and_history():
    inventory = _new_inventory()
    imported = {
        "name": "Borrowed Game",
        "format": "physical",
        "platform": "Switch",
        "link": "https://www.dekudeals.com/items/borrowed-game",
        "added_at": "2026-01-01",
    }
    asyncio.run(inventory.async_reconcile_collection([imported]))
    copy_id = next(iter(inventory.snapshot()["copies"]))

    asyncio.run(inventory.async_lend_copy(copy_id, "Alex", "2026-12-01"))
    before = inventory.snapshot()

    result = asyncio.run(inventory.async_reconcile_collection([]))
    after = inventory.snapshot()

    assert result["created"] == 0
    assert after["copies"][copy_id]["collection_present"] is False
    assert after["copies"][copy_id]["needs_review"] is True
    assert after["copies"][copy_id]["active_loan"] == before["copies"][copy_id]["active_loan"]
    assert after["history"] == before["history"]



def test_imported_physical_copy_persists_artwork_and_description():
    inventory = _new_inventory()
    imported = {
        "name": "Artwork Game",
        "format": "physical",
        "platform": "Switch",
        "link": "https://www.dekudeals.com/items/artwork-game",
        "added_at": "2026-01-01",
        "image": "https://cdn.example/artwork.jpg",
        "description": "A short game description.",
    }

    asyncio.run(inventory.async_reconcile_collection([imported]))
    copy = next(iter(inventory.snapshot()["copies"].values()))

    assert copy["image"] == imported["image"]
    assert copy["description"] == imported["description"]


def test_separate_config_entries_keep_inventory_and_loans_isolated():
    switch_inventory = _new_inventory("legacy-switch-entry")
    playstation_inventory = _new_inventory("playstation-entry")

    switch_copy = asyncio.run(
        switch_inventory.async_register_copy("Example Game", "Switch")
    )
    playstation_copy = asyncio.run(
        playstation_inventory.async_register_copy("Example Game", "PlayStation 5")
    )
    asyncio.run(switch_inventory.async_lend_copy(switch_copy, "Alex"))

    reloaded_switch = _new_inventory("legacy-switch-entry")
    reloaded_playstation = _new_inventory("playstation-entry")

    assert set(reloaded_switch.snapshot()["copies"]) == {switch_copy}
    assert set(reloaded_playstation.snapshot()["copies"]) == {playstation_copy}
    assert reloaded_switch.snapshot()["copies"][switch_copy]["active_loan"]["borrower"] == "Alex"
    assert reloaded_playstation.snapshot()["copies"][playstation_copy]["active_loan"] is None
    assert reloaded_switch.snapshot()["history"][0]["borrower"] == "Alex"
    assert reloaded_playstation.snapshot()["history"] == []
