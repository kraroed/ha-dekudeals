"""Secure same-origin proxy for verified TheGamesDB front-cover artwork."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
MAX_ARTWORK_BYTES = 8 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_allowed_artwork_url(value: str) -> bool:
    """Allow only HTTPS TheGamesDB original front-boxart files."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname == "cdn.thegamesdb.net"
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith("/images/original/boxart/front/")
        and _FILENAME_RE.fullmatch(parsed.path.rsplit("/", 1)[-1])
        and not parsed.query
        and not parsed.fragment
    )


def artwork_proxy_url(hass: HomeAssistant, entry_id: str, image_url: str) -> str:
    """Create a signed same-origin URL for an approved remote cover."""
    entry_data = hass.data.get(DOMAIN, {}).get("entries", {}).get(entry_id)
    if not entry_data or not _is_allowed_artwork_url(image_url):
        return image_url
    secret = entry_data.get("artwork_proxy_secret")
    if not isinstance(secret, bytes):
        return image_url
    encoded = base64.urlsafe_b64encode(image_url.encode()).decode().rstrip("=")
    signature = hmac.new(secret, image_url.encode(), hashlib.sha256).hexdigest()
    return f"/api/dekudeals/artwork/{entry_id}?url={encoded}&sig={signature}"


class DekuDealsArtworkView(HomeAssistantView):
    """Serve only signed TheGamesDB cover URLs through Home Assistant."""

    url = "/api/dekudeals/artwork/{entry_id}"
    name = "api:dekudeals:artwork"
    requires_auth = False

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Validate the per-entry signature and fetch the approved image."""
        entry_data = (
            request.app["hass"].data.get(DOMAIN, {}).get("entries", {}).get(entry_id)
        )
        secret = entry_data.get("artwork_proxy_secret") if entry_data else None
        encoded = request.query.get("url", "")
        supplied_signature = request.query.get("sig", "")
        if not isinstance(secret, bytes) or not encoded or not supplied_signature:
            raise web.HTTPNotFound()
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            image_url = base64.urlsafe_b64decode(padded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPNotFound() from None
        if not _is_allowed_artwork_url(image_url):
            raise web.HTTPNotFound()
        expected = hmac.new(secret, image_url.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied_signature):
            raise web.HTTPNotFound()

        session = async_get_clientsession(request.app["hass"])
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with session.get(
                image_url, timeout=timeout, allow_redirects=False
            ) as response:
                if response.status != 200:
                    raise web.HTTPBadGateway()
                content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
                if content_type not in ALLOWED_CONTENT_TYPES:
                    raise web.HTTPBadGateway()
                body = await response.content.read(MAX_ARTWORK_BYTES + 1)
                if len(body) > MAX_ARTWORK_BYTES:
                    raise web.HTTPBadGateway()
        except web.HTTPException:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Unable to proxy DekuDeals cover artwork: %s", err)
            raise web.HTTPBadGateway() from err

        return web.Response(
            body=body,
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
