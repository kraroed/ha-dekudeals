"""Tests for the TheGamesDB artwork API client."""

import asyncio

import aiohttp
import pytest

from custom_components.dekudeals.thegamesdb import TheGamesDBArtworkProvider


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self.payload = payload
        self.status = status
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None,
                history=(),
                status=self.status,
                message="test HTTP error",
                headers=self.headers,
            )

    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, params))
        response = self.payloads.pop(0)
        if isinstance(response, FakeResponse):
            return response
        return FakeResponse(response)


def _platforms_payload():
    return {
        "data": {
            "platforms": {
                "1": {
                    "id": 1,
                    "name": "Nintendo Switch",
                    "alias": "switch",
                }
            }
        }
    }


def _games_payload(title="Example Game", platform=1):
    return {
        "data": {
            "games": [
                {"id": 42, "game_title": title, "platform": platform}
            ]
        },
        "include": {
            "boxart": {
                "base_url": {
                    "original": "https://cdn.thegamesdb.net/images/original/"
                },
                "data": {
                    "42": [
                        {
                            "type": "boxart",
                            "side": "front",
                            "filename": "boxart/front/42-1.jpg",
                            "resolution": "600x900",
                        }
                    ]
                },
            },
            "platform": {"data": {}},
        },
    }


def test_provider_fetches_platform_catalog_once_and_returns_front_cover():
    async def run():
        session = FakeSession([_platforms_payload(), _games_payload()])
        provider = TheGamesDBArtworkProvider(session, "test-key")

        result = await provider.async_get_front_cover("Example Game", "Switch")

        assert result == (
            "https://cdn.thegamesdb.net/images/original/"
            "boxart/front/42-1.jpg",
            True,
        )
        assert len(session.calls) == 2
        assert session.calls[0][0].endswith("/Platforms")
        assert session.calls[1][0].endswith("/Games/ByGameName")
        assert session.calls[1][1]["filter[platform]"] == "1"

    asyncio.run(run())


def test_provider_rejects_unknown_platform_without_game_search():
    async def run():
        session = FakeSession([{"data": {"platforms": {}}}])
        provider = TheGamesDBArtworkProvider(session, "test-key")

        result = await provider.async_get_front_cover("Example Game", "Unknown Console")

        assert result == (None, True)
        assert len(session.calls) == 1

    asyncio.run(run())


def test_provider_does_not_fetch_without_api_key():
    async def run():
        session = FakeSession([])
        provider = TheGamesDBArtworkProvider(session, "")

        result = await provider.async_get_front_cover("Example Game", "Switch")

        assert result == (None, False)
        assert session.calls == []

    asyncio.run(run())


def test_platform_catalog_failure_is_cached_briefly_then_retried(monkeypatch):
    from types import SimpleNamespace

    from custom_components.dekudeals import thegamesdb as module

    class FailingOnceSession(FakeSession):
        def __init__(self):
            super().__init__([_platforms_payload(), _games_payload()])
            self.attempts = 0

        def get(self, url, *, params, timeout):
            self.attempts += 1
            if self.attempts == 1:
                raise asyncio.TimeoutError
            return super().get(url, params=params, timeout=timeout)

    async def run():
        clock = [1000.0]
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        session = FailingOnceSession()
        provider = TheGamesDBArtworkProvider(session, "test-key")

        assert await provider.async_get_front_cover("Example Game", "Switch") == (None, False)
        assert session.attempts == 1

        # A second title lookup in the same refresh reuses the cached failure.
        assert await provider.async_get_front_cover("Another Game", "Switch") == (None, False)
        assert session.attempts == 1

        # The negative cache expires and the provider can recover.
        clock[0] += 61
        assert await provider.async_get_front_cover("Example Game", "Switch") == (
            "https://cdn.thegamesdb.net/images/original/boxart/front/42-1.jpg",
            True,
        )
        assert session.attempts == 3

    asyncio.run(run())


def test_provider_diagnostic_distinguishes_no_game_candidates():
    async def run():
        session = FakeSession([
            _platforms_payload(),
            {"data": {"games": []}},
            {"data": {"games": []}},
        ])
        provider = TheGamesDBArtworkProvider(session, "test-key")

        assert await provider.async_get_front_cover_diagnostic(
            "Missing Game", "Switch"
        ) == (None, "no_game_candidates")
        assert await provider.async_get_front_cover(
            "Missing Game", "Switch"
        ) == (None, True)

    asyncio.run(run())


