"""Live DekuDeals collection and cached game metadata coordinator."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .importer import CollectionImportError, parse_collection_export
from .metadata import extract_game_metadata, is_dekudeals_item_url

_LOGGER = logging.getLogger(__name__)
METADATA_CACHE_VERSION = 2
METADATA_MAX_PER_REFRESH = 20
METADATA_CONCURRENCY = 3
METADATA_CACHE_TTL = 30 * 24 * 60 * 60


class DekuDealsCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Fetch a public collection and enrich rows with cached page metadata."""

    def __init__(
        self,
        hass: HomeAssistant,
        collection_url: str,
        fallback_json: str | None = None,
        entry_id: str = "default",
    ) -> None:
        self.collection_url = collection_url.rstrip("/")
        self.fallback_json = fallback_json.strip() if fallback_json else None
        self._metadata_store = Store(
            hass, METADATA_CACHE_VERSION, f"{DOMAIN}_{entry_id}_game_metadata"
        )
        self._metadata_cache: dict[str, dict[str, Any]] | None = None
        self._metadata_cursor = 0
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=6),
        )

    async def _async_load_metadata_cache(self) -> None:
        """Load metadata cache once; ignore invalid cache data safely."""
        if self._metadata_cache is not None:
            return
        try:
            stored = await self._metadata_store.async_load()
        except (OSError, ValueError):
            _LOGGER.warning("Could not load DekuDeals game metadata cache")
            stored = None
        if (
            isinstance(stored, dict)
            and isinstance(stored.get("items"), dict)
            and isinstance(stored.get("cursor", 0), int)
        ):
            self._metadata_cache = {
                key: value
                for key, value in stored["items"].items()
                if isinstance(key, str) and isinstance(value, dict)
            }
            self._metadata_cursor = max(0, stored.get("cursor", 0))
        else:
            self._metadata_cache = {}

    async def _async_enrich_metadata(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Fill missing artwork and descriptions without blocking collection sync."""
        await self._async_load_metadata_cache()
        assert self._metadata_cache is not None
        now = time.time()
        enriched = [dict(item) for item in items]
        candidates: list[tuple[int, str]] = []

        for index, item in enumerate(enriched):
            link = item.get("link")
            if not is_dekudeals_item_url(link):
                continue
            cache = self._metadata_cache.get(link)
            if cache:
                if not item.get("image") and isinstance(cache.get("image"), str):
                    item["image"] = cache["image"]
                if not item.get("description") and isinstance(cache.get("description"), str):
                    item["description"] = cache["description"]
            missing = not item.get("image") or not item.get("description")
            cache_is_fresh = (
                isinstance(cache, dict)
                and isinstance(cache.get("checked_at"), (int, float))
                and now - cache["checked_at"] < METADATA_CACHE_TTL
            )
            if missing and not cache_is_fresh:
                candidates.append((index, link))

        if not candidates:
            return enriched

        start = self._metadata_cursor % len(candidates)
        selected = (
            candidates[start:] + candidates[:start]
        )[:METADATA_MAX_PER_REFRESH]
        self._metadata_cursor = (start + len(selected)) % len(candidates)
        session = async_get_clientsession(self.hass)
        semaphore = asyncio.Semaphore(METADATA_CONCURRENCY)

        async def fetch(index: int, link: str) -> None:
            async with semaphore:
                try:
                    timeout = aiohttp.ClientTimeout(total=20)
                    async with session.get(
                        link, timeout=timeout, allow_redirects=False
                    ) as response:
                        response.raise_for_status()
                        html = await response.text(errors="ignore")
                    metadata = extract_game_metadata(html, link)
                except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as err:
                    _LOGGER.debug("Could not retrieve metadata for %s: %s", link, err)
                    return

                current = enriched[index]
                for field in ("image", "description"):
                    if not current.get(field) and metadata.get(field):
                        current[field] = metadata[field]
                self._metadata_cache[link] = {
                    **metadata,
                    "checked_at": time.time(),
                }

        await asyncio.gather(*(fetch(index, link) for index, link in selected))
        try:
            await self._metadata_store.async_save(
                {"items": self._metadata_cache, "cursor": self._metadata_cursor}
            )
        except (OSError, ValueError):
            _LOGGER.warning("Could not save DekuDeals game metadata cache")
        return enriched

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Fetch the public JSON export, using saved JSON only as fallback."""
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
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            json.JSONDecodeError,
            CollectionImportError,
        ) as err:
            if not self.fallback_json:
                raise UpdateFailed(
                    f"Unable to refresh DekuDeals collection: {err}"
                ) from err
            _LOGGER.warning(
                "Could not refresh DekuDeals collection; using the saved JSON export: %s",
                err,
            )
            try:
                items = parse_collection_export(self.fallback_json)
            except CollectionImportError as fallback_err:
                raise UpdateFailed(
                    "Both the live collection and saved export are invalid."
                ) from fallback_err

        return await self._async_enrich_metadata(items)
