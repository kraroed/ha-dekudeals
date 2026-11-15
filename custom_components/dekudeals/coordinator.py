"""Collection data coordinator."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_COLLECTION_JSON, DOMAIN
from .importer import parse_collection_export


class DekuDealsCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Hold the most recently imported collection."""

    def __init__(self, hass: HomeAssistant, collection_json: str) -> None:
        self.collection_json = collection_json
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(hours=6),
        )

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Return the imported collection snapshot.

        Live DekuDeals fetching is intentionally not claimed in this initial
        implementation; the JSON export is the source of truth until sync is added.
        """
        return parse_collection_export(self.collection_json)
