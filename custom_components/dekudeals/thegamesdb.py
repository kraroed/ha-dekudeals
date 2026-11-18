"""TheGamesDB API client for verified front-cover artwork lookup."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .artwork import normalize_game_title, select_thegamesdb_front_cover

_LOGGER = logging.getLogger(__name__)
_API_BASE = "https://api.thegamesdb.net/v1"


class TheGamesDBArtworkProvider:
    """Look up physical front box art by exact game title and console."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key.strip()
        self._platform_ids: dict[str, int] | None = None
        self._platform_catalog_valid: bool | None = None
        self._platform_lock = asyncio.Lock()
        self._platform_retry_after = 0.0

    async def _async_get_platform_ids(self) -> dict[str, int]:
        """Load and normalize TheGamesDB platform names once per runtime."""
        if self._platform_ids is not None and time.monotonic() < self._platform_retry_after:
            return self._platform_ids
        if self._platform_ids is not None and self._platform_retry_after == 0:
            return self._platform_ids

        async with self._platform_lock:
            if self._platform_ids is not None and time.monotonic() < self._platform_retry_after:
                return self._platform_ids
            if self._platform_ids is not None and self._platform_retry_after == 0:
                return self._platform_ids
            try:
                async with self._session.get(
                    f"{_API_BASE}/Platforms",
                    params={"apikey": self._api_key},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                self._platform_ids = {}
                self._platform_catalog_valid = None
                self._platform_retry_after = time.monotonic() + 60
                raise

            data = payload.get("data") if isinstance(payload, dict) else None
            platforms = data.get("platforms") if isinstance(data, dict) else None
            if not isinstance(platforms, dict):
                self._platform_ids = {}
                self._platform_catalog_valid = False
                # Malformed catalog payloads are transient; retry after a short cooldown.
                self._platform_retry_after = time.monotonic() + 60
                return self._platform_ids

            result: dict[str, int] = {}
            for platform in platforms.values():
                if not isinstance(platform, dict):
                    continue
                platform_id = platform.get("id")
                name = platform.get("name")
                alias = platform.get("alias")
                if not isinstance(platform_id, int):
                    continue
                for value in (name, alias):
                    if isinstance(value, str) and value.strip():
                        result[normalize_game_title(value)] = platform_id
            self._platform_ids = result
            self._platform_catalog_valid = True
            self._platform_retry_after = 0.0
            _LOGGER.debug(
                "TheGamesDB platform catalog loaded: %d normalized platform names",
                len(result),
            )
            return result

    async def async_get_front_cover_diagnostic(
        self, title: str, platform: str
    ) -> tuple[str | None, str]:
        """Return a verified cover and a machine-readable lookup outcome.

        Outcomes distinguish definitive misses from provider/configuration
        failures so diagnostics never present a transport failure as no match.
        """
        if not self._api_key:
            return None, "api_key_missing"
        if not title.strip() or not platform.strip():
            return None, "invalid_lookup_input"

        try:
            platform_ids = await self._async_get_platform_ids()
            if not platform_ids and time.monotonic() < self._platform_retry_after:
                return None, "platform_catalog_unavailable"
            if self._platform_catalog_valid is False:
                return None, "invalid_platform_catalog"

            requested_platform = normalize_game_title(platform)
            platform_id = platform_ids.get(requested_platform)
            if platform_id is None:
                matches = {
                    value
                    for key, value in platform_ids.items()
                    if key.endswith(f" {requested_platform}")
                    or requested_platform.endswith(f" {key}")
                }
                if len(matches) == 1:
                    platform_id = matches.pop()
            if platform_id is None:
                _LOGGER.debug(
                    "TheGamesDB has no platform mapping for DekuDeals platform %r",
                    platform,
                )
                return None, "platform_unmapped"

            _LOGGER.debug(
                "TheGamesDB platform mapping for %r resolved to ID %s",
                platform,
                platform_id,
            )
            async with self._session.get(
                f"{_API_BASE}/Games/ByGameName",
                params={
                    "apikey": self._api_key,
                    "name": title,
                    "filter[platform]": str(platform_id),
                    "include": "boxart,platform",
                },
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                response.raise_for_status()
                payload: Any = await response.json(content_type=None)

            data = payload.get("data") if isinstance(payload, dict) else None
            games = data.get("games") if isinstance(data, dict) else None
            if not isinstance(games, list):
                _LOGGER.debug(
                    "TheGamesDB returned an invalid game-search response for %r",
                    title,
                )
                return None, "invalid_game_search_response"
            if not games:
                _LOGGER.debug(
                    "TheGamesDB found no exact-title candidates for %r on %r",
                    title,
                    platform,
                )
                return None, "no_game_candidates"

            cover = select_thegamesdb_front_cover(payload, title, platform_id)
            if cover:
                _LOGGER.debug(
                    "TheGamesDB verified a front cover for %r on %r",
                    title,
                    platform,
                )
                return cover, "verified_cover"

            _LOGGER.debug(
                "TheGamesDB returned %d candidate(s) for %r on %r, but none had "
                "an exact-title portrait front cover that passed validation",
                len(games),
                title,
                platform,
            )
            return None, "no_verified_front_cover"
        except aiohttp.ClientResponseError as err:
            _LOGGER.warning(
                "TheGamesDB returned HTTP %s while looking up artwork for %r (%s). "
                "Check the configured API key and TheGamesDB service access.",
                err.status,
                title,
                platform,
            )
            return None, "provider_http_error"
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as err:
            _LOGGER.debug(
                "TheGamesDB artwork lookup failed for %r (%s): %s",
                title,
                platform,
                err,
            )
            return None, "provider_request_error"

    async def async_get_front_cover(
        self, title: str, platform: str
    ) -> tuple[str | None, bool]:
        """Return a trusted cover and whether the provider lookup completed."""
        cover, status = await self.async_get_front_cover_diagnostic(title, platform)
        return cover, status in {
            "verified_cover",
            "platform_unmapped",
            "no_game_candidates",
            "no_verified_front_cover",
        }
