"""Sensor entities for Cherkasy Outage."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CherkasyOutageCoordinator
from .const import (
    DOMAIN,
    ENTITY_LAST_UPDATED,
    ENTITY_NEXT_OUTAGE_END,
    ENTITY_NEXT_OUTAGE_START,
    ENTITY_SCHEDULE_TODAY,
    ENTITY_SCHEDULE_TOMORROW,
)
from .parser import get_next_outage

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CherkasyOutageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            OutageScheduleSensor(coordinator, entry, "today"),
            OutageScheduleSensor(coordinator, entry, "tomorrow"),
            NextOutageSensor(coordinator, entry, "start"),
            NextOutageSensor(coordinator, entry, "end"),
            LastUpdatedSensor(coordinator, entry),
        ]
    )


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class _OutageBase(CoordinatorEntity):
    """Common base for all Cherkasy Outage entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CherkasyOutageCoordinator,
        entry: ConfigEntry,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"Cherkasy Outage — {self.coordinator.group}",
            "manufacturer": "Cherkasy Oblenergo",
            "model": "Schedule Monitor",
        }


# ---------------------------------------------------------------------------
# Schedule sensors (today / tomorrow)
# ---------------------------------------------------------------------------

class OutageScheduleSensor(_OutageBase, SensorEntity):
    """Shows total outage hours for today or tomorrow."""

    def __init__(
        self,
        coordinator: CherkasyOutageCoordinator,
        entry: ConfigEntry,
        day: str,  # "today" or "tomorrow"
    ) -> None:
        unique_suffix = ENTITY_SCHEDULE_TODAY if day == "today" else ENTITY_SCHEDULE_TOMORROW
        super().__init__(coordinator, entry, unique_suffix)
        self._day = day
        self._attr_name = f"Outage schedule {day}"
        self._attr_icon = "mdi:lightning-bolt-off"

    @property
    def _day_data(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._day)

    @property
    def native_value(self) -> str:
        data = self._day_data
        if data is None:
            return "none"
        return f"{data['total_hours']}h"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._day_data
        if data is None:
            return {}
        return {
            "date": data["date"],
            "windows": data["windows"],
            "windows_formatted": data["windows_formatted"],
            "window_count": len(data["windows"]),
            "group": self.coordinator.group,
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


# ---------------------------------------------------------------------------
# Next outage start / end sensors
# ---------------------------------------------------------------------------

class NextOutageSensor(_OutageBase, SensorEntity):
    """Datetime of the next outage window start or end."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-alert-outline"

    def __init__(
        self,
        coordinator: CherkasyOutageCoordinator,
        entry: ConfigEntry,
        bound: str,  # "start" or "end"
    ) -> None:
        unique_suffix = ENTITY_NEXT_OUTAGE_START if bound == "start" else ENTITY_NEXT_OUTAGE_END
        super().__init__(coordinator, entry, unique_suffix)
        self._bound = bound
        self._attr_name = f"Next outage {bound}"

    def _find_next_window(self) -> dict[str, str] | None:
        data = self.coordinator.data
        if not data:
            return None

        now = datetime.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)
        current_time = now.time()

        # Try today first
        today_data = data.get("today")
        if today_data and today_data["date"] == today.isoformat():
            w = get_next_outage(today_data["windows"], current_time)
            if w is not None:
                return {"window": w, "date": today}

        # Fall back to tomorrow
        tomorrow_data = data.get("tomorrow")
        if tomorrow_data and tomorrow_data["date"] == tomorrow.isoformat():
            if tomorrow_data["windows"]:
                return {"window": tomorrow_data["windows"][0], "date": tomorrow}

        return None

    @property
    def native_value(self) -> datetime | None:
        result = self._find_next_window()
        if result is None:
            return None
        window = result["window"]
        day: date = result["date"]
        time_str = window[self._bound]
        h, m = map(int, time_str.split(":"))
        # Midnight-end: treat as start of next day
        if h == 0 and m == 0 and self._bound == "end":
            day = day + timedelta(days=1)
        local_tz = datetime.now().astimezone().tzinfo
        return datetime(day.year, day.month, day.day, h, m, tzinfo=local_tz)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


# ---------------------------------------------------------------------------
# Last updated sensor
# ---------------------------------------------------------------------------

class LastUpdatedSensor(_OutageBase, SensorEntity):
    """Timestamp of when the schedule was last successfully fetched."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Schedule last updated"
    _attr_icon = "mdi:update"

    def __init__(
        self,
        coordinator: CherkasyOutageCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, ENTITY_LAST_UPDATED)

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        if not data or not data.get("last_updated"):
            return None
        return datetime.fromisoformat(data["last_updated"])

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
