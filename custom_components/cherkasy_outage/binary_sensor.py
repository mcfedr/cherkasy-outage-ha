"""Binary sensor — is there currently a scheduled outage?"""
from __future__ import annotations

import logging
from datetime import datetime, date

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CherkasyOutageCoordinator
from .const import DOMAIN, ENTITY_OUTAGE_ACTIVE
from .parser import is_currently_in_outage

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CherkasyOutageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OutageActiveSensor(coordinator, entry)])


class OutageActiveSensor(CoordinatorEntity, BinarySensorEntity):
    """True while the current time falls within a scheduled outage window."""

    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_has_entity_name = True
    _attr_name = "Outage active"
    _attr_icon = "mdi:transmission-tower-off"

    def __init__(
        self,
        coordinator: CherkasyOutageCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{ENTITY_OUTAGE_ACTIVE}"

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        if not data:
            return False
        now = datetime.now()
        today = now.date()
        current_time = now.time()

        today_data = data.get("today")
        if today_data and today_data["date"] == today.isoformat():
            return is_currently_in_outage(today_data["windows"], current_time)
        return False

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"Cherkasy Outage — {self.coordinator.group}",
            "manufacturer": "Cherkasy Oblenergo",
            "model": "Schedule Monitor",
        }
