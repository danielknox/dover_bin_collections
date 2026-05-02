from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_BASE_URL,
    CONF_PROPERTY_ID,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import DoverBinCollectionsCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = DoverBinCollectionsCoordinator(
        hass,
        entry_id=entry.entry_id,
        property_id=entry.data[CONF_PROPERTY_ID],
        base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        scan_interval_hours=entry.options.get(
            CONF_SCAN_INTERVAL_HOURS,
            entry.data.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS),
        ),
    )
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        raise ConfigEntryNotReady(coordinator.last_exception or "Initial refresh failed")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
