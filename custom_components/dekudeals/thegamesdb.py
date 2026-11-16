"""TheGamesDB API client for verified front box-art lookup."""

from __future__ import annotations

import asyncio
import logging
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

    async def _async_get_platform_ids(self) -> dict[str, int]:
        """Load and normalize TheGamesDB platform names once per runtime."""
        if self._platform_ids is not None:
            return self._platform_ids
        async with self._session.get(
            f"{_API_BASE}/Platforms",
            params={"apikey": self._api_key},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        platforms = payload.get("data", {}).get("platforms", {})
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
        return result

    async def async_get_front_cover(self, title: str, platform: str) -> str | None:
        """Return a trusted exact-match front cover, or None on any mismatch."""
        if not self._api_key or not title.strip() or not platform.strip():
            return None
        try:
            platform_ids = await self._async_get_platform_ids()
            requested_platform = normalize_game_title(platform)
            platform_id = platform_ids.get(requested_platform)
            if platform_id is None:
                # TheGamesDB often prefixes vendor names (e.g. Sony) while
                # DekuDeals uses the shorter console label. Accept only a
                # whole-token prefix/suffix match, never fuzzy similarity.
                matches = {
                    value for key, value in platform_ids.items()
                    if key.endswith(f" {requested_platform}")
                    or requested_platform.endswith(f" {key}")
                }
                if len(matches) == 1:
                    platform_id = matches.pop()
            if platform_id is None:
                return None
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
                payload: dict[str, Any] = await response.json(content_type=None)
            return select_thegamesdb_front_cover(payload, title, platform_id)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError) as err:
            _LOGGER.debug(
                "TheGamesDB artwork lookup failed for %s (%s): %s",
                title,
                platform,
                err,
            )
            return None
