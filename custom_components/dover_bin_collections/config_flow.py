from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BASE_URL,
    CONF_PROPERTY_ID,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_BASE_URL,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)
from .parser import (
    DoverCollectionsConnectionError,
    DoverCollectionsParseError,
    build_url,
    fetch_page,
    parse_services,
)


def _user_schema(
    *,
    property_id_default: str = "",
    base_url_default: str = DEFAULT_BASE_URL,
    scan_interval_default: int = DEFAULT_SCAN_INTERVAL_HOURS,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PROPERTY_ID, default=property_id_default): str,
            vol.Optional(CONF_BASE_URL, default=base_url_default): str,
            vol.Optional(CONF_SCAN_INTERVAL_HOURS, default=scan_interval_default): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=24)
            ),
        }
    )


class DoverBinCollectionsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "DoverBinCollectionsOptionsFlow":
        return DoverBinCollectionsOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            property_id = str(user_input[CONF_PROPERTY_ID]).strip()
            base_url = str(user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)).strip() or DEFAULT_BASE_URL
            scan_interval_hours = int(user_input[CONF_SCAN_INTERVAL_HOURS])

            if not property_id or not property_id.isdigit():
                errors["base"] = "invalid_property_id"
            else:
                await self.async_set_unique_id(property_id)
                self._abort_if_unique_id_configured()

                try:
                    url = build_url(property_id, base_url)
                    html_text = await self.hass.async_add_executor_job(fetch_page, url)
                    await self.hass.async_add_executor_job(parse_services, html_text)
                except DoverCollectionsConnectionError:
                    errors["base"] = "cannot_connect"
                except DoverCollectionsParseError:
                    errors["base"] = "no_services"
                except Exception:
                    errors["base"] = "unknown"

            if not errors:
                return self.async_create_entry(
                    title=f"{DEFAULT_NAME} {property_id}",
                    data={
                        CONF_PROPERTY_ID: property_id,
                        CONF_BASE_URL: base_url,
                        CONF_SCAN_INTERVAL_HOURS: scan_interval_hours,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )


class DoverBinCollectionsOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_SCAN_INTERVAL_HOURS: int(user_input[CONF_SCAN_INTERVAL_HOURS]),
                },
            )

        current_value = self._config_entry.options.get(
            CONF_SCAN_INTERVAL_HOURS,
            self._config_entry.data.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL_HOURS, default=current_value): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=24)
                    )
                }
            ),
        )
