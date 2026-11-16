"""Tests for safe DekuDeals page metadata extraction."""

from custom_components.dekudeals.metadata import (
    extract_game_metadata,
    is_dekudeals_item_url,
)


def test_extracts_open_graph_cover_and_description():
    html = """
    <html><head>
      <meta property="og:image" content="https://cdn.example/game-cover.jpg">
      <meta property="og:description" content="  An   excellent game. ">
    </head></html>
    """

    assert extract_game_metadata(
        html, "https://www.dekudeals.com/items/example"
    ) == {
        "image": "https://cdn.example/game-cover.jpg",
        "description": "An excellent game.",
    }


def test_extracts_standard_description_and_resolves_relative_cover():
    html = """
    <meta name="description" content="A game description">
    <meta name="twitter:image" content="/images/cover.jpg">
    """

    assert extract_game_metadata(
        html, "https://www.dekudeals.com/items/example"
    ) == {
        "image": "https://www.dekudeals.com/images/cover.jpg",
        "description": "A game description",
    }


def test_rejects_non_https_cover_images():
    html = '<meta property="og:image" content="http://example.com/cover.jpg">'

    assert extract_game_metadata(
        html, "https://www.dekudeals.com/items/example"
    ) == {"image": None, "description": None}


def test_only_fetches_https_dekudeals_item_pages():
    assert is_dekudeals_item_url("https://www.dekudeals.com/items/example")
    assert is_dekudeals_item_url("https://dekudeals.com/items/example")
    assert not is_dekudeals_item_url("http://www.dekudeals.com/items/example")
    assert not is_dekudeals_item_url("https://www.dekudeals.com:8443/items/example")
    assert not is_dekudeals_item_url("https://example.com/items/example")
    assert not is_dekudeals_item_url("https://www.dekudeals.com/collection/example")



def test_uses_json_ld_when_social_metadata_is_missing():
    html = '''
    <script type="application/ld+json">
    {"@type":"VideoGame","description":"Structured description","image":["https://cdn.example/cover.jpg"]}
    </script>
    '''

    assert extract_game_metadata(
        html, "https://www.dekudeals.com/items/example"
    ) == {
        "image": "https://cdn.example/cover.jpg",
        "description": "Structured description",
    }
