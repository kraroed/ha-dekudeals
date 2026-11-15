"""Sensors for DekuDeals."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_LIST_ITEMS

DESCRIPTIONS = (
    SensorEntityDescription(key="games", name="Games", icon="mdi:gamepad-variant"),
    SensorEntityDescription(key="switch_games", name="Switch Games", icon="mdi:nintendo-switch"),
    SensorEntityDescription(key="switch_2_games", name="Switch 2 Games", icon="mdi:nintendo-switch"),
    SensorEntityDescription(key="physical_games", name="Physical Games", icon="mdi:gamepad"),
    SensorEntityDescription(key="digital_games", name="Digital Games", icon="mdi:download"),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up collection sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(DekuDealsSensor(coordinator, description) for description in DESCRIPTIONS)


class DekuDealsSensor(CoordinatorEntity, SensorEntity):
    """Represent a collection count."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry_id}_{description.key}" if hasattr(coordinator, "config_entry_id") else description.key

    @property
    def native_value(self):
        items = self.coordinator.data or []
        key = self.entity_description.key
        if key == "games":
            return len(items)
        if key == "switch_games":
            return sum(item["platform"].lower() == "switch" for item in items)
        if key == "switch_2_games":
            return sum(item["platform"].lower() == "switch 2" for item in items)
        if key == "physical_games":
            return sum(item["format"] == "physical" for item in items)
        if key == "digital_games":
            return sum(item["format"] == "digital" for item in items)
        return 0

    @property
    def extra_state_attributes(self):
        items = self.coordinator.data or []
        return {
            "items": items[:MAX_LIST_ITEMS],
            "items_truncated": len(items) > MAX_LIST_ITEMS,
            "source": "DekuDeals JSON export",
        }

    @callback
    def _handle_coordinator_update(self):
        self.async_write_ha_state()
