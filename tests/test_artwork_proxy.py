"""Tests for the signed same-origin TheGamesDB artwork proxy."""

from custom_components.dekudeals.artwork_proxy import (
    build_artwork_proxy_url,
    is_allowed_artwork_url,
    _safe_redirect_target,
)


def test_allows_only_https_thegamesdb_front_cover_paths():
    assert is_allowed_artwork_url(
        "https://cdn.thegamesdb.net/images/original/boxart/front/42294-1.jpg"
    )
    assert not is_allowed_artwork_url(
        "http://cdn.thegamesdb.net/images/original/boxart/front/42294-1.jpg"
    )
    assert not is_allowed_artwork_url(
        "https://example.com/images/original/boxart/front/42294-1.jpg"
    )
    assert not is_allowed_artwork_url(
        "https://cdn.thegamesdb.net/images/original/boxart/back/42294-1.jpg"
    )
    assert not is_allowed_artwork_url(
        "https://cdn.thegamesdb.net/images/original/boxart/front/../secret.jpg"
    )
    assert not is_allowed_artwork_url(
        "https://cdn.thegamesdb.net/images/original/boxart/front/cover.jpg?redirect=https://evil.example"
    )


def test_builds_signed_same_origin_url_for_allowed_cover():
    url = "https://cdn.thegamesdb.net/images/original/boxart/front/42294-1.jpg"
    result = build_artwork_proxy_url("entry-123", "secret", url)
    assert result.startswith("/api/dekudeals/artwork/entry-123?")
    assert "url=https%3A%2F%2Fcdn.thegamesdb.net" in result
    assert "sig=" in result


def test_leaves_non_thegamesdb_images_unchanged():
    url = "https://images.example/cover.jpg"
    assert build_artwork_proxy_url("entry-123", "secret", url) == url


def test_allows_only_same_host_front_cover_redirects():
    source = "https://cdn.thegamesdb.net/images/original/boxart/front/cover.jpg"
    assert _safe_redirect_target(
        source, "/images/original/boxart/front/cover-v2.jpg"
    ) == "https://cdn.thegamesdb.net/images/original/boxart/front/cover-v2.jpg"
    assert _safe_redirect_target(
        source, "https://cdn.thegamesdb.net/images/original/boxart/front/final.jpg"
    ) == "https://cdn.thegamesdb.net/images/original/boxart/front/final.jpg"
    assert _safe_redirect_target(source, "https://evil.example/cover.jpg") is None
    assert _safe_redirect_target(
        source, "https://cdn.thegamesdb.net/images/original/boxart/back/cover.jpg"
    ) is None
    assert _safe_redirect_target(source, None) is None
