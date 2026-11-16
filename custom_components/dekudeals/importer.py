"""Parsing and normalization for DekuDeals collection exports."""

from __future__ import annotations

import json
from typing import Any


class CollectionImportError(ValueError):
    """Raised when a collection export is invalid."""


def _optional_text(value: Any) -> str | None:
    """Return bounded, normalized optional text."""
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:2000] or None


def _optional_https_url(value: Any) -> str | None:
    """Return only absolute HTTPS image URLs."""
    if not isinstance(value, str) or not value.startswith("https://"):
        return None
    return value[:2048]


def parse_collection_export(raw: str) -> list[dict[str, Any]]:
    """Parse an exported collection while preserving row order and duplicates."""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as err:
        raise CollectionImportError("The collection export is not valid JSON.") from err

    if isinstance(payload, list):
        source_items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        source_items = payload["items"]
    else:
        raise CollectionImportError("Expected a JSON object containing an items array or a JSON array.")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(source_items):
        if not isinstance(item, dict):
            raise CollectionImportError(f"Collection item {index + 1} must be an object.")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CollectionImportError(f"Collection item {index + 1} is missing a name.")
        game_format = str(item.get("format") or "unknown").strip().lower()
        if game_format not in {"physical", "digital"}:
            game_format = "unknown"
        normalized.append(
            {
                "name": name.strip(),
                "link": item.get("link") if isinstance(item.get("link"), str) else None,
                "added_at": item.get("added_at") if isinstance(item.get("added_at"), str) else None,
                "format": game_format,
                "platform": str(item.get("platform") or "Unknown").strip() or "Unknown",
                "note": item.get("note") if isinstance(item.get("note"), str) else None,
                "image": _optional_https_url(item.get("image") or item.get("image_url") or item.get("cover")),
                "description": None,\n                "item_type": "game",\n                "parent_game": None,
                "source_index": index,
            }
        )
    return normalized
