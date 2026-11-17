"""Secure same-origin proxy for TheGamesDB front-cover artwork."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from urllib.parse import quote, urljoin, urlparse

import aiohttp
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_ALLOWED_HOST = "cdn.thegamesdb.net"
_ALLOWED_PATH = re.compile(r"/images/original/boxart/front/[A-Za-z0-9._-]+$")
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


def is_allowed_artwork_url(value: str) -> bool:
    """Accept only HTTPS TheGamesDB original front-cover files."""
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname == _ALLOWED_HOST
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and bool(_ALLOWED_PATH.fullmatch(parsed.path))
        )
    except ValueError:
        return False


def _safe_redirect_target(current_url: str, location: str | None) -> str | None:
    """Resolve a CDN redirect without allowing the proxy to reach another host."""
    if not location:
        return None
    target = urljoin(current_url, location)
    return target if is_allowed_artwork_url(target) else None


def _signature(secret: str, image_url: str) -> str:
    """Sign one exact image URL with the config-entry secret."""
    return hmac.new(
        secret.encode("utf-8"), image_url.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def build_artwork_proxy_url(entry_id: str, secret: str, image_url: str) -> str:
    """Return a signed same-origin URL, or the original URL if not eligible."""
    if not is_allowed_artwork_url(image_url):
        return image_url
    return (
        f"/api/dekudeals/artwork/{quote(entry_id, safe='')}"
        f"?url={quote(image_url, safe='')}&sig={_signature(secret, image_url)}"
    )


class TheGamesDBArtworkView(HomeAssistantView):
    """Serve signed TheGamesDB front covers from the Home Assistant origin."""

    url = "/api/dekudeals/artwork/{entry_id}"
    name = "api:dekudeals:artwork"
    requires_auth = False

    async def get(self, request, entry_id: str):
        """Validate the signed URL and return a bounded image response."""
        # HomeAssistantView instances do not expose a hass attribute.
        # Resolve Home Assistant from the request application instead.
        hass = request.app["hass"]
        entry = (
            hass.data.get(DOMAIN, {})
            .get("entries", {})
            .get(entry_id)
        )
        if not isinstance(entry, dict):
            raise web.HTTPNotFound()
        secret = entry.get("artwork_proxy_secret")
        image_url = request.query.get("url", "")
        supplied_signature = request.query.get("sig", "")
        if (
            not isinstance(secret, str)
            or not is_allowed_artwork_url(image_url)
            or not hmac.compare_digest(
                supplied_signature, _signature(secret, image_url)
            )
        ):
            raise web.HTTPNotFound()

        session = async_get_clientsession(hass)
        current_url = image_url
        try:
            # Follow a small number of CDN redirects manually. Every destination
            # must remain an approved TheGamesDB front-cover URL. Ask upstream
            # intermediaries not to substitute a reduced or transformed image.
            for redirect_count in range(4):
                async with session.get(
                    current_url,
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=False,
                    headers={
                        "Accept": "image/jpeg,image/png,image/webp,*/*;q=0.8",
                        "Cache-Control": "no-transform",
                    },
                ) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        target = _safe_redirect_target(
                            current_url, response.headers.get("Location")
                        )
                        if target is None or redirect_count == 3:
                            raise web.HTTPBadGateway()
                        current_url = target
                        continue
                    if response.status != 200:
                        raise web.HTTPBadGateway()
                    content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
                    if content_type not in _ALLOWED_CONTENT_TYPES:
                        raise web.HTTPBadGateway()
                    if response.content_length is not None and response.content_length > _MAX_IMAGE_BYTES:
                        raise web.HTTPBadGateway()
                    body = await response.content.read(_MAX_IMAGE_BYTES + 1)
                    if not body or len(body) > _MAX_IMAGE_BYTES:
                        raise web.HTTPBadGateway()
                    break
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("TheGamesDB artwork proxy request failed: %s", err)
            raise web.HTTPBadGateway() from err

        # no-transform also asks reverse proxies and caches between Home
        # Assistant and the browser to preserve the original image bytes.
        return web.Response(
            body=body,
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=86400, no-transform"},
        )
