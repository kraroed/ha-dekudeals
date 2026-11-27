"""TheGamesDB API client for verified front-cover artwork lookup."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp

from .artwork import normalize_game_title, select_thegamesdb_front_cover

_LOGGER = logging.getLogger(__name__)
_API_BASE = "https://api.thegamesdb.net/v1"
_RATE_LIMIT_BACKOFF_INITIAL = 15 * 60
_RATE_LIMIT_BACKOFF_MAX = 6 * 60 * 60
_RATE_LIMIT_HEADER_MAX = 24 * 60 * 60


class TheGamesDBRateLimitedError(Exception):
    """Raised when the provider has asked the client to slow down."""


class TheGamesDBArtworkProvider:
    """Look up physical front box art by exact game title and console."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key.strip()
        self._platform_ids: dict[str, int] | None = None
        self._platform_catalog_valid: bool | None = None
        self._platform_lock = asyncio.Lock()
        self._platform_retry_after = 0.0
        self._rate_limit_retry_after = 0.0
        self._rate_limit_backoff = _RATE_LIMIT_BACKOFF_INITIAL
        self._rate_limit_generation = 0
        self._rate_limit_lock = asyncio.Lock()

    @staticmethod
    def _retry_after_seconds(headers: Any) -> int | None:
        """Parse Retry-After as delta seconds or an HTTP date."""
        value = headers.get("Retry-After") if headers else None
        if not isinstance(value, str) or not value.strip():
            return None
        value = value.strip()
        try:
            seconds = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        if seconds <= 0:
            return 1
        return min(int(seconds + 0.999), _RATE_LIMIT_HEADER_MAX)

    async def _async_record_rate_limit(self, headers: Any) -> None:
        """Set one shared cooldown for every provider endpoint."""
        async with self._rate_limit_lock:
            # Concurrent requests can all receive 429. Count that as one
            # provider event rather than repeatedly extending the cooldown.
            if time.monotonic() < self._rate_limit_retry_after:
                return
            retry_after = self._retry_after_seconds(headers)
            delay = retry_after or self._rate_limit_backoff
            self._rate_limit_generation += 1
            self._rate_limit_retry_after = time.monotonic() + delay
            self._rate_limit_backoff = min(
                self._rate_limit_backoff * 2, _RATE_LIMIT_BACKOFF_MAX
            )
            _LOGGER.warning(
                "TheGamesDB rate limit reached (HTTP 429). Pausing all artwork "
                "lookups for approximately %d seconds%s.",
                delay,
                " as requested by Retry-After" if retry_after else " using backoff",
            )

    async def _async_request_json(self, endpoint: str, params: dict[str, str]) -> Any:
        """Perform a provider request and centrally enforce rate-limit handling."""
        async with self._rate_limit_lock:
            if time.monotonic() < self._rate_limit_retry_after:
                raise TheGamesDBRateLimitedError
            request_generation = self._rate_limit_generation

        async with self._session.get(
            f"{_API_BASE}/{endpoint}",
            params=params,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status == 429:
                await self._async_record_rate_limit(response.headers)
                raise TheGamesDBRateLimitedError
            response.raise_for_status()
            payload = await response.json(content_type=None)
        # A successful response only proves recovery if no newer request has
        # reported a 429 since this request began.
        async with self._rate_limit_lock:
            if request_generation == self._rate_limit_generation:
                self._rate_limit_retry_after = 0.0
                self._rate_limit_backoff = _RATE_LIMIT_BACKOFF_INITIAL
        return payload

    async def _async_get_platform_ids(self) -> dict[str, int]:
        """Load and normalize TheGamesDB platform names once per runtime."""
        if time.monotonic() < self._rate_limit_retry_after:
            raise TheGamesDBRateLimitedError
        if self._platform_ids is not None and time.monotonic() < self._platform_retry_after:
            return self._platform_ids
        if self._platform_ids is not None and self._platform_retry_after == 0:
            return self._platform_ids

        async with self._platform_lock:
            if time.monotonic() < self._rate_limit_retry_after:
                raise TheGamesDBRateLimitedError
            if self._platform_ids is not None and time.monotonic() < self._platform_retry_after:
                return self._platform_ids
            if self._platform_ids is not None and self._platform_retry_after == 0:
                return self._platform_ids
            try:
                payload = await self._async_request_json(
                    "Platforms", {"apikey": self._api_key}
                )
            except TheGamesDBRateLimitedError:
                self._platform_ids = {}
                self._platform_catalog_valid = None
                self._platform_retry_after = self._rate_limit_retry_after
                raise
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
        if time.monotonic() < self._rate_limit_retry_after:
            return None, "provider_rate_limited"

        try:
            platform_ids = await self._async_get_platform_ids()
            if self._platform_catalog_valid is False:
                return None, "invalid_platform_catalog"
            if not platform_ids and time.monotonic() < self._platform_retry_after:
                return None, "platform_catalog_unavailable"

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
            payload: Any = await self._async_request_json(
                "Games/ByGameName",
                {
                    "apikey": self._api_key,
                    "name": title,
                    "filter[platform]": str(platform_id),
                    "include": "boxart,platform",
                },
            )

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
        except TheGamesDBRateLimitedError:
            return None, "provider_rate_limited"
        except aiohttp.ClientResponseError as err:
            _LOGGER.warning(
                "TheGamesDB returned HTTP %s while looking up artwork for %r (%s). "
                "Check TheGamesDB service access and API allowance; HTTP %s does "
                "not by itself establish that the API key is invalid.",
                err.status,
                title,
                platform,
                err.status,
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
