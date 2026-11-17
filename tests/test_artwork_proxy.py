"""Tests for the signed, restricted artwork proxy URLs."""

from urllib.parse import parse_qs, urlparse

from custom_components.dekudeals.artwork_proxy import (
    _is_allowed_artwork_url,
    artwork_proxy_url,
)


def test_allows_only_thegamesdb_front_boxart():
    assert _is_allowed_artwork_url(
        "https://cdn.thegamesdb.net/images/original/boxart/front/42294-1.jpg"
    )


def test_rejects_untrusted_hosts_paths_and_url_components():
    invalid = [
        "http://cdn.thegamesdb.net/images/original/boxart/front/42294-1.jpg",
        "https://evil.example/images/original/boxart/front/42294-1.jpg",
        "https://cdn.thegamesdb.net/images/original/boxart/back/42294-1.jpg",
        "https://cdn.thegamesdb.net/images/original/boxart/front/../secret.jpg",
        "https://cdn.thegamesdb.net/images/original/boxart/front/42294-1.jpg?x=1",
        "https://user@cdn.thegamesdb.net/images/original/boxart/front/42294-1.jpg",
        "https://cdn.thegamesdb.net:443/images/original/boxart/front/42294-1.jpg",
    ]
    assert all(not _is_allowed_artwork_url(url) for url in invalid)


def test_proxy_url_is_signed_and_relative():
    class FakeHass:
        data = {
            "dekudeals": {
                "entries": {
                    "entry-1": {"artwork_proxy_secret": b"x" * 32}
                }
            }
        }

    url = artwork_proxy_url(
        FakeHass(),
        "entry-1",
        "https://cdn.thegamesdb.net/images/original/boxart/front/42294-1.jpg",
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path == "/api/dekudeals/artwork/entry-1"
    assert query["url"]
    assert len(query["sig"][0]) == 64


def test_unapproved_or_unconfigured_images_are_not_proxied():
    class FakeHass:
        data = {"dekudeals": {"entries": {"entry-1": {}}}}

    original = "https://example.com/cover.jpg"
    assert artwork_proxy_url(FakeHass(), "entry-1", original) == original
