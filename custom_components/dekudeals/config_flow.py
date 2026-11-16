"""Config flow for DekuDeals."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import CONF_COLLECTION_JSON, CONF_COLLECTION_URL, CONF_PLATFORM, CONF_THEGAMESDB_API_KEY, DOMAIN
from .importer import CollectionImportError, parse_collection_export


class DekuDealsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DekuDeals."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Configure a public collection URL and optional offline fallback."""
        errors: dict[str, str] = {}
        if user_input is not None:
            collection_url = user_input[CONF_COLLECTION_URL].strip().removesuffix(".json").rstrip("/")
            fallback_json = user_input.get(CONF_COLLECTION_JSON, "").strip()
            platform = " ".join(user_input.get(CONF_PLATFORM, "Switch").split())
            try:
                if not collection_url.startswith(
                    ("https://www.dekudeals.com/collection/", "https://dekudeals.com/collection/")
                ):
                    raise CollectionImportError("Enter a valid DekuDeals collection URL.")
                if not platform or len(platform) > 64:
                    raise CollectionImportError("Enter a console name up to 64 characters.")
                if fallback_json:
                    parse_collection_export(fallback_json)
            except CollectionImportError:
                errors["base"] = "invalid_export"
            else:
                # Preserve the legacy Switch unique ID so existing installations
                # upgrade in place; other consoles can use the same collection URL.
                normalized_platform = platform.casefold()
                unique_id = collection_url if normalized_platform == "switch" else f"{collection_url}::{normalized_platform}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                data = {CONF_COLLECTION_URL: collection_url, CONF_PLATFORM: platform}
                if fallback_json:
                    data[CONF_COLLECTION_JSON] = fallback_json
                return self.async_create_entry(title=f"DekuDeals — {platform}", data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLATFORM, default="Switch"): str,
                    vol.Required(
                        CONF_COLLECTION_URL,
                        default="https://www.dekudeals.com/collection/w8h3s6w3t6",
                    ): str,
                    vol.Optional(CONF_COLLECTION_JSON): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow for updating an offline fallback export."""
        return DekuDealsOptionsFlow(config_entry)


class DekuDealsOptionsFlow(config_entries.OptionsFlow):
    """Update or clear the optional saved JSON fallback."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Validate and save a replacement fallback export."""
        errors: dict[str, str] = {}
        if user_input is not None:
            fallback_json = user_input.get(CONF_COLLECTION_JSON, "").strip()
            api_key = user_input.get(CONF_THEGAMESDB_API_KEY, "").strip()
            try:
                if fallback_json:
                    parse_collection_export(fallback_json)
            except CollectionImportError:
                errors["base"] = "invalid_export"
            else:
                options = {CONF_THEGAMESDB_API_KEY: api_key}
                if fallback_json:
                    options[CONF_COLLECTION_JSON] = fallback_json
                return self.async_create_entry(title="", data=options)
        current_json = self.config_entry.options.get(
            CONF_COLLECTION_JSON, self.config_entry.data.get(CONF_COLLECTION_JSON, "")
        )
        current_api_key = self.config_entry.options.get(CONF_THEGAMESDB_API_KEY, "")
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_COLLECTION_JSON, default=current_json): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    ),
                    vol.Optional(CONF_THEGAMESDB_API_KEY, default=current_api_key): str,
                }
            ),
            errors=errors,
        )