def test_provider_diagnostic_distinguishes_candidate_without_verified_front_cover():
    async def run():
        payload = _games_payload()
        payload["include"]["boxart"]["data"]["42"] = [
            {
                "type": "boxart",
                "side": "back",
                "filename": "boxart/back.jpg",
                "resolution": "600x900",
            }
        ]
        session = FakeSession([_platforms_payload(), payload])
        provider = TheGamesDBArtworkProvider(session, "test-key")

        assert await provider.async_get_front_cover_diagnostic(
            "Example Game", "Switch"
        ) == (None, "no_verified_front_cover")

    asyncio.run(run())


def test_provider_diagnostic_marks_malformed_platform_catalog_retryable():
    async def run():
        session = FakeSession([{"data": {"platforms": []}}])
        provider = TheGamesDBArtworkProvider(session, "test-key")

        assert await provider.async_get_front_cover_diagnostic(
            "Example Game", "Switch"
        ) == (None, "invalid_platform_catalog")
        assert await provider.async_get_front_cover_diagnostic(
            "Example Game", "Switch"
        ) == (None, "invalid_platform_catalog")
        assert await provider.async_get_front_cover(
            "Example Game", "Switch"
        ) == (None, False)

    asyncio.run(run())


def test_http_429_honors_retry_after_and_pauses_all_lookups(monkeypatch):
    from types import SimpleNamespace

    from custom_components.dekudeals import thegamesdb as module

    async def run():
        clock = [1000.0]
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        session = FakeSession([
            FakeResponse({}, status=429, headers={"Retry-After": "120"}),
            _platforms_payload(),
            _games_payload(),
        ])
        provider = TheGamesDBArtworkProvider(session, "test-key")

        assert await provider.async_get_front_cover_diagnostic(
            "First Game", "Switch"
        ) == (None, "provider_rate_limited")
        assert len(session.calls) == 1

        # The cooldown is provider-wide: another title does not trigger even
        # a platform-catalog request while the Retry-After window is active.
        assert await provider.async_get_front_cover_diagnostic(
            "Second Game", "Switch"
        ) == (None, "provider_rate_limited")
        assert len(session.calls) == 1

        clock[0] += 121
        assert await provider.async_get_front_cover_diagnostic(
            "Example Game", "Switch"
        ) == (
            "https://cdn.thegamesdb.net/images/original/boxart/front/42-1.jpg",
            "verified_cover",
        )
        assert len(session.calls) == 3

    asyncio.run(run())


def test_http_429_uses_exponential_backoff_when_retry_after_missing(monkeypatch):
    from types import SimpleNamespace

    from custom_components.dekudeals import thegamesdb as module

    async def run():
        clock = [500.0]
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        session = FakeSession([
            FakeResponse({}, status=429),
            _platforms_payload(),
            _games_payload(),
        ])
        provider = TheGamesDBArtworkProvider(session, "test-key")

        assert await provider.async_get_front_cover_diagnostic(
            "First Game", "Switch"
        ) == (None, "provider_rate_limited")
        assert provider._rate_limit_retry_after == 500 + 15 * 60
        assert provider._rate_limit_backoff == 30 * 60
        assert await provider.async_get_front_cover_diagnostic(
            "Second Game", "Switch"
        ) == (None, "provider_rate_limited")
        assert len(session.calls) == 1

    asyncio.run(run())



def test_stale_success_does_not_clear_newer_rate_limit(monkeypatch):
    from types import SimpleNamespace
    from custom_components.dekudeals import thegamesdb as module

    class BlockingResponse(FakeResponse):
        def __init__(self, started, release):
            super().__init__({"data": {"ok": True}})
            self.started = started
            self.release = release

        async def __aenter__(self):
            self.started.set()
            await self.release.wait()
            return self

    class BlockingSession:
        def __init__(self, response):
            self.response = response

        def get(self, url, *, params, timeout):
            return self.response

    async def run():
        clock = [1000.0]
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        started = asyncio.Event()
        release = asyncio.Event()
        provider = TheGamesDBArtworkProvider(
            BlockingSession(BlockingResponse(started, release)), "test-key"
        )
        request = asyncio.create_task(provider._async_request_json("Games", {}))
        await started.wait()
        await provider._async_record_rate_limit({"Retry-After": "120"})
        release.set()

        assert await request == {"data": {"ok": True}}
        assert provider._rate_limit_retry_after == 1120.0
        assert provider._rate_limit_backoff == 30 * 60
        with pytest.raises(module.TheGamesDBRateLimitedError):
            await provider._async_request_json("Games", {})

    asyncio.run(run())
