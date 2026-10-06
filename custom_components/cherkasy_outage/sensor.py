"""Sensors: queues, next outage start/end, today's and tomorrow's ГПВ windows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import OutageConfigEntry, OutageRuntime
from .entity import OutageEntity
from .helpers import kyiv_tz
from .models import Outage

NO_OUTAGES = "none"


def _fmt(outage: Outage) -> str:
    tz = kyiv_tz()
    start = outage.start.astimezone(tz)
    end = outage.end.astimezone(tz)
    midnight = end.date() > start.date() and end.hour == 0 and end.minute == 0
    return f"{start:%H:%M}–{'24:00' if midnight else f'{end:%H:%M}'}"


def _day_state(runtime: OutageRuntime, day: date) -> str | None:
    windows = runtime.windows_for(day)
    if windows is None:
        return None
    return ", ".join(_fmt(o) for o in windows) or NO_OUTAGES


def _day_attrs(runtime: OutageRuntime, day: date) -> dict[str, Any]:
    post = runtime.schedule_posts.get(day)
    windows = runtime.windows_for(day) or []
    attrs: dict[str, Any] = {
        "date": day.isoformat(),
        "queue": runtime.queue,
        "windows": [{"start": o.start.isoformat(), "end": o.end.isoformat()} for o in windows],
        "hours": round(sum((o.end - o.start).total_seconds() for o in windows) / 3600, 2),
    }
    if post is not None:
        attrs |= {
            "title": post.title,
            "published_at": post.published_at.isoformat(),
            "is_update": post.is_update,
            "cancelled": post.cancelled,
        }
    return attrs


def _today() -> date:
    return dt_util.now(kyiv_tz()).date()


def _next_start(runtime: OutageRuntime) -> datetime | None:
    outage = runtime.next_outage()
    return outage.start if outage else None


def _next_end(runtime: OutageRuntime) -> datetime | None:
    outage = runtime.current_outage() or runtime.next_outage()
    return outage.end if outage else None


def _next_attrs(runtime: OutageRuntime) -> dict[str, Any]:
    outage = runtime.next_outage()
    return outage.as_dict() if outage else {}


def _end_attrs(runtime: OutageRuntime) -> dict[str, Any]:
    outage = runtime.current_outage() or runtime.next_outage()
    return outage.as_dict() if outage else {}


def _latest_post_time(runtime: OutageRuntime) -> datetime | None:
    posts = runtime.schedule_posts.values()
    return max((p.published_at for p in posts), default=None)


def _queue_attrs(runtime: OutageRuntime) -> dict[str, Any]:
    data = runtime.account.data
    return {
        "source": runtime.queue_source,
        "api_queue": data.queue.gpv if data else None,
        "queue_info": list(data.queue.raw) if data else [],
    }


@dataclass(frozen=True, kw_only=True)
class OutageSensorDescription(SensorEntityDescription):
    value_fn: Callable[[OutageRuntime], Any]
    attrs_fn: Callable[[OutageRuntime], dict[str, Any]] | None = None
    source: str = "any"  # which coordinator decides availability: schedule/account/any


SENSORS: tuple[OutageSensorDescription, ...] = (
    OutageSensorDescription(
        key="next_start",
        translation_key="next_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_start,
        attrs_fn=_next_attrs,
    ),
    OutageSensorDescription(
        key="next_end",
        translation_key="next_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_end,
        attrs_fn=_end_attrs,
    ),
    OutageSensorDescription(
        key="today",
        translation_key="today",
        value_fn=lambda r: _day_state(r, _today()),
        attrs_fn=lambda r: _day_attrs(r, _today()),
        source="schedule",
    ),
    OutageSensorDescription(
        key="tomorrow",
        translation_key="tomorrow",
        value_fn=lambda r: _day_state(r, _today() + timedelta(days=1)),
        attrs_fn=lambda r: _day_attrs(r, _today() + timedelta(days=1)),
        source="schedule",
    ),
    OutageSensorDescription(
        key="queue",
        translation_key="queue",
        value_fn=lambda r: r.queue,
        attrs_fn=_queue_attrs,
    ),
    OutageSensorDescription(
        key="emergency_queue",
        translation_key="emergency_queue",
        value_fn=lambda r: r.account.data.queue.gav if r.account.data else None,
        source="account",
    ),
    OutageSensorDescription(
        key="schedule_published",
        translation_key="schedule_published",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_latest_post_time,
        source="schedule",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OutageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(OutageSensor(entry.runtime_data, d) for d in SENSORS)


class OutageSensor(OutageEntity, SensorEntity):
    entity_description: OutageSensorDescription

    def __init__(self, runtime: OutageRuntime, description: OutageSensorDescription) -> None:
        super().__init__(runtime, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        source = self.entity_description.source
        if source == "schedule":
            return self.runtime.schedule.last_update_success
        if source == "account":
            return self.runtime.account.last_update_success
        return super().available

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.runtime)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.runtime)
