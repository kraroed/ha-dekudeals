"""Tests for strict external box-art selection."""

from custom_components.dekudeals.artwork import (
    normalize_game_title,
    select_thegamesdb_front_cover,
)


def _payload(images, *, title="Example Game", platform=4919):
    return {
        "data": {"games": [{"id": 123, "game_title": title, "platform": platform}]},
        "include": {
            "boxart": {
                "base_url": {"original": "https://cdn.example/images/original/"},
                "data": {"123": images},
            },
            "platform": {"data": {}},
        },
    }


def test_normalizes_punctuation_and_ampersands():
    assert normalize_game_title("Sonic & Knuckles!") == "sonic and knuckles"


def test_selects_front_boxart_with_portrait_dimensions():
    result = select_thegamesdb_front_cover(
        _payload([
            {"type": "boxart", "side": "back", "filename": "back.jpg", "resolution": "600x900"},
            {"type": "boxart", "side": "front", "filename": "boxart/front.jpg", "resolution": "600x900"},
        ]),
        "Example Game",
        4919,
    )
    assert result == "https://cdn.example/images/original/boxart/front.jpg"


def test_rejects_landscape_full_wrap_wrong_side_and_wrong_type():
    result = select_thegamesdb_front_cover(
        _payload([
            {"type": "boxart", "side": "front", "filename": "wrap.jpg", "resolution": "1800x900"},
            {"type": "boxart", "side": "back", "filename": "back.jpg", "resolution": "600x900"},
            {"type": "screenshot", "side": "front", "filename": "shot.jpg", "resolution": "600x900"},
        ]),
        "Example Game",
        4919,
    )
    assert result is None


def test_rejects_wrong_title_or_platform():
    assert select_thegamesdb_front_cover(
        _payload([{"type": "boxart", "side": "front", "filename": "front.jpg", "resolution": "600x900"}]),
        "Different Game",
        4919,
    ) is None
    assert select_thegamesdb_front_cover(
        _payload([{"type": "boxart", "side": "front", "filename": "front.jpg", "resolution": "600x900"}]),
        "Example Game",
        9999,
    ) is None


def test_rejects_untrusted_image_hosts_and_bad_dimensions():
    payload = _payload([
        {"type": "boxart", "side": "front", "filename": "https://evil.example/front.jpg", "resolution": "600x900"},
        {"type": "boxart", "side": "front", "filename": "front.jpg", "resolution": "wide"},
    ])
    assert select_thegamesdb_front_cover(payload, "Example Game", 4919) is None



def test_accepts_explicit_front_cover_when_resolution_is_omitted():
    """TheGamesDB image resolution metadata is optional."""
    payload = _payload([
        {
            "type": "boxart",
            "side": "front",
            "filename": "boxart/front-no-resolution.jpg",
        }
    ])
    assert select_thegamesdb_front_cover(payload, "Example Game", 4919) == (
        "https://cdn.example/images/original/boxart/front-no-resolution.jpg"
    )
