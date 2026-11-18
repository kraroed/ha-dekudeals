"""Tests for collection artwork coverage diagnostics."""

from types import SimpleNamespace

from custom_components.dekudeals.sensor import COLLECTION_DESCRIPTIONS, DekuDealsSensor


def _coverage_sensor(items):
    description = next(
        item for item in COLLECTION_DESCRIPTIONS if item.key == "artwork_coverage"
    )
    sensor = DekuDealsSensor.__new__(DekuDealsSensor)
    sensor.coordinator = SimpleNamespace(data=items)
    sensor.entity_description = description
    return sensor


def test_artwork_coverage_reports_counts_and_missing_title_sample():
    sensor = _coverage_sensor(
        [
            {"name": "Game One", "image": "https://cdn.example/one.jpg"},
            {"name": "Game Two", "image": None},
            {"name": "Game Three", "image": " "},
        ]
    )

    assert sensor.native_value == 33
    assert sensor.extra_state_attributes == {
        "total_items": 3,
        "items_with_artwork": 1,
        "items_missing_artwork": 2,
        "coverage_percent": 33,
        "missing_artwork_sample": ["Game Two", "Game Three"],
        "missing_artwork_sample_truncated": False,
    }


def test_artwork_coverage_handles_empty_collection():
    sensor = _coverage_sensor([])

    assert sensor.native_value == 0
    assert sensor.extra_state_attributes["total_items"] == 0
    assert sensor.extra_state_attributes["coverage_percent"] == 0


def test_artwork_coverage_limits_missing_title_sample_to_25():
    sensor = _coverage_sensor([{"name": f"Game {index}"} for index in range(30)])

    attributes = sensor.extra_state_attributes
    assert sensor.native_value == 0
    assert len(attributes["missing_artwork_sample"]) == 25
    assert attributes["missing_artwork_sample_truncated"] is True
