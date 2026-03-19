"""Cherkasy Outage Schedule — custom HA integration."""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_API_HASH,
    CONF_API_ID,
    CONF_CHANNEL,
    CONF_GROUP,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    SESSION_FILE,
)
from .parser import parse_schedule
from .telegram_reader import TelegramReader

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cherkasy Outage from a config entry."""
    session_path = hass.config.path(SESSION_FILE)

    reader = TelegramReader(
        api_id=int(entry.data[CONF_API_ID]),
        api_hash=entry.data[CONF_API_HASH],
        session_path=session_path,
    )

    try:
        await reader.connect()
    except PermissionError as err:
        raise ConfigEntryNotReady(
            "Telegram session not authorised — please reconfigure the integration"
        ) from err
    except Exception as err:
        raise ConfigEntryNotReady(f"Could not connect to Telegram: {err}") from err

    poll_minutes = entry.options.get(
        CONF_POLL_INTERVAL,
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )

    coordinator = CherkasyOutageCoordinator(
        hass=hass,
        reader=reader,
        channel=entry.data[CONF_CHANNEL],
        group=entry.options.get(CONF_GROUP, entry.data[CONF_GROUP]),
        update_interval=timedelta(minutes=poll_minutes),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: CherkasyOutageCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.reader.disconnect()
    return unload_ok


class CherkasyOutageCoordinator(DataUpdateCoordinator):
    """Fetch schedule data from Telegram on a regular interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        reader: TelegramReader,
        channel: str,
        group: str,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.reader = reader
        self.channel = channel
        self.group = group

    async def _async_update_data(self):
        """Fetch messages and parse schedule. Called by DataUpdateCoordinator."""
        try:
            messages = await self.reader.fetch_recent_messages(self.channel)
        except Exception as err:
            raise UpdateFailed(f"Error fetching Telegram messages: {err}") from err

        try:
            data = parse_schedule(messages, self.group)
        except Exception as err:
            raise UpdateFailed(f"Error parsing schedule: {err}") from err

        return data
