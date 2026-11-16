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
from .importer import CollectionImportError, filter_collection_platform, parse_collection_export
from .metadata import extract_game_metadata, is_dekudeals_item_url
from .thegamesdb import TheGamesDBArtworkProvider

_LOGGER = logging.getLogger(__name__)
METADATA_CACHE_VERSION = 2
METADATA_MAX_PER_REFRESH = 20
METADATA_CONCURRENCY = 3
METADATA_CACHE_TTL = 30 * 24 * 60 * 60
METADATA_MISS_RETRY_TTL = 7 * 24 * 60 * 60


class DekuDealsCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Fetch a public collection and enrich rows with cached game metadata."""

    def __init__(
        self,
        hass: HomeAssistant,
        collection_url: str,
        fallback_json: str | None = None,
        entry_id: str = "default",
        platform: str = "Switch",
        thegamesdb_api_key: str | None = None,
    ) -> None:
        self.collection_url = collection_url.rstrip("/")
        self.platform = " ".join((platform or "Switch").split())
        self.fallback_json = fallback_json.strip() if fallback_json else None
        self._thegamesdb_api_key = (thegamesdb_api_key or "").strip()
        self._artwork_provider: TheGamesDBArtworkProvider | None = None
        self._metadata_store = Store(
            hass, METADATA_CACHE_VERSION, f"{DOMAIN}_{entry_id}_game_metadata_v4"
        )
        self._metadata_cache: dict[str, dict[str, Any]] | None = None
        self._metadata_cursor = 0
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{self.platform.casefold().replace(' ', '_')}",
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
                if cache.get("item_type") in {"game", "dlc"}:
                    item["item_type"] = cache["item_type"]
                if isinstance(cache.get("parent_game"), str):
                    item["parent_game"] = cache["parent_game"]
            missing = (
                not item.get("image")
                or not item.get("description")
                or not cache
                or not cache.get("item_type")
            )
            # Successful artwork can remain cached for 30 days. If no verified
            # image was found, retry sooner so newly added provider artwork can
            # appear without waiting a full month.
            cache_ttl = (
                METADATA_CACHE_TTL
                if isinstance(cache, dict) and cache.get("image")
                else METADATA_MISS_RETRY_TTL
            )
            cache_is_fresh = (
                isinstance(cache, dict)
                and isinstance(cache.get("checked_at"), (int, float))
                and now - cache["checked_at"] < cache_ttl
            )
            # A cache entry created before the API key was configured has
            # no TheGamesDB check marker. Force one provider lookup for those
            # previously missing covers, without discarding cached descriptions
            # or waiting for the normal seven-day miss retry interval.
            provider_needs_check = bool(
                self._thegamesdb_api_key
                and isinstance(cache, dict)
                and not cache.get("thegamesdb_checked_at")
                and not item.get("image")
            )
            if missing and (not cache_is_fresh or provider_needs_check):
                candidates.append((index, link))

        if not candidates:
            return enriched

        start = self._metadata_cursor % len(candidates)
        selected = (candidates[start:] + candidates[:start])[:METADATA_MAX_PER_REFRESH]
        self._metadata_cursor = (start + len(selected)) % len(candidates)
        session = async_get_clientsession(self.hass)
        semaphore = asyncio.Semaphore(METADATA_CONCURRENCY)
        if self._thegamesdb_api_key and self._artwork_provider is None:
            self._artwork_provider = TheGamesDBArtworkProvider(
                session, self._thegamesdb_api_key
            )

        async def fetch(index: int, link: str) -> None:
            async with semaphore:
                metadata: dict[str, Any] = {}
                try:
                    timeout = aiohttp.ClientTimeout(total=20)
                    async with session.get(
                        link, timeout=timeout, allow_redirects=False
                    ) as response:
                        response.raise_for_status()
                        html = await response.text(errors="ignore")
                    metadata = extract_game_metadata(html, link)
                except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as err:
                    _LOGGER.debug(
                        "Could not retrieve DekuDeals metadata for %s: %s", link, err
                    )

                # A failed or incomplete DekuDeals page must not prevent the
                # independent box-art provider from finding a verified cover.
                provider_checked = False
                if not metadata.get("image") and self._artwork_provider is not None:
                    cover = await self._artwork_provider.async_get_front_cover(
                        str(enriched[index].get("name") or ""),
                        str(enriched[index].get("platform") or self.platform),
                    )
                    provider_checked = True
                    if cover:
                        metadata["image"] = cover

                current = enriched[index]
                for field in ("image", "description", "item_type", "parent_game"):
                    if metadata.get(field) is not None:
                        current[field] = metadata[field]
                cache_entry = {
                    **metadata,
                    "checked_at": time.time(),
                }
                if provider_checked:
                    cache_entry["thegamesdb_checked_at"] = time.time()
                elif isinstance(self._metadata_cache.get(link), dict):
                    previous_provider_check = self._metadata_cache[link].get(
                        "thegamesdb_checked_at"
                    )
                    if previous_provider_check:
                        cache_entry["thegamesdb_checked_at"] = previous_provider_check
                self._metadata_cache[link] = cache_entry

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

        selected_items = filter_collection_platform(items, self.platform)
        return await self._async_enrich_metadata(selected_items)
