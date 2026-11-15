"""Persistent physical game inventory and lending history."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_VERSION = 1
EMPTY_DATA: dict[str, Any] = {"schema_version": 1, "copies": {}, "history": []}


class InventoryError(ValueError):
    """Raised when an inventory operation is invalid."""


def _now() -> str:
    return dt_util.utcnow().isoformat()


def _valid_date(value: str | None) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


class GameInventory:
    """Manage locally stored physical copies without coupling them to imports."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}_inventory")
        self._data = deepcopy(EMPTY_DATA)
        self._lock = asyncio.Lock()
        self._loaded = False

    async def async_load(self) -> None:
        """Load and validate persisted inventory."""
        stored = await self._store.async_load()
        if stored is None:
            self._data = deepcopy(EMPTY_DATA)
        else:
            self._validate_data(stored)
            self._data = deepcopy(stored)
        self._loaded = True

    @staticmethod
    def _validate_data(data: Any) -> None:
        if not isinstance(data, dict) or data.get("schema_version") != STORAGE_VERSION:
            raise InventoryError("Unsupported or malformed inventory storage version.")
        if not isinstance(data.get("copies"), dict) or not isinstance(data.get("history"), list):
            raise InventoryError("Inventory storage is malformed.")
        for copy_id, item in data["copies"].items():
            if not isinstance(item, dict) or item.get("copy_id") != copy_id:
                raise InventoryError("Inventory copy record is malformed.")
            if not isinstance(item.get("game"), str) or not item["game"].strip():
                raise InventoryError("Inventory copy is missing its game title.")
            if item.get("format") != "physical":
                raise InventoryError("Only physical copies can be stored in inventory.")
            if item.get("source") not in {"manual", "dekudeals"}:
                raise InventoryError("Inventory copy has an invalid source.")
            if item.get("active_loan") is not None and not isinstance(item["active_loan"], dict):
                raise InventoryError("Inventory loan record is malformed.")

    def snapshot(self) -> dict[str, Any]:
        """Return a defensive copy of all inventory data."""
        return deepcopy(self._data)

    async def _async_commit(self, candidate: dict[str, Any]) -> None:
        """Persist candidate data before publishing it in memory."""
        self._validate_data(candidate)
        await self._store.async_save(candidate)
        self._data = candidate

    def _require_loaded(self) -> None:
        if not self._loaded:
            raise InventoryError("Inventory has not finished loading.")

    async def async_register_copy(
        self, game: str, platform: str = "Unknown", notes: str | None = None
    ) -> str:
        """Register a physical copy that is not represented by the online export."""
        if not isinstance(game, str) or not game.strip():
            raise InventoryError("A game title is required.")
        async with self._lock:
            self._require_loaded()
            candidate = deepcopy(self._data)
            copy_id = str(uuid4())
            candidate["copies"][copy_id] = {
                "copy_id": copy_id,
                "game": game.strip(),
                "platform": (platform or "Unknown").strip() or "Unknown",
                "format": "physical",
                "source": "manual",
                "source_identity": None,
                "source_fingerprint": None,
                "collection_present": None,
                "needs_review": False,
                "review_reason": None,
                "notes": notes,
                "active_loan": None,
                "created_at": _now(),
            }
            await self._async_commit(candidate)
            return copy_id

    async def async_lend_copy(
        self,
        copy_id: str,
        borrower: str,
        due_date: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Lend a physical copy and append a permanent history event."""
        if not isinstance(borrower, str) or not borrower.strip():
            raise InventoryError("A borrower name is required.")
        if not _valid_date(due_date):
            raise InventoryError("Due date must use YYYY-MM-DD.")
        async with self._lock:
            self._require_loaded()
            item = self._data["copies"].get(copy_id)
            if item is None:
                raise InventoryError("Unknown physical copy.")
            if item["active_loan"] is not None:
                raise InventoryError("This copy is already lent out.")
            candidate = deepcopy(self._data)
            record = candidate["copies"][copy_id]
            loan = {
                "borrower": borrower.strip(),
                "lent_at": _now(),
                "due_date": due_date,
                "notes": notes,
            }
            record["active_loan"] = loan
            candidate["history"].append(
                {
                    "event_id": str(uuid4()),
                    "copy_id": copy_id,
                    "game": record["game"],
                    "event": "lent",
                    **loan,
                }
            )
            await self._async_commit(candidate)

    async def async_return_copy(self, copy_id: str) -> None:
        """Return a lent copy and preserve the completed loan in history."""
        async with self._lock:
            self._require_loaded()
            item = self._data["copies"].get(copy_id)
            if item is None:
                raise InventoryError("Unknown physical copy.")
            if item["active_loan"] is None:
                raise InventoryError("This copy is not currently lent out.")
            candidate = deepcopy(self._data)
            record = candidate["copies"][copy_id]
            loan = record["active_loan"]
            candidate["history"].append(
                {
                    "event_id": str(uuid4()),
                    "copy_id": copy_id,
                    "game": record["game"],
                    "event": "returned",
                    "borrower": loan["borrower"],
                    "lent_at": loan["lent_at"],
                    "due_date": loan.get("due_date"),
                    "returned_at": _now(),
                    "notes": loan.get("notes"),
                }
            )
            record["active_loan"] = None
            await self._async_commit(candidate)

    async def async_update_copy(self, copy_id: str, notes: str | None) -> None:
        """Update the private notes attached to a physical copy."""
        async with self._lock:
            self._require_loaded()
            if copy_id not in self._data["copies"]:
                raise InventoryError("Unknown physical copy.")
            candidate = deepcopy(self._data)
            candidate["copies"][copy_id]["notes"] = notes
            await self._async_commit(candidate)

    async def async_resolve_match(self, copy_id: str, resolution: str) -> None:
        """Resolve a collection reconciliation warning without deleting a copy."""
        if resolution not in {"present", "not_present", "manual"}:
            raise InventoryError("Resolution must be present, not_present, or manual.")
        async with self._lock:
            self._require_loaded()
            if copy_id not in self._data["copies"]:
                raise InventoryError("Unknown physical copy.")
            candidate = deepcopy(self._data)
            item = candidate["copies"][copy_id]
            if resolution == "manual":
                item.update(source="manual", source_identity=None, source_fingerprint=None)
                item["collection_present"] = None
            else:
                item["collection_present"] = resolution == "present"
            item["needs_review"] = False
            item["review_reason"] = None
            await self._async_commit(candidate)

    async def async_reconcile_collection(
        self, imported_items: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Reconcile imported physical rows conservatively, retaining every copy."""
        from .reconciliation import build_reconciliation_plan

        async with self._lock:
            self._require_loaded()
            plan = build_reconciliation_plan(imported_items, self._data["copies"])
            candidate = deepcopy(self._data)

            for copy_id, changes in plan["updates"].items():
                candidate["copies"][copy_id].update(changes)

            for item in plan["creates"]:
                copy_id = str(uuid4())
                candidate["copies"][copy_id] = {
                    "copy_id": copy_id,
                    "game": item["name"],
                    "platform": item["platform"],
                    "format": "physical",
                    "source": "dekudeals",
                    "source_identity": item["identity"],
                    "source_fingerprint": item["fingerprint"],
                    "collection_present": True,
                    "needs_review": False,
                    "review_reason": None,
                    "notes": item.get("note"),
                    "active_loan": None,
                    "created_at": _now(),
                }

            await self._async_commit(candidate)
            return {
                "created": len(plan["creates"]),
                "updated": len(plan["updates"]),
                "ambiguous": len(plan["ambiguous"]),
            }
