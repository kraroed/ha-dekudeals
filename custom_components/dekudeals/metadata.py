"""Extract lightweight cover-art and description metadata from DekuDeals pages."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


class _MetadataParser(HTMLParser):
    """Read Open Graph, Twitter Card, and standard description metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str] = {}
        self._json_ld = False
        self._json_parts: list[str] = []
        self.json_ld: dict[str, str] = {}

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
                description = record.get("description")
                if isinstance(description, str):
                    self.json_ld.setdefault("description", description)
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
    """Extract a safe image URL and a concise description from page metadata."""
    parser = _MetadataParser()
    parser.feed(html)

    image = (
        parser.values.get("og:image")
        or parser.values.get("twitter:image")
        or parser.values.get("twitter:image:src")
        or parser.json_ld.get("image")
    )
    description = (
        parser.values.get("og:description")
        or parser.values.get("description")
        or parser.values.get("twitter:description")
        or parser.json_ld.get("description")
    )

    if image:
        image = urljoin(page_url, image.strip())
        parsed_image = urlparse(image)
        if parsed_image.scheme != "https":
            image = None

    if description:
        description = " ".join(description.split())[:2000] or None

    return {"image": image, "description": description}
