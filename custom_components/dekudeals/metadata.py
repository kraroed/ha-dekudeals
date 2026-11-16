"""Extract cover art, item type, and store description from DekuDeals pages."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


class _MetadataParser(HTMLParser):
    """Read image metadata, JSON-LD, and visible page text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str] = {}
        self._json_ld = False
        self._json_parts: list[str] = []
        self.json_ld: dict[str, str] = {}
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value for key, value in attrs if value}
        if tag.casefold() == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            content = values.get("content")
            if key and content:
                self.values.setdefault(key, content.strip())
        elif tag.casefold() == "script" and values.get("type", "").casefold() == "application/ld+json":
            self._json_ld = True
            self._json_parts = []

    def handle_data(self, data: str) -> None:
        if self._json_ld:
            self._json_parts.append(data)
        else:
            self.text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._json_ld:
            self._json_ld = False
            try:
                payload = json.loads("".join(self._json_parts))
            except (TypeError, json.JSONDecodeError):
                return
            records = payload if isinstance(payload, list) else [payload]
            for record in records:
                if not isinstance(record, dict):
                    continue
                image = record.get("image")
                if isinstance(image, str):
                    self.json_ld.setdefault("image", image)
                elif isinstance(image, dict) and isinstance(image.get("url"), str):
                    self.json_ld.setdefault("image", image["url"])
                elif isinstance(image, list) and image:
                    first = image[0]
                    if isinstance(first, str):
                        self.json_ld.setdefault("image", first)
                    elif isinstance(first, dict) and isinstance(first.get("url"), str):
                        self.json_ld.setdefault("image", first["url"])


def is_dekudeals_item_url(value: str | None) -> bool:
    """Only request item pages on the expected public DekuDeals host."""
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"dekudeals.com", "www.dekudeals.com"}
            and parsed.port in (None, 443)
            and parsed.path.startswith("/items/")
            and bool(parsed.path.removeprefix("/items/").strip("/"))
        )
    except ValueError:
        return False


def extract_game_metadata(html: str, page_url: str) -> dict[str, str | None]:
    """Extract cover art, DLC classification, and the actual Description section.

    Social metadata is intentionally not used for descriptions: DekuDeals uses
    those fields for promotional/sale copy. The visible Description section is
    the product description supplied on the item page.
    """
    parser = _MetadataParser()
    parser.feed(html)
    page_text = " ".join(" ".join(parser.text_parts).split())

    image = (
        parser.values.get("og:image")
        or parser.values.get("twitter:image")
        or parser.values.get("twitter:image:src")
        or parser.json_ld.get("image")
    )
    if image:
        image = urljoin(page_url, image.strip())
        if urlparse(image).scheme != "https":
            image = None

    description = None
    match = re.search(r"\bDescription\s*(.*?)\s*Screenshots\b", page_text, re.IGNORECASE)
    if match:
        description = " ".join(match.group(1).split())[:2000] or None

    dlc_match = re.search(
        r"\\bDLC\\s+for\\s+(.+?)(?=\\s+(?:Details|Current prices|Description)\\b|\\s+\\d+(?:\\.\\d+)?\\s*⭐|$)",
        page_text,
        re.IGNORECASE,
    )
    page_title = parser.values.get("og:title") or parser.values.get("twitter:title") or ""
    # DekuDeals does not consistently expose the "DLC for [game]" label in
    # the same part of the page. Also inspect the title and the actual
    # Description section for explicit DLC / add-on / expansion wording.
    dlc_markers = re.compile(
        r"\\b(?:DLC|downloadable content|season pass|expansion pack|add[- ]on)\\b",
        re.IGNORECASE,
    )
    is_dlc = bool(
        dlc_match
        or dlc_markers.search(page_title)
        or (description and dlc_markers.search(description))
    )
    item_type = "dlc" if is_dlc else "game"
    parent_game = " ".join(dlc_match.group(1).split())[:300] if dlc_match else None

    return {
        "image": image,
        "description": description,
        "item_type": item_type,
        "parent_game": parent_game,
    }
