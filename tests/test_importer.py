"""Tests for the DekuDeals export parser."""

import pytest

from custom_components.dekudeals.importer import (
    CollectionImportError,
    parse_collection_export,
)


def test_preserves_duplicate_rows_and_order():
    raw = '{"items": [' \
        '{"name": "Same Game", "format": "physical", "platform": "Switch"},' \
        '{"name": "Same Game", "format": "physical", "platform": "Switch"}' \
        ']}'

    items = parse_collection_export(raw)

    assert len(items) == 2
    assert [item["source_index"] for item in items] == [0, 1]
    assert items[0]["name"] == items[1]["name"]


def test_normalizes_missing_fields():
    items = parse_collection_export('{"items":[{"name":"Example"}]}')

    assert items[0]["platform"] == "Unknown"
    assert items[0]["format"] == "unknown"
    assert items[0]["link"] is None
    assert items[0]["added_at"] is None
    assert items[0]["image"] is None
    assert items[0]["description"] is None


def test_keeps_supported_metadata():
    items = parse_collection_export(
        '{"items":[{"name":"Example","link":"https://example.com/game",'
        '"added_at":"2026-01-02","format":"digital","platform":"Switch 2",'
        '"note":"wishlist"}]}'
    )

    assert items[0]["link"] == "https://example.com/game"
    assert items[0]["added_at"] == "2026-01-02"
    assert items[0]["format"] == "digital"
    assert items[0]["platform"] == "Switch 2"
    assert items[0]["note"] == "wishlist"


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        '{"items":"not a list"}',
        '{"items":[null]}',
        '{"items":[{}]}',
        '{"items":[{"name":" " }]}',
    ],
)
def test_rejects_invalid_exports(raw):
    with pytest.raises(CollectionImportError):
        parse_collection_export(raw)


def test_accepts_top_level_array_export():
    items = parse_collection_export(
        '[{"name":"Array Game","format":"physical","platform":"Switch"}]'
    )

    assert len(items) == 1
    assert items[0]["name"] == "Array Game"


def test_accepts_empty_top_level_collection():
    assert parse_collection_export("[]") == []



def test_imports_cover_art_but_ignores_untrusted_export_description():
    items = parse_collection_export(
        '{"items":[{"name":"Example","image":"https://cdn.example/cover.jpg",'
        '"description":"A great game."}]}'
    )

    assert items[0]["image"] == "https://cdn.example/cover.jpg"
    assert items[0]["description"] is None\n    assert items[0]["item_type"] == "game"\n    assert items[0]["parent_game"] is None


def test_rejects_non_https_or_invalid_optional_metadata():
    items = parse_collection_export(
        '{"items":[{"name":"Example","image":"http://example.com/cover.jpg",'
        '"description":123}]}'
    )

    assert items[0]["image"] is None
    assert items[0]["description"] is None
