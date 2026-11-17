"""Home Assistant services for physical game inventory."""

from __future__ import annotations

import aiohttp
import voluptuous as vol
from urllib.parse import urlparse

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .artwork_proxy import _safe_redirect_target, is_allowed_artwork_url
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
ATTR_GAME_NAME = "game_name"


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
    """Register inventory and artwork diagnostic services."""

    async def lend(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass, call,
            lambda inventory: inventory.async_lend_copy(
                call.data[ATTR_COPY_ID], call.data[ATTR_BORROWER],
                call.data.get(ATTR_DUE_DATE), call.data.get(ATTR_NOTES),
            ),
        )

    async def return_game(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass, call,
            lambda inventory: inventory.async_return_copy(call.data[ATTR_COPY_ID]),
        )

    async def register(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass, call,
            lambda inventory: inventory.async_register_copy(
                call.data[ATTR_GAME], call.data.get(ATTR_PLATFORM, "Unknown"),
                call.data.get(ATTR_NOTES),
            ),
        )

    async def update(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass, call,
            lambda inventory: inventory.async_update_copy(
                call.data[ATTR_COPY_ID], call.data.get(ATTR_NOTES)
            ),
        )

    async def resolve(call: ServiceCall) -> None:
        await _run_inventory_action(
            hass, call,
            lambda inventory: inventory.async_resolve_match(
                call.data[ATTR_COPY_ID], call.data[ATTR_RESOLUTION]
            ),
        )

    async def _refresh_and_reconcile(entry_data, refresh_method) -> None:
        """Wait until both collection refresh and inventory persistence finish."""
        entry_data["reconciliation_task"] = None
        await refresh_method()
        task = entry_data.get("reconciliation_task")
        if task is not None:
            try:
                await task
            except Exception as err:
                raise HomeAssistantError(
                    "The collection refreshed, but inventory reconciliation failed. "
                    "Check the DekuDeals integration log before retrying."
                ) from err

    async def refresh(call: ServiceCall) -> None:
        entry_id, _inventory = _get_inventory(hass, call)
        entry_data = hass.data[DOMAIN]["entries"][entry_id]
        await _refresh_and_reconcile(
            entry_data, entry_data["coordinator"].async_request_refresh
        )

    async def refresh_artwork(call: ServiceCall) -> None:
        entry_id, _inventory = _get_inventory(hass, call)
        entry_data = hass.data[DOMAIN]["entries"][entry_id]
        await _refresh_and_reconcile(
            entry_data, entry_data["coordinator"].async_refresh_artwork
        )

    async def diagnose_artwork(call: ServiceCall) -> None:
        """Check a selected game's TheGamesDB URL from the HA host."""
        entries = hass.data.get(DOMAIN, {}).get("entries", {})
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

        game_name = call.data.get(ATTR_GAME_NAME, "Bluey").strip()
        items = entry["coordinator"].data or []
        match = next(
            (item for item in items
             if game_name.casefold() in str(item.get("name", "")).casefold()),
            None,
        )
        if match is None:
            raise HomeAssistantError(f'Could not find "{game_name}" in this collection.')
        image_url = match.get("image")
        if not is_allowed_artwork_url(image_url):
            raise HomeAssistantError(
                f'"{match.get("name", game_name)}" does not currently have an eligible TheGamesDB front-cover URL.'
            )

        session = async_get_clientsession(hass)
        current_url = image_url
        redirects = 0
        result = "Unknown response"
        details = []
        try:
            for attempt in range(4):
                async with session.get(
                    current_url,
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=False,
                ) as response:
                    details.append(
                        f"HTTP status: {response.status}\n"
                        f"Content-Type: {response.headers.get('Content-Type', '(missing)')}\n"
                        f"Content-Length: {response.headers.get('Content-Length', '(not supplied)')}"
                    )
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        target = _safe_redirect_target(current_url, location)
                        details.append(f"Redirect: {location or '(missing Location header)'}")
                        if target is None or attempt == 3:
                            result = "FAILED: redirect is missing, unsafe, or exceeds the redirect limit."
                            break
                        current_url = target
                        redirects += 1
                        continue
                    if response.status != 200:
                        result = f"FAILED: CDN returned HTTP {response.status}."
                    else:
                        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
                        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                            result = f"FAILED: unsupported image content type ({content_type or 'missing'})."
                        elif response.content_length is not None and response.content_length > 8 * 1024 * 1024:
                            result = "FAILED: image exceeds the 8 MiB size limit."
                        else:
                            sample = await response.content.read(32)
                            result = (
                                "PASSED: Home Assistant fetched image bytes from TheGamesDB."
                                if sample else "FAILED: CDN returned an empty response body."
                            )
                            details.append(f"Body sample: {len(sample)} bytes read")
                    break
        except (aiohttp.ClientError, TimeoutError) as err:
            result = f"FAILED: network request raised {type(err).__name__}: {err}"
        details.append(f"Redirects followed: {redirects}")
        details.append(f"Final URL host: {urlparse(current_url).hostname}")
        message = (
            f"Artwork diagnostic for **{match.get('name', game_name)}**\n\n"
            f"**{result}**\n\n" + "\n\n".join(details)
            + "\n\nThis checks the CDN request from Home Assistant, independently of the Lovelace card."
        )
        persistent_notification.async_create(
            hass, message, title="DekuDeals artwork diagnostic",
            notification_id="dekudeals_artwork_diagnostic",
        )

    common = {vol.Optional(ATTR_CONFIG_ENTRY_ID): str}
    hass.services.async_register(
        DOMAIN, "lend_game", lend,
        schema=vol.Schema({
            vol.Required(ATTR_COPY_ID): str, vol.Required(ATTR_BORROWER): str,
            vol.Optional(ATTR_DUE_DATE): str, vol.Optional(ATTR_NOTES): str, **common,
        }),
    )
    hass.services.async_register(
        DOMAIN, "return_game", return_game,
        schema=vol.Schema({vol.Required(ATTR_COPY_ID): str, **common}),
    )
    hass.services.async_register(
        DOMAIN, "register_copy", register,
        schema=vol.Schema({
            vol.Required(ATTR_GAME): str, vol.Optional(ATTR_PLATFORM, default="Unknown"): str,
            vol.Optional(ATTR_NOTES): str, **common,
        }),
    )
    hass.services.async_register(
        DOMAIN, "update_inventory", update,
        schema=vol.Schema({
            vol.Required(ATTR_COPY_ID): str, vol.Required(ATTR_NOTES): str, **common,
        }),
    )
    hass.services.async_register(
        DOMAIN, "resolve_inventory_match", resolve,
        schema=vol.Schema({
            vol.Required(ATTR_COPY_ID): str,
            vol.Required(ATTR_RESOLUTION): vol.In(["present", "not_present", "manual"]),
            **common,
        }),
    )
    hass.services.async_register(DOMAIN, "refresh_collection", refresh, schema=vol.Schema(common))
    hass.services.async_register(DOMAIN, "refresh_artwork", refresh_artwork, schema=vol.Schema(common))
    hass.services.async_register(
        DOMAIN, "diagnose_artwork", diagnose_artwork,
        schema=vol.Schema({
            vol.Optional(ATTR_GAME_NAME, default="Bluey"): str,
            **common,
        }),
    )
