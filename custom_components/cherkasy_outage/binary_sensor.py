"""Binary sensor that is on while a scheduled outage window is in progress."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OutageConfigEntry
from .entity import OutageEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OutageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ScheduledNowSensor(entry.runtime_data, "scheduled_now")])


class ScheduledNowSensor(OutageEntity, BinarySensorEntity):
    """On while now is inside any known outage window (schedule, not grid state)."""

    @property
    def is_on(self) -> bool:
        return self.runtime.current_outage() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        outage = self.runtime.current_outage()
        if outage is None:
            return {}
        return {"kind": outage.kind, "summary": outage.summary, "ends_at": outage.end.isoformat()}
