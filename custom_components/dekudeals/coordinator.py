"""Collection data coordinator."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .importer import parse_collection_export

_LOGGER = logging.getLogger(__name__)


class DekuDealsCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Hold the most recently imported collection."""

    def __init__(self, hass: HomeAssistant, collection_json: str) -> None:
        self.collection_json = collection_json
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
        )

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Parse the stored export snapshot.

        The integration currently imports a user-provided JSON export; it does
        not claim to fetch or scrape the live DekuDeals website.
        """
        return parse_collection_export(self.collection_json)
