"""Tests for safe DekuDeals page metadata extraction."""

from custom_components.dekudeals.metadata import extract_game_metadata, is_dekudeals_item_url


def test_extracts_cover_and_actual_description_not_social_promo_copy():
    html = """
    <meta property="og:image" content="https://cdn.example/game-cover.jpg">
    <meta property="og:description" content="Save 50% this week!">
    <h2>Description</h2><p>An actual game description.</p>
    <h2>Screenshots</h2><p>Screenshot gallery</p>
    """
    result = extract_game_metadata(html, "https://www.dekudeals.com/items/example")
    assert result == {
        "image": "https://cdn.example/game-cover.jpg",
        "description": "An actual game description.",
        "item_type": "game",
        "parent_game": None,
    }


def test_extracts_dlc_parent_and_description():
    html = """
    <h1>Expansion Pack</h1><h4>DLC for Example Game</h4>
    <h2>Details</h2><p>Current prices</p>
    <h2>Description</h2><p>Includes new levels and characters.</p>
    <h2>Screenshots</h2>
    """
    result = extract_game_metadata(html, "https://www.dekudeals.com/items/example-dlc")
    assert result["item_type"] == "dlc"
    assert result["parent_game"] == "Example Game"
    assert result["description"] == "Includes new levels and characters."


def test_description_is_empty_when_only_promotional_metadata_exists():
    html = '<meta property="og:description" content="On sale now">'
    result = extract_game_metadata(html, "https://www.dekudeals.com/items/example")
    assert result["description"] is None


def test_rejects_non_https_cover_images():
    html = '<meta property="og:image" content="http://example.com/cover.jpg">'
    result = extract_game_metadata(html, "https://www.dekudeals.com/items/example")
    assert result["image"] is None


def test_only_fetches_https_dekudeals_item_pages():
    assert is_dekudeals_item_url("https://www.dekudeals.com/items/example")
    assert is_dekudeals_item_url("https://dekudeals.com/items/example")
    assert not is_dekudeals_item_url("http://www.dekudeals.com/items/example")
    assert not is_dekudeals_item_url("https://www.dekudeals.com:8443/items/example")
    assert not is_dekudeals_item_url("https://example.com/items/example")
    assert not is_dekudeals_item_url("https://www.dekudeals.com/collection/example")
