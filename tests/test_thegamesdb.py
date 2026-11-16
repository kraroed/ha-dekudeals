"""Tests for the TheGamesDB artwork API client."""

import asyncio

from custom_components.dekudeals.thegamesdb import TheGamesDBArtworkProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        return None

    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, params))
        return FakeResponse(self.payloads.pop(0))


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
            "boxart/front/42-1.jpg"
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

        assert result is None
        assert len(session.calls) == 1

    asyncio.run(run())


def test_provider_does_not_fetch_without_api_key():
    async def run():
        session = FakeSession([])
        provider = TheGamesDBArtworkProvider(session, "")

        result = await provider.async_get_front_cover("Example Game", "Switch")

        assert result is None
        assert session.calls == []

    asyncio.run(run())
