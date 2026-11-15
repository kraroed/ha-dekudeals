"""DekuDeals integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import CONF_COLLECTION_JSON, DOMAIN
from .coordinator import DekuDealsCoordinator
from .importer import parse_collection_export
from .inventory import GameInventory
from .services import async_setup_services

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration domain and register its services."""
    hass.data.setdefault(DOMAIN, {"entries": {}})
    hass.data[DOMAIN].setdefault("entries", {})
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Set up a configured collection and its persistent physical inventory."""
    coordinator = DekuDealsCoordinator(hass, entry.data[CONF_COLLECTION_JSON])
    await coordinator.async_config_entry_first_refresh()

    inventory = GameInventory(hass, entry.entry_id)
    await inventory.async_load()
    await inventory.async_reconcile_collection(
        parse_collection_export(entry.data[CONF_COLLECTION_JSON])
    )

    hass.data.setdefault(DOMAIN, {"entries": {}})
    hass.data[DOMAIN].setdefault("entries", {})[entry.entry_id] = {
        "coordinator": coordinator,
        "inventory": inventory,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Unload a collection without deleting its persistent inventory."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    return True
