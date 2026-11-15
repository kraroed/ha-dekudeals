"""Config flow for DekuDeals."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import CONF_COLLECTION_JSON, CONF_COLLECTION_URL, DOMAIN
from .importer import CollectionImportError, parse_collection_export


class DekuDealsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DekuDeals."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Import a collection export."""
        errors: dict[str, str] = {}
        if user_input is not None:
            collection_url = user_input[CONF_COLLECTION_URL].strip()
            try:
                if not collection_url.startswith(
                    ("https://www.dekudeals.com/collection/", "https://dekudeals.com/collection/")
                ):
                    raise CollectionImportError("Enter a valid DekuDeals collection URL.")
                parse_collection_export(user_input[CONF_COLLECTION_JSON])
            except CollectionImportError:
                errors["invalid_export"] = "invalid_export"
            else:
                await self.async_set_unique_id(collection_url.rstrip("/"))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="DekuDeals",
                    data={
                        CONF_COLLECTION_URL: collection_url,
                        CONF_COLLECTION_JSON: user_input[CONF_COLLECTION_JSON],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COLLECTION_URL): str,
                    vol.Required(CONF_COLLECTION_JSON): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow for updating an imported export."""
        return DekuDealsOptionsFlow(config_entry)


class DekuDealsOptionsFlow(config_entries.OptionsFlow):
    """Update the collection export for an existing config entry."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Validate and save a replacement collection export."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parse_collection_export(user_input[CONF_COLLECTION_JSON])
            except CollectionImportError:
                errors["base"] = "invalid_export"
            else:
                return self.async_create_entry(
                    title="",
                    data={CONF_COLLECTION_JSON: user_input[CONF_COLLECTION_JSON]},
                )

        current_json = self.config_entry.options.get(
            CONF_COLLECTION_JSON, self.config_entry.data[CONF_COLLECTION_JSON]
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_COLLECTION_JSON, default=current_json
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    )
                }
            ),
            errors=errors,
        )
