"""Calendar of outage windows: ГПВ for the queue plus planned / emergency works."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import OutageConfigEntry
from .entity import OutageEntity
from .models import Outage


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OutageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([OutageCalendar(entry.runtime_data, "outages")])


def _event(outage: Outage) -> CalendarEvent:
    description = outage.description
    if outage.status:
        description = f"{outage.status}\n{description}".strip()
    return CalendarEvent(
        start=outage.start,
        end=outage.end,
        summary=outage.summary,
        description=description or None,
        uid=f"{outage.kind}-{outage.start.isoformat()}-{outage.end.isoformat()}",
    )


class OutageCalendar(OutageEntity, CalendarEntity):
    """All known outage windows for the account."""

    _attr_name = None  # the device name ("Power outages") is the entity name

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.utcnow()
        outage = self.runtime.current_outage(now) or self.runtime.next_outage(now)
        return _event(outage) if outage else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            _event(outage)
            for outage in self.runtime.outages
            if outage.end > start_date and outage.start < end_date
        ]
