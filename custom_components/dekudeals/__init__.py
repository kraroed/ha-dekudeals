"""DekuDeals integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import CONF_COLLECTION_JSON, CONF_COLLECTION_URL, DOMAIN
from .coordinator import DekuDealsCoordinator
from .inventory import GameInventory
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration domain and register its services."""
    hass.data.setdefault(DOMAIN, {"entries": {}})
    hass.data[DOMAIN].setdefault("entries", {})
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Set up a live collection and its persistent physical inventory."""
    collection_url = entry.data[CONF_COLLECTION_URL]
    fallback_json = entry.options.get(
        CONF_COLLECTION_JSON, entry.data.get(CONF_COLLECTION_JSON)
    )
    coordinator = DekuDealsCoordinator(
        hass, collection_url, fallback_json, entry_id=entry.entry_id
    )
    await coordinator.async_config_entry_first_refresh()

    inventory = GameInventory(hass, entry.entry_id)
    await inventory.async_load()
    await inventory.async_reconcile_collection(coordinator.data or [])

    hass.data.setdefault(DOMAIN, {"entries": {}})
    hass.data[DOMAIN].setdefault("entries", {})[entry.entry_id] = {
        "coordinator": coordinator,
        "inventory": inventory,
    }

    async def _async_reconcile_updated_collection() -> None:
        """Keep physical inventory in sync after a successful live refresh."""
        try:
            await inventory.async_reconcile_collection(coordinator.data or [])
        except Exception:
            _LOGGER.exception("Failed to reconcile refreshed DekuDeals collection")
            return
        async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}_inventory_updated")

    def _handle_coordinator_update() -> None:
        hass.async_create_task(_async_reconcile_updated_collection())

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_reload_entry(hass: HomeAssistant, entry) -> None:
    """Reload after the fallback export options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Unload a collection without deleting its persistent inventory."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    return True
