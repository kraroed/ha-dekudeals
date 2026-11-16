"""Collection and physical inventory sensors for DekuDeals."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MAX_LIST_ITEMS

COLLECTION_DESCRIPTIONS = (
    SensorEntityDescription(key="games", name="Games", icon="mdi:gamepad-variant"),
    SensorEntityDescription(key="switch_games", name="Switch Games", icon="mdi:gamepad"),
    SensorEntityDescription(key="switch_2_games", name="Switch 2 Games", icon="mdi:gamepad"),
    SensorEntityDescription(key="physical_games", name="Physical Games", icon="mdi:gamepad"),
    SensorEntityDescription(key="digital_games", name="Digital Games", icon="mdi:download"),\n    SensorEntityDescription(key="dlc_items", name="DLC Items", icon="mdi:download-box"),
)

INVENTORY_DESCRIPTIONS = (
    SensorEntityDescription(key="in_possession", name="Games In Possession", icon="mdi:gamepad-variant"),
    SensorEntityDescription(key="lent_out", name="Games Lent Out", icon="mdi:handshake"),
    SensorEntityDescription(key="overdue", name="Games Overdue", icon="mdi:calendar-alert"),
    SensorEntityDescription(key="total_copies", name="Total Physical Copies", icon="mdi:counter"),
    SensorEntityDescription(key="active_loans", name="Active Game Loans", icon="mdi:account-arrow-right"),
    SensorEntityDescription(key="lending_history", name="Game Lending History", icon="mdi:history"),
    SensorEntityDescription(key="needs_review", name="Inventory Needs Review", icon="mdi:alert-circle"),
    SensorEntityDescription(key="unmatched", name="Unmatched Physical Games", icon="mdi:help-circle"),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up collection and inventory sensors."""
    entry_data = hass.data[DOMAIN]["entries"][entry.entry_id]
    coordinator = entry_data["coordinator"]
    inventory = entry_data["inventory"]
    entities = [
        DekuDealsSensor(coordinator, entry.entry_id, description)
        for description in COLLECTION_DESCRIPTIONS
    ]
    entities.extend(
        InventorySensor(inventory, entry.entry_id, description)
        for description in INVENTORY_DESCRIPTIONS
    )
    async_add_entities(entities)


class DekuDealsSensor(CoordinatorEntity, SensorEntity):
    """Represent a collection count."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Group collection entities under one DekuDeals device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="DekuDeals",
            manufacturer="DekuDeals",
            model="Collection and physical inventory",
        )

    @property
    def native_value(self):
        """Return the count for this sensor."""
        items = self.coordinator.data or []
        key = self.entity_description.key
        if key == "games":
            return len(items)
        if key == "switch_games":
            return sum(item["platform"].casefold() == "switch" for item in items)
        if key == "switch_2_games":
            return sum(item["platform"].casefold() == "switch 2" for item in items)
        if key == "physical_games":
            return sum(item["format"] == "physical" for item in items)
        if key == "digital_games":
            return sum(item["format"] == "digital" for item in items)
        return 0

    @property
    def extra_state_attributes(self):
        """Expose a bounded snapshot of the imported collection."""
        items = self.coordinator.data or []
        return {
            "items": items[:MAX_LIST_ITEMS],
            "items_truncated": len(items) > MAX_LIST_ITEMS,
            "source": "DekuDeals JSON export",
        }


class InventorySensor(SensorEntity):
    """Expose a live view of persistent physical game inventory."""

    _attr_has_entity_name = True

    def __init__(self, inventory, entry_id, description):
        self.inventory = inventory
        self.entity_description = description
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._signal = f"{DOMAIN}_{entry_id}_inventory_updated"

    @property
    def device_info(self) -> DeviceInfo:
        """Group inventory entities with the collection device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="DekuDeals",
            manufacturer="DekuDeals",
            model="Collection and physical inventory",
        )

    async def async_added_to_hass(self):
        """Subscribe to successful inventory mutations."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._handle_update)
        )

    @callback
    def _handle_update(self):
        self.async_write_ha_state()

    @property
    def _copies(self):
        return list(self.inventory.snapshot()["copies"].values())

    @property
    def native_value(self):
        """Return the selected inventory count."""
        copies = self._copies
        key = self.entity_description.key
        lent = [item for item in copies if item.get("active_loan") is not None]
        if key == "in_possession":
            return len(copies) - len(lent)
        if key in {"lent_out", "active_loans"}:
            return len(lent)
        if key == "overdue":
            today = dt_util.now().date().isoformat()
            return sum(
                item["active_loan"].get("due_date") is not None
                and item["active_loan"]["due_date"] < today
                for item in lent
            )
        if key == "total_copies":
            return len(copies)
        if key == "lending_history":
            return len(self.inventory.snapshot()["history"])
        if key == "needs_review":
            return sum(item.get("needs_review", False) for item in copies)
        if key == "unmatched":
            return sum(
                item.get("source") == "dekudeals"
                and item.get("collection_present") is False
                for item in copies
            )
        return 0

    @property
    def extra_state_attributes(self):
        """Expose bounded copy, loan, and history details."""
        snapshot = self.inventory.snapshot()
        copies = list(snapshot["copies"].values())
        key = self.entity_description.key
        if key in {"lent_out", "active_loans", "overdue"}:
            today = dt_util.now().date().isoformat()
            selected = [
                item for item in copies
                if item.get("active_loan") is not None
                and (
                    key != "overdue"
                    or (
                        item["active_loan"].get("due_date") is not None
                        and item["active_loan"]["due_date"] < today
                    )
                )
            ]
        elif key == "needs_review":
            selected = [item for item in copies if item.get("needs_review")]
        elif key == "unmatched":
            selected = [
                item for item in copies
                if item.get("source") == "dekudeals"
                and item.get("collection_present") is False
            ]
        elif key == "lending_history":
            return {
                "recent_events": snapshot["history"][-20:][::-1],
                "total_events": len(snapshot["history"]),
            }
        else:
            selected = copies
        return {
            "copies": selected[:MAX_LIST_ITEMS],
            "items_truncated": len(selected) > MAX_LIST_ITEMS,
        }
