"""DekuDeals integration."""

from __future__ import annotations

import asyncio
import logging
import secrets

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_COLLECTION_JSON,
    CONF_COLLECTION_URL,
    CONF_PLATFORM,
    CONF_THEGAMESDB_API_KEY,
    DOMAIN,
)
from .coordinator import DekuDealsCoordinator
from .inventory import GameInventory
from .services import async_setup_services
from .artwork_proxy import TheGamesDBArtworkView

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration domain, artwork endpoint, and services."""
    hass.data.setdefault(DOMAIN, {"entries": {}})
    hass.data[DOMAIN].setdefault("entries", {})
    hass.http.register_view(TheGamesDBArtworkView())
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Set up a live collection and its persistent physical inventory."""
    collection_url = entry.data[CONF_COLLECTION_URL]
    fallback_json = entry.options.get(
        CONF_COLLECTION_JSON, entry.data.get(CONF_COLLECTION_JSON)
    )
    coordinator = DekuDealsCoordinator(
        hass,
        collection_url,
        fallback_json,
        entry_id=entry.entry_id,
        platform=entry.data.get(CONF_PLATFORM, "Switch"),
        thegamesdb_api_key=entry.options.get(CONF_THEGAMESDB_API_KEY),
    )
    await coordinator.async_config_entry_first_refresh()

    inventory = GameInventory(hass, entry.entry_id)
    await inventory.async_load()
    await inventory.async_reconcile_collection(coordinator.data or [])

    hass.data.setdefault(DOMAIN, {"entries": {}})
    entry_data = {
        "coordinator": coordinator,
        "inventory": inventory,
        "reconciliation_tasks": set(),
        "reconciliation_task": None,
        # The unauthenticated image endpoint requires this unguessable,
        # runtime-only secret for every individual config entry.
        "artwork_proxy_secret": secrets.token_urlsafe(32),
    }
    hass.data[DOMAIN].setdefault("entries", {})[entry.entry_id] = entry_data

    async def _async_reconcile_updated_collection() -> None:
        """Keep physical inventory in sync after a successful live refresh."""
        try:
            await inventory.async_reconcile_collection(coordinator.data or [])
        except Exception:
            _LOGGER.exception("Failed to reconcile refreshed DekuDeals collection")
            raise
        async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}_inventory_updated")

    def _reconciliation_finished(task: asyncio.Task) -> None:
        entry_data["reconciliation_tasks"].discard(task)
        if not task.cancelled():
            # Retrieve background exceptions to avoid an unhandled-task warning.
            task.exception()

    def _handle_coordinator_update() -> None:
        task = hass.async_create_task(_async_reconcile_updated_collection())
        entry_data["reconciliation_task"] = task
        entry_data["reconciliation_tasks"].add(task)
        task.add_done_callback(_reconciliation_finished)

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_reload_entry(hass: HomeAssistant, entry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Unload a collection without deleting its persistent inventory."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    entry_data = hass.data[DOMAIN]["entries"].get(entry.entry_id)
    if entry_data is not None:
        tasks = tuple(entry_data.get("reconciliation_tasks", ()))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    return True
