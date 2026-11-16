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
    platform_data = include.get("platform")
    if not isinstance(games, list) or not isinstance(boxart, dict):
        return None
    base_urls = boxart.get("base_url")
    image_map = boxart.get("data")
    if not isinstance(base_urls, dict) or not isinstance(image_map, dict):
        return None
    base_url = base_urls.get("original")
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
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
            resolution = image.get("resolution")
            if not isinstance(resolution, str):
                continue
            match = re.fullmatch(r"(\\d+)x(\\d+)", resolution.strip())
            if not match:
                continue
            width, height = (int(part) for part in match.groups())
            if width <= 0 or height <= 0:
                continue
            ratio = width / height
            if not 0.48 <= ratio <= 0.85:
                continue
            filename = image.get("filename")
            if not isinstance(filename, str) or not filename or filename.startswith(("/", "\\\\")):
                continue
            image_url = urljoin(base_url.rstrip("/") + "/", filename)
            parsed = urlparse(image_url)
            if parsed.scheme == "https" and parsed.hostname == urlparse(base_url).hostname:
                return image_url
    return None
