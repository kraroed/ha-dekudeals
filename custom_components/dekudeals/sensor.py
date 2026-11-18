"""Collection and physical inventory sensors for DekuDeals."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .artwork_proxy import build_artwork_proxy_url
from .const import DOMAIN, MAX_LIST_ITEMS

COLLECTION_DESCRIPTIONS = (
    SensorEntityDescription(key="games", name="Games", icon="mdi:gamepad-variant"),
    SensorEntityDescription(key="configured_platform_games", name="Configured Platform Games", icon="mdi:gamepad-variant"),
    SensorEntityDescription(key="switch_games", name="Switch Games", icon="mdi:gamepad"),
    SensorEntityDescription(key="switch_2_games", name="Switch 2 Games", icon="mdi:gamepad"),
    SensorEntityDescription(key="physical_games", name="Physical Games", icon="mdi:gamepad"),
    SensorEntityDescription(key="digital_games", name="Digital Games", icon="mdi:download"),
    SensorEntityDescription(key="dlc_items", name="DLC Items", icon="mdi:download-box"),
    SensorEntityDescription(key="artwork_coverage", name="Artwork Coverage", icon="mdi:image-check"),
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
    artwork_proxy_secret = entry_data["artwork_proxy_secret"]
    entities = [
        DekuDealsSensor(
            coordinator,
            entry.entry_id,
            description,
            artwork_proxy_secret,
        )
        for description in COLLECTION_DESCRIPTIONS
    ]
    entities.extend(
        InventorySensor(
            inventory,
            entry.entry_id,
            description,
            artwork_proxy_secret,
        )
        for description in INVENTORY_DESCRIPTIONS
    )
    async_add_entities(entities)


class DekuDealsSensor(CoordinatorEntity, SensorEntity):
    """Represent a collection count."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, coordinator, entry_id, description, artwork_proxy_secret):
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._artwork_proxy_secret = artwork_proxy_secret
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
        games = [item for item in items if item.get("item_type") != "dlc"]
        if key == "games":
            return len(games)
        if key == "configured_platform_games":
            return len(games)
        if key == "dlc_items":
            return sum(item.get("item_type") == "dlc" for item in items)
        if key == "switch_games":
            return sum(item["platform"].casefold() == "switch" for item in games)
        if key == "switch_2_games":
            return sum(item["platform"].casefold() == "switch 2" for item in games)
        if key == "physical_games":
            return sum(item["format"] == "physical" for item in games)
        if key == "digital_games":
            return sum(item["format"] == "digital" for item in games)
        if key == "artwork_coverage":
            total = len(items)
            with_artwork = sum(
                isinstance(item.get("image"), str) and bool(item["image"].strip())
                for item in items
            )
            return round(with_artwork * 100 / total) if total else 0
        return 0

    @property
    def extra_state_attributes(self):
        """Expose collection artwork coverage or a bounded item snapshot."""
        items = self.coordinator.data or []
        if self.entity_description.key == "artwork_coverage":
            missing = [
                str(item.get("name") or "Unknown title")
                for item in items
                if not isinstance(item.get("image"), str) or not item["image"].strip()
            ]
            with_artwork = len(items) - len(missing)
            return {
                "total_items": len(items),
                "items_with_artwork": with_artwork,
                "items_missing_artwork": len(missing),
                "coverage_percent": (
                    round(with_artwork * 100 / len(items)) if items else 0
                ),
                "missing_artwork_sample": missing[:25],
                "missing_artwork_sample_truncated": len(missing) > 25,
            }
        exposed_items = []
        for source_item in items[:MAX_LIST_ITEMS]:
            item = dict(source_item)
            image_url = item.get("image")
            if isinstance(image_url, str):
                item["image"] = build_artwork_proxy_url(
                    self._entry_id, self._artwork_proxy_secret, image_url
                )
            exposed_items.append(item)
        return {
            "items": exposed_items,
            "items_truncated": len(items) > MAX_LIST_ITEMS,
            "source": "DekuDeals JSON export",
            "configured_platform": self.coordinator.platform,
        }


class InventorySensor(SensorEntity):
    """Expose a live view of persistent physical game inventory."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"copies", "recent_events"})

    def __init__(self, inventory, entry_id, description, artwork_proxy_secret):
        self.inventory = inventory
        self._artwork_proxy_secret = artwork_proxy_secret
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
        exposed_copies = []
        for source_copy in selected[:MAX_LIST_ITEMS]:
            copy = dict(source_copy)
            image_url = copy.get("image")
            if isinstance(image_url, str):
                copy["image"] = build_artwork_proxy_url(
                    self._entry_id, self._artwork_proxy_secret, image_url
                )
            exposed_copies.append(copy)
        return {
            "copies": exposed_copies,
            "items_truncated": len(selected) > MAX_LIST_ITEMS,
        }
