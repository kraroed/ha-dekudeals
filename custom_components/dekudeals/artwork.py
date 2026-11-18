"""Artwork provider response parsing and validation helpers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse


def normalize_game_title(value: str) -> str:
    """Normalize titles for conservative provider matching."""
    value = value.casefold().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def select_thegamesdb_front_cover(
    payload: dict[str, Any],
    requested_title: str,
    requested_platform_id: int,
) -> str | None:
    """Select only an exact-title, exact-platform, portrait front box-art image.

    TheGamesDB explicitly labels box-art images by type and side. Do not accept
    backs, banners, screenshots, or images from another platform.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    include = payload.get("include")
    if not isinstance(data, dict) or not isinstance(include, dict):
        return None
    games = data.get("games")
    boxart = include.get("boxart")
    if not isinstance(games, list) or not isinstance(boxart, dict):
        return None
    base_urls = boxart.get("base_url")
    image_map = boxart.get("data")
    if not isinstance(base_urls, dict) or not isinstance(image_map, dict):
        return None
    base_url = base_urls.get("original")
    if not isinstance(base_url, str) or urlparse(base_url).scheme != "https" or not urlparse(base_url).hostname:
        return None

    target = normalize_game_title(requested_title)
    for game in games:
        if not isinstance(game, dict):
            continue
        if game.get("platform") != requested_platform_id:
            continue
        if normalize_game_title(str(game.get("game_title") or "")) != target:
            continue
        images = image_map.get(str(game.get("id")), [])
        if not isinstance(images, list):
            continue
        for image in images:
            if not isinstance(image, dict):
                continue
            if image.get("type") != "boxart" or image.get("side") != "front":
                continue
            # Resolution is optional in TheGamesDB image records. If present,
            # enforce portrait dimensions; if absent, trust explicit boxart/front labels.
            resolution = image.get("resolution")
            if resolution is not None:
                if not isinstance(resolution, str):
                    continue
                match = re.fullmatch(r"(\d+)x(\d+)", resolution.strip())
                if not match:
                    continue
                width, height = (int(part) for part in match.groups())
                if width <= 0 or height <= 0:
                    continue
                ratio = width / height
                if not 0.48 <= ratio <= 0.85:
                    continue
            filename = image.get("filename")
            if (
                not isinstance(filename, str)
                or not filename
                or filename.startswith(("/", "\\\\"))
            ):
                continue
            image_url = urljoin(base_url.rstrip("/") + "/", filename)
            parsed = urlparse(image_url)
            if parsed.scheme == "https" and parsed.hostname == urlparse(base_url).hostname:
                return image_url
    return None




def parent_artwork_cache_key(parent_title: str, platform: str) -> str:
    """Build a stable cache key for an external parent-game artwork lookup."""
    return (
        "__thegamesdb_parent__:"
        f"{normalize_game_title(platform)}:"
        f"{normalize_game_title(parent_title)}"
    )


def apply_parent_game_artwork(
    items: list[dict[str, Any]],
    metadata_cache: dict[str, dict[str, Any]],
) -> int:
    """Reuse verified collection or external parent covers and annotate gaps."""
    collection_games: set[str] = set()
    verified_parent_covers: dict[str, str] = {}
    for item in items:
        if item.get("item_type") == "dlc":
            continue
        name, link = item.get("name"), item.get("link")
        if not isinstance(name, str) or not name.strip():
            continue
        normalized_name = normalize_game_title(name)
        collection_games.add(normalized_name)
        if not isinstance(link, str):
            continue
        cached = metadata_cache.get(link)
        if (
            isinstance(cached, dict)
            and cached.get("artwork_verified") is True
            and isinstance(cached.get("image"), str)
            and cached["image"].strip()
        ):
            verified_parent_covers.setdefault(normalized_name, cached["image"])

    inherited = 0
    for item in items:
        item.pop("artwork_missing_reason", None)
        if isinstance(item.get("image"), str) and item["image"].strip():
            if item.get("artwork_inherited") is True:
                continue
            if item.get("item_type") != "dlc":
                continue

        if item.get("item_type") != "dlc":
            if not isinstance(item.get("image"), str) or not item["image"].strip():
                item["artwork_missing_reason"] = "standalone_cover_unavailable"
            continue

        parent_game, link = item.get("parent_game"), item.get("link")
        child_cache = metadata_cache.get(link) if isinstance(link, str) else None
        if (
            isinstance(child_cache, dict)
            and child_cache.get("artwork_verified") is True
            and isinstance(child_cache.get("image"), str)
            and child_cache["image"].strip()
        ):
            item["image"] = child_cache["image"]
            item.pop("artwork_inherited", None)
            continue

        if not isinstance(parent_game, str) or not parent_game.strip():
            item["artwork_missing_reason"] = "parent_relationship_missing"
            continue

        normalized_parent = normalize_game_title(parent_game)
        parent_cover = verified_parent_covers.get(normalized_parent)
        if not parent_cover:
            platform = item.get("platform")
            if isinstance(platform, str) and platform.strip():
                external_cache = metadata_cache.get(
                    parent_artwork_cache_key(parent_game, platform)
                )
                if (
                    isinstance(external_cache, dict)
                    and external_cache.get("artwork_verified") is True
                    and isinstance(external_cache.get("image"), str)
                    and external_cache["image"].strip()
                ):
                    parent_cover = external_cache["image"]
        if parent_cover:
            item["image"] = parent_cover
            item["artwork_inherited"] = True
            item.pop("artwork_missing_reason", None)
            inherited += 1
        elif normalized_parent not in collection_games:
            external_cache = (
                metadata_cache.get(parent_artwork_cache_key(parent_game, str(item.get("platform") or "")))
                if isinstance(item.get("platform"), str)
                else None
            )
            if isinstance(external_cache, dict) and external_cache.get("checked_at"):
                item["artwork_missing_reason"] = "external_parent_cover_unavailable"
            else:
                item["artwork_missing_reason"] = "parent_not_in_collection"
        else:
            item["artwork_missing_reason"] = "parent_cover_not_verified"
    return inherited

def summarize_artwork_coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize cover availability without exposing an unbounded missing-title list."""
    missing_items = [
        item for item in items
        if not isinstance(item.get("image"), str) or not item["image"].strip()
    ]
    missing = [str(item.get("name") or "Unknown title") for item in missing_items]
    by_reason: dict[str, list[str]] = {}
    for item in missing_items:
        reason = item.get("artwork_missing_reason", "not_classified")
        if not isinstance(reason, str):
            reason = "not_classified"
        by_reason.setdefault(reason, []).append(str(item.get("name") or "Unknown title"))
    total = len(items)
    with_artwork = total - len(missing)
    return {
        "total_items": total,
        "items_with_artwork": with_artwork,
        "items_missing_artwork": len(missing),
        "coverage_percent": round(with_artwork * 100 / total) if total else 0,
        "missing_artwork_sample": missing[:25],
        "missing_artwork_sample_truncated": len(missing) > 25,
        "artwork_missing_by_reason": {
            reason: len(names) for reason, names in sorted(by_reason.items())
        },
        "artwork_missing_samples_by_reason": {
            reason: names[:10] for reason, names in sorted(by_reason.items())
        },
    }
