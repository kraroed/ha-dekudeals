"""Tests for strict external box-art selection."""

from custom_components.dekudeals.artwork import (
    apply_parent_game_artwork,
    normalize_game_title,
    parent_artwork_cache_key,
    select_thegamesdb_front_cover,
    summarize_artwork_coverage,
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



def test_artwork_coverage_reports_counts_and_missing_titles():
    result = summarize_artwork_coverage([
        {"name": "Game One", "image": "https://cdn.example/one.jpg"},
        {"name": "Game Two", "image": None},
        {"name": "Game Three", "image": " "},
    ])
    assert result == {
        "total_items": 3,
        "items_with_artwork": 1,
        "items_missing_artwork": 2,
        "coverage_percent": 33,
        "missing_artwork_sample": ["Game Two", "Game Three"],
        "missing_artwork_sample_truncated": False,
        "artwork_missing_by_reason": {"not_classified": 2},
        "artwork_missing_samples_by_reason": {
            "not_classified": ["Game Two", "Game Three"]
        },
    }


def test_artwork_coverage_handles_empty_collection():
    result = summarize_artwork_coverage([])
    assert result["coverage_percent"] == 0
    assert result["total_items"] == 0


def test_artwork_coverage_bounds_missing_title_sample():
    result = summarize_artwork_coverage([
        {"name": f"Game {index}"} for index in range(30)
    ])
    assert result["items_missing_artwork"] == 30
    assert len(result["missing_artwork_sample"]) == 25
    assert result["missing_artwork_sample_truncated"] is True



def test_dlc_inherits_only_explicit_verified_parent_cover():
    parent_url = "https://dekudeals.com/items/parent"
    dlc_url = "https://dekudeals.com/items/dlc"
    items = [
        {"name": "Parent Game", "link": parent_url, "item_type": "game"},
        {
            "name": "Parent Game Expansion",
            "link": dlc_url,
            "item_type": "dlc",
            "parent_game": "Parent Game",
            "image": "https://example.com/unverified-export-image.jpg",
        },
    ]
    cache = {
        parent_url: {
            "image": "https://cdn.example/verified-parent-cover.jpg",
            "artwork_verified": True,
        },
        dlc_url: {"artwork_verified": False},
    }

    assert apply_parent_game_artwork(items, cache) == 1
    assert items[1]["image"] == "https://cdn.example/verified-parent-cover.jpg"
    assert items[1]["artwork_inherited"] is True


def test_dlc_keeps_its_own_verified_cover_instead_of_parent_cover():
    parent_url = "https://dekudeals.com/items/parent"
    dlc_url = "https://dekudeals.com/items/dlc"
    items = [
        {"name": "Parent Game", "link": parent_url, "item_type": "game"},
        {
            "name": "Parent Game Expansion",
            "link": dlc_url,
            "item_type": "dlc",
            "parent_game": "Parent Game",
        },
    ]
    cache = {
        parent_url: {"image": "https://cdn.example/parent.jpg", "artwork_verified": True},
        dlc_url: {"image": "https://cdn.example/dlc.jpg", "artwork_verified": True},
    }

    assert apply_parent_game_artwork(items, cache) == 0
    assert items[1]["image"] == "https://cdn.example/dlc.jpg"
    assert "artwork_inherited" not in items[1]


def test_unverified_parent_artwork_is_never_inherited():
    parent_url = "https://dekudeals.com/items/parent"
    dlc_url = "https://dekudeals.com/items/dlc"
    items = [
        {"name": "Parent Game", "link": parent_url, "item_type": "game"},
        {
            "name": "Parent Game Expansion",
            "link": dlc_url,
            "item_type": "dlc",
            "parent_game": "Parent Game",
        },
    ]
    cache = {
        parent_url: {"image": "https://cdn.example/unverified.jpg", "artwork_verified": False}
    }

    assert apply_parent_game_artwork(items, cache) == 0
    assert "image" not in items[1]



def test_missing_artwork_diagnostics_distinguish_dlc_relationship_gaps():
    parent_url = "https://dekudeals.com/items/parent"
    items = [
        {"name": "Parent Game", "link": parent_url, "item_type": "game"},
        {"name": "Expansion One", "item_type": "dlc"},
        {
            "name": "Expansion Two",
            "item_type": "dlc",
            "parent_game": "Game Not In Collection",
        },
        {
            "name": "Expansion Three",
            "item_type": "dlc",
            "parent_game": "Parent Game",
        },
        {"name": "Standalone Game", "item_type": "game"},
    ]
    apply_parent_game_artwork(
        items,
        {parent_url: {"image": "https://cdn.example/unverified.jpg", "artwork_verified": False}},
    )

    result = summarize_artwork_coverage(items)
    assert result["artwork_missing_by_reason"] == {
        "parent_cover_not_verified": 1,
        "parent_not_in_collection": 1,
        "parent_relationship_missing": 1,
        "standalone_cover_unavailable": 2,
    }
    assert result["artwork_missing_samples_by_reason"]["parent_relationship_missing"] == [
        "Expansion One"
    ]



def test_dlc_inherits_verified_external_parent_cover_when_parent_is_not_in_collection():
    parent_title = "Parent Game"
    platform = "Switch"
    key = parent_artwork_cache_key(parent_title, platform)
    items = [
        {
            "name": "Parent Game Expansion",
            "item_type": "dlc",
            "parent_game": parent_title,
            "platform": platform,
        }
    ]
    cache = {
        key: {
            "image": "https://cdn.example/verified-external-parent.jpg",
            "artwork_verified": True,
            "checked_at": 12345,
        }
    }

    assert apply_parent_game_artwork(items, cache) == 1
    assert items[0]["image"] == "https://cdn.example/verified-external-parent.jpg"
    assert items[0]["artwork_inherited"] is True
    assert "artwork_missing_reason" not in items[0]


def test_dlc_does_not_inherit_unverified_external_parent_cover():
    key = parent_artwork_cache_key("Parent Game", "Switch")
    items = [
        {
            "name": "Parent Game Expansion",
            "item_type": "dlc",
            "parent_game": "Parent Game",
            "platform": "Switch",
        }
    ]

    assert apply_parent_game_artwork(
        items,
        {key: {"image": "https://cdn.example/unverified.jpg", "artwork_verified": False, "checked_at": 12345}},
    ) == 0
    assert "image" not in items[0]
    assert items[0]["artwork_missing_reason"] == "external_parent_cover_unavailable"



def test_external_parent_artwork_uses_configured_platform_when_item_platform_missing():
    key = parent_artwork_cache_key("Parent Game", "Switch")
    items = [
        {
            "name": "Parent Game Expansion",
            "item_type": "dlc",
            "parent_game": "Parent Game",
        }
    ]
    cache = {
        key: {
            "image": "https://cdn.example/verified-parent.jpg",
            "artwork_verified": True,
            "checked_at": 12345,
        }
    }

    assert apply_parent_game_artwork(items, cache, "Switch") == 1
    assert items[0]["image"] == "https://cdn.example/verified-parent.jpg"
