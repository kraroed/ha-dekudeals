"""Home Assistant services for physical game inventory."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN
from .inventory import GameInventory, InventoryError

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_COPY_ID = "copy_id"
ATTR_GAME = "game"
ATTR_PLATFORM = "platform"
ATTR_BORROWER = "borrower"
ATTR_DUE_DATE = "due_date"
ATTR_NOTES = "notes"
ATTR_RESOLUTION = "resolution"


def _get_inventory(hass: HomeAssistant, call: ServiceCall) -> tuple[str, GameInventory]:
    entries = hass.data[DOMAIN]["entries"]
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id is None:
        if len(entries) != 1:
            raise HomeAssistantError(
                "Specify config_entry_id when more than one DekuDeals collection is configured."
            )
        entry_id = next(iter(entries))
    entry = entries.get(entry_id)
    if entry is None:
        raise HomeAssistantError("The selected DekuDeals collection is not loaded.")
    return entry_id, entry["inventory"]


async def _run_inventory_action(hass: HomeAssistant, call: ServiceCall, action) -> None:
    entry_id, inventory = _get_inventory(hass, call)
    try:
        await action(inventory)
    except InventoryError as err:
        raise HomeAssistantError(str(err)) from err
    async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_inventory_updated")


def async_setup_services(hass: HomeAssistant) -> None:
    """Register inventory services once for the integration domain."""

    async def lend(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass,
            call,
            lambda inventory: inventory.async_lend_copy(
                call.data[ATTR_COPY_ID],
                call.data[ATTR_BORROWER],
                call.data.get(ATTR_DUE_DATE),
                call.data.get(ATTR_NOTES),
            ),
        )

    async def return_game(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass,
            call,
            lambda inventory: inventory.async_return_copy(call.data[ATTR_COPY_ID]),
        )

    async def register(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass,
            call,
            lambda inventory: inventory.async_register_copy(
                call.data[ATTR_GAME],
                call.data.get(ATTR_PLATFORM, "Unknown"),
                call.data.get(ATTR_NOTES),
            ),
        )

    async def update(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass,
            call,
            lambda inventory: inventory.async_update_copy(
                call.data[ATTR_COPY_ID], call.data.get(ATTR_NOTES)
            ),
        )

    async def resolve(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass,
            call,
            lambda inventory: inventory.async_resolve_match(
                call.data[ATTR_COPY_ID], call.data[ATTR_RESOLUTION]
            ),
        )

    async def refresh(call: ServiceCall) -> None:
        entry_id, data = _get_inventory(hass, call)
        await data["coordinator"].async_request_refresh()

    common = {vol.Optional(ATTR_CONFIG_ENTRY_ID): str}
    hass.services.async_register(
        DOMAIN,
        "lend_game",
        lend,
        schema=vol.Schema(
            {
                vol.Required(ATTR_COPY_ID): str,
                vol.Required(ATTR_BORROWER): str,
                vol.Optional(ATTR_DUE_DATE): str,
                vol.Optional(ATTR_NOTES): str,
                **common,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "return_game",
        return_game,
        schema=vol.Schema(
            {vol.Required(ATTR_COPY_ID): str, **common}
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "register_copy",
        register,
        schema=vol.Schema(
            {
                vol.Required(ATTR_GAME): str,
                vol.Optional(ATTR_PLATFORM, default="Unknown"): str,
                vol.Optional(ATTR_NOTES): str,
                **common,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "update_inventory",
        update,
        schema=vol.Schema(
            {
                vol.Required(ATTR_COPY_ID): str,
                vol.Required(ATTR_NOTES): str,
                **common,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "resolve_inventory_match",
        resolve,
        schema=vol.Schema(
            {
                vol.Required(ATTR_COPY_ID): str,
                vol.Required(ATTR_RESOLUTION): vol.In(
                    ["present", "not_present", "manual"]
                ),
                **common,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "refresh_collection",
        refresh,
        schema=vol.Schema(common),
    )
