"""Config flow for DekuDeals."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import CONF_COLLECTION_JSON, CONF_COLLECTION_URL, DOMAIN
from .importer import CollectionImportError, parse_collection_export


class DekuDealsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DekuDeals."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Import a collection export."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                items = parse_collection_export(user_input[CONF_COLLECTION_JSON])
            except CollectionImportError:
                errors["base"] = "invalid_export"
            else:
                await self.async_set_unique_id(user_input[CONF_COLLECTION_URL].strip())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="DekuDeals",
                    data={
                        CONF_COLLECTION_URL: user_input[CONF_COLLECTION_URL].strip(),
                        CONF_COLLECTION_JSON: user_input[CONF_COLLECTION_JSON],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_COLLECTION_URL): str,
                vol.Required(CONF_COLLECTION_JSON): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={},
        )
