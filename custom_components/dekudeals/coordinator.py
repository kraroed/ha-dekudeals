"""Live DekuDeals collection data coordinator."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .importer import CollectionImportError, parse_collection_export

_LOGGER = logging.getLogger(__name__)


class DekuDealsCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Fetch and normalize a public DekuDeals collection JSON export."""

    def __init__(
        self,
        hass: HomeAssistant,
        collection_url: str,
        fallback_json: str | None = None,
    ) -> None:
        self.collection_url = collection_url.rstrip("/")
        self.fallback_json = fallback_json.strip() if fallback_json else None
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=6),
        )

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Fetch the public JSON export, using a saved export only as fallback."""
        url = (
            self.collection_url
            if self.collection_url.endswith(".json")
            else f"{self.collection_url}.json"
        )
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            items = parse_collection_export(json.dumps(payload))
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, CollectionImportError) as err:
            if self.fallback_json:
                _LOGGER.warning(
                    "Could not refresh DekuDeals collection; using the saved JSON export: %s",
                    err,
                )
                try:
                    return parse_collection_export(self.fallback_json)
                except CollectionImportError as fallback_err:
                    raise UpdateFailed(
                        "Both the live collection and saved export are invalid."
                    ) from fallback_err
            raise UpdateFailed(f"Unable to refresh DekuDeals collection: {err}") from err
        return items
