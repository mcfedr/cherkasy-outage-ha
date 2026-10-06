"""Cherkasyoblenergo power outage schedule integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import ACCOUNT_SCAN_INTERVAL, SCHEDULE_SCAN_INTERVAL
from .coordinator import (
    AccountCoordinator,
    OutageConfigEntry,
    OutageRuntime,
    ScheduleCoordinator,
)
from .helpers import async_get_client

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: OutageConfigEntry) -> bool:
    """Set up an account from a config entry."""
    client = await async_get_client(hass)
    schedule = ScheduleCoordinator(hass, entry, client, "schedule", SCHEDULE_SCAN_INTERVAL)
    account = AccountCoordinator(hass, entry, client, "account", ACCOUNT_SCAN_INTERVAL)
    await schedule.async_config_entry_first_refresh()
    await account.async_config_entry_first_refresh()

    runtime = OutageRuntime(hass, entry, schedule, account)
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    runtime.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OutageConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
