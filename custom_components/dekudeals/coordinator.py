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
METADATA_MAX_PER_REFRESH = 50
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

    async def async_refresh_artwork(self) -> None:
        """Force a fresh TheGamesDB lookup without clearing saved metadata."""
        await self._async_load_metadata_cache()
        assert self._metadata_cache is not None
        for cache_entry in self._metadata_cache.values():
            cache_entry.pop("thegamesdb_checked_at", None)
            cache_entry.pop("checked_at", None)
        self._metadata_cursor = 0
        _LOGGER.info(
            "Starting forced artwork refresh for %s (%d cached game entries)",
            self.platform,
            len(self._metadata_cache),
        )
        await self.async_request_refresh()

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
                # Older releases cached image URLs without recording whether
                # they were verified front covers. Never continue displaying
                # those legacy URLs as artwork.
                cached_artwork_verified = cache.get("artwork_verified") is True
                if (
                    cached_artwork_verified
                    and isinstance(cache.get("image"), str)
                ):
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
                if (
                    isinstance(cache, dict)
                    and cache.get("image")
                    and cache.get("artwork_verified") is True
                )
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
                and (
                    not isinstance(cache, dict)
                    or not isinstance(cache.get("thegamesdb_checked_at"), (int, float))
                    or now - cache["thegamesdb_checked_at"] >= METADATA_MISS_RETRY_TTL
                )
            )
            # One-time migration for legacy cached URLs: re-fetch the product
            # page and query TheGamesDB instead of trusting an image whose
            # dimensions and front-cover status were never verified.
            legacy_artwork_needs_check = bool(
                isinstance(cache, dict)
                and isinstance(cache.get("image"), str)
                and cache.get("artwork_verified") is not True
                and not cache.get("artwork_revalidated_at")
            )
            if (
                (missing and (not cache_is_fresh or legacy_artwork_needs_check))
                or provider_needs_check
            ):
                candidates.append((index, link))

        if not candidates:
            inherited_count = apply_parent_game_artwork(enriched, self._metadata_cache)
            if inherited_count:
                _LOGGER.debug(
                    "DekuDeals metadata refresh for %s: reused verified parent-game artwork for %d DLC entries",
                    self.platform,
                    inherited_count,
                )
            _LOGGER.debug(
                "DekuDeals metadata refresh for %s: no eligible missing metadata items",
                self.platform,
            )
            return enriched

        start = self._metadata_cursor % len(candidates)
        selected = (candidates[start:] + candidates[:start])[:METADATA_MAX_PER_REFRESH]
        self._metadata_cursor = (start + len(selected)) % len(candidates)
        _LOGGER.debug(
            "DekuDeals metadata refresh for %s: %d items need metadata; selected %d (maximum %d per refresh); TheGamesDB key configured: %s",
            self.platform,
            len(candidates),
            len(selected),
            METADATA_MAX_PER_REFRESH,
            bool(self._thegamesdb_api_key),
        )
        session = async_get_clientsession(self.hass)
        semaphore = asyncio.Semaphore(METADATA_CONCURRENCY)
        if self._thegamesdb_api_key and self._artwork_provider is None:
            self._artwork_provider = TheGamesDBArtworkProvider(
                session, self._thegamesdb_api_key
            )

        artwork_found = 0
        provider_attempts = 0

        async def fetch(index: int, link: str) -> None:
            nonlocal artwork_found, provider_attempts
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
                    _LOGGER.debug(
                        "DekuDeals metadata page processed for %r: image=%s, description=%s, item_type=%s",
                        enriched[index].get("name"),
                        bool(metadata.get("image")),
                        bool(metadata.get("description")),
                        bool(metadata.get("item_type")),
                    )
                except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as err:
                    _LOGGER.debug(
                        "Could not retrieve DekuDeals metadata for %s: %s", link, err
                    )

                # TheGamesDB is the preferred artwork source. Always try it
                # before accepting DekuDeals artwork, even when the collection
                # export already contains a landscape/promotional image.
                provider_checked = False
                provider_cover = None
                if self._artwork_provider is not None:
                    provider_attempts += 1
                    _LOGGER.debug(
                        "Attempting TheGamesDB front-cover lookup for %r on %r",
                        enriched[index].get("name"),
                        enriched[index].get("platform") or self.platform,
                    )
                    provider_cover, provider_checked = await self._artwork_provider.async_get_front_cover(
                        str(enriched[index].get("name") or ""),
                        str(enriched[index].get("platform") or self.platform),
                    )
                    if provider_cover:
                        artwork_found += 1

                current = enriched[index]
                fallback_image = current.get("image") or metadata.get("image")
                selected_image = provider_cover or fallback_image
                if selected_image:
                    current["image"] = selected_image
                for field in ("description", "item_type", "parent_game"):
                    if metadata.get(field) is not None:
                        current[field] = metadata[field]
                # Preserve previously fetched descriptions and DLC metadata
                # when a transient page failure prevents refreshing them.
                previous_cache = self._metadata_cache.get(link)
                previous_artwork_verified = bool(
                    isinstance(previous_cache, dict)
                    and previous_cache.get("artwork_verified") is True
                    and previous_cache.get("image")
                )
                cache_entry = (
                    dict(previous_cache)
                    if isinstance(previous_cache, dict) and previous_artwork_verified
                    else (
                        {
                            key: value
                            for key, value in previous_cache.items()
                            if key not in {"image", "artwork_verified"}
                        }
                        if isinstance(previous_cache, dict)
                        else {}
                    )
                )
                cache_entry.update(
                    {key: value for key, value in metadata.items()
                     if key != "image" and value is not None}
                )
                if selected_image:
                    cache_entry["image"] = selected_image
                cache_entry["checked_at"] = time.time()
                cache_entry["artwork_verified"] = bool(
                    provider_cover or previous_artwork_verified
                )
                cache_entry["artwork_source"] = (
                    "thegamesdb" if (provider_cover or previous_artwork_verified)
                    else "thegamesdb_unavailable" if provider_checked
                    else cache_entry.get("artwork_source", "dekudeals")
                )
                cache_entry["artwork_revalidated_at"] = time.time()
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
        inherited_count = apply_parent_game_artwork(enriched, self._metadata_cache)
        if inherited_count:
            _LOGGER.debug(
                "DekuDeals metadata refresh for %s: inherited verified parent-game artwork for %d DLC entries",
                self.platform,
                inherited_count,
            )
        _LOGGER.debug(
            "DekuDeals metadata refresh for %s completed: %d TheGamesDB lookups attempted; %d new verified cover URLs found",
            self.platform,
            provider_attempts,
            artwork_found,
        )
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
