"""TheGamesDB API client for verified front box-art lookup."""

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
        self._platform_lock = asyncio.Lock()
        self._platform_retry_after = 0.0

    async def _async_get_platform_ids(self) -> dict[str, int]:
        """Load and normalize TheGamesDB platform names once per runtime."""
        if self._platform_ids is not None and time.monotonic() < self._platform_retry_after:
            return self._platform_ids
        if self._platform_ids is not None and self._platform_retry_after == 0:
            return self._platform_ids

        # Multiple game lookups can start together during a collection refresh.
        # Serialize the initial platform request so we only fetch this catalog once.
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
                # Cache transient failures briefly so each game lookup in the
                # same refresh does not serialize another 20-second timeout.
                self._platform_ids = {}
                self._platform_retry_after = time.monotonic() + 60
                raise

            if not isinstance(payload, dict):
                self._platform_ids = {}
                return self._platform_ids
            data = payload.get("data")
            platforms = data.get("platforms") if isinstance(data, dict) else None
            result: dict[str, int] = {}
            if isinstance(platforms, dict):
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
            self._platform_retry_after = 0.0
            _LOGGER.debug(
                "TheGamesDB platform catalog loaded: %d normalized platform names",
                len(result),
            )
            return result

    async def async_get_front_cover(
        self, title: str, platform: str
    ) -> tuple[str | None, bool]:
        """Return a trusted cover and whether the provider lookup completed.

        A completed no-cover response is a definitive miss. Request failures
        and malformed responses remain retryable and are not cached as checks.
        """
        if not self._api_key or not title.strip() or not platform.strip():
            return None, False
        try:
            platform_ids = await self._async_get_platform_ids()
            if not platform_ids and time.monotonic() < self._platform_retry_after:
                # The platform catalog request failed recently. Its short-lived
                # empty cache is not a definitive unknown-platform result.
                return None, False
            requested_platform = normalize_game_title(platform)
            platform_id = platform_ids.get(requested_platform)
            if platform_id is None:
                # TheGamesDB often prefixes vendor names (e.g. Sony) while
                # DekuDeals uses the shorter console label. Accept only a
                # whole-token prefix/suffix match, never fuzzy similarity.
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
                return None, True
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
                _LOGGER.debug("TheGamesDB returned an invalid game-search response for %r", title)
                return None, False
            game_count = len(games)
            cover = select_thegamesdb_front_cover(payload, title, platform_id)
            _LOGGER.debug(
                "TheGamesDB lookup for %r on platform ID %s returned %d game candidates; verified front cover %s",
                title,
                platform_id,
                game_count,
                "found" if cover else "not found (no exact-title portrait front box art passed validation)",
            )
            return cover, True
        except aiohttp.ClientResponseError as err:
            # Never include request parameters or the API key in diagnostics.
            _LOGGER.warning(
                "TheGamesDB returned HTTP %s while looking up artwork for %r (%s). "
                "Check the configured API key and TheGamesDB service access.",
                err.status,
                title,
                platform,
            )
            return None, False
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
            return None, False
