"""Data coordinators and the per-entry runtime that combines them."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import OblenergoClient, OblenergoError, published_at_of
from .const import (
    ACCOUNT_LOOKAHEAD_DAYS,
    CONF_ACCOUNT,
    CONF_QUEUE,
    CONF_QUEUE_OVERRIDE,
    DOMAIN,
    EVENT_SCHEDULE_CHANGED,
    MAX_CONSECUTIVE_FAILURES,
    QUEUE_AUTO,
    SCHEDULE_POST_MAX_AGE,
)
from .helpers import kyiv_tz
from .models import AccountData, Outage, ScheduleData, SchedulePost
from .parser import (
    is_schedule_title,
    latest_per_date,
    merge_outages,
    parse_published_at,
    parse_schedule_post,
    schedule_outages,
)

_LOGGER = logging.getLogger(__name__)

type OutageConfigEntry = ConfigEntry[OutageRuntime]


class _TolerantCoordinator[DataT](DataUpdateCoordinator[DataT]):
    """Keeps serving the last good data through a few failed polls."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: OutageConfigEntry,
        client: OblenergoClient,
        name: str,
        interval: timedelta,
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=name, update_interval=interval)
        self.client = client
        self._failures = 0

    async def _fetch(self) -> DataT:
        raise NotImplementedError

    async def _async_update_data(self) -> DataT:
        try:
            data = await self._fetch()
        except OblenergoError as err:
            self._failures += 1
            if self.data is not None and self._failures < MAX_CONSECUTIVE_FAILURES:
                _LOGGER.warning(
                    "%s update failed (%s/%s), keeping previous data: %s",
                    self.name,
                    self._failures,
                    MAX_CONSECUTIVE_FAILURES,
                    err,
                )
                return self.data
            raise UpdateFailed(str(err)) from err
        self._failures = 0
        return data


class ScheduleCoordinator(_TolerantCoordinator[ScheduleData]):
    """Hourly ГПВ schedules by queue, from the oblenergo's news posts."""

    async def _fetch(self) -> ScheduleData:
        tz = kyiv_tz()
        now = dt_util.now(tz)
        candidates: list[tuple[dict[str, Any], datetime]] = []
        for meta in await self.client.latest_posts():
            published = parse_published_at(published_at_of(meta), tz)
            if (
                published is not None
                and is_schedule_title(str(meta.get("title", "")))
                and now - published <= SCHEDULE_POST_MAX_AGE
            ):
                candidates.append((meta, published))

        details = await asyncio.gather(
            *(self.client.post(str(meta["slug"])) for meta, _ in candidates)
        )
        parsed: list[SchedulePost] = []
        unparsed: list[str] = []
        for (meta, published), post in zip(candidates, details, strict=True):
            title = str(post.get("title") or meta.get("title") or "")
            result = parse_schedule_post(
                slug=str(meta["slug"]),
                title=title,
                content=str(post.get("content") or ""),
                published_at=published,
            )
            if result is None or (not result.queues and not result.cancelled):
                unparsed.append(title)
                continue
            parsed.append(result)

        # Keep schedules we already know about in case their post has dropped out of
        # the newest-posts page; forget anything older than yesterday.
        keep_from = now.date() - timedelta(days=1)
        previous = self.data.posts.values() if self.data else ()
        posts = {
            day: post
            for day, post in latest_per_date([*previous, *parsed]).items()
            if day >= keep_from
        }
        return ScheduleData(posts=posts, unparsed=unparsed)


class AccountCoordinator(_TolerantCoordinator[AccountData]):
    """Queue assignment plus planned / emergency works for the account."""

    async def _fetch(self) -> AccountData:
        tz = kyiv_tz()
        today = dt_util.now(tz).date()
        account = self.config_entry.data[CONF_ACCOUNT]
        (queue, as_of), works = await asyncio.gather(
            self.client.queue_info(account, today),
            self.client.works(
                account,
                today - timedelta(days=1),
                today + timedelta(days=ACCOUNT_LOOKAHEAD_DAYS),
                tz,
            ),
        )
        return AccountData(queue=queue, outages=merge_outages(works), data_as_of=as_of)


class OutageRuntime:
    """Per config entry: owns the coordinators and derives what entities show."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: OutageConfigEntry,
        schedule: ScheduleCoordinator,
        account: AccountCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.schedule = schedule
        self.account = account
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._snapshot: tuple[str | None, dict[date, tuple]] | None = None

    # -- lifecycle -------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        """Start listening; called once both coordinators have data."""
        self.entry.async_on_unload(self.schedule.async_add_listener(self._on_update))
        self.entry.async_on_unload(self.account.async_add_listener(self._on_update))
        self.entry.async_on_unload(self._cancel_timer)
        self._on_update()

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Register an entity callback; returns the remover."""
        self._listeners.append(update_callback)

        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    @callback
    def _on_update(self) -> None:
        self._check_schedule_changes()
        self._update_repair_issue()
        self._schedule_next_boundary()
        for update_callback in list(self._listeners):
            update_callback()

    @callback
    def _cancel_timer(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _schedule_next_boundary(self) -> None:
        """Wake up exactly when an outage starts or ends so states flip on time."""
        self._cancel_timer()
        now = dt_util.utcnow()
        upcoming = [
            moment
            for outage in self.outages
            for moment in (outage.start, outage.end)
            if moment > now
        ]
        if not upcoming:
            return

        @callback
        def _fire(_: datetime) -> None:
            self._unsub_timer = None
            self._on_update()

        self._unsub_timer = async_track_point_in_utc_time(self.hass, _fire, min(upcoming))

    # -- derived data -------------------------------------------------------------

    @property
    def queue(self) -> str | None:
        """The ГПВ sub-queue in effect: option override, then API, then setup value."""
        override = self.entry.options.get(CONF_QUEUE_OVERRIDE, QUEUE_AUTO)
        if override and override != QUEUE_AUTO:
            return str(override)
        if self.account.data and self.account.data.queue.gpv:
            return self.account.data.queue.gpv
        return self.entry.data.get(CONF_QUEUE)

    @property
    def queue_source(self) -> str:
        override = self.entry.options.get(CONF_QUEUE_OVERRIDE, QUEUE_AUTO)
        if override and override != QUEUE_AUTO:
            return "override"
        if self.account.data and self.account.data.queue.gpv:
            return "api"
        return "setup"

    @property
    def schedule_posts(self) -> dict[date, SchedulePost]:
        return self.schedule.data.posts if self.schedule.data else {}

    @property
    def gpv_outages(self) -> list[Outage]:
        if not self.queue:
            return []
        return schedule_outages(self.schedule_posts, self.queue, kyiv_tz())

    @property
    def work_outages(self) -> list[Outage]:
        return self.account.data.outages if self.account.data else []

    @property
    def outages(self) -> list[Outage]:
        """Every known outage window, sorted by start."""
        return sorted([*self.gpv_outages, *self.work_outages], key=lambda o: (o.start, o.end))

    def current_outage(self, now: datetime | None = None) -> Outage | None:
        now = now or dt_util.utcnow()
        active = [o for o in self.outages if o.contains(now)]
        return max(active, key=lambda o: o.end) if active else None

    def next_outage(self, now: datetime | None = None) -> Outage | None:
        now = now or dt_util.utcnow()
        return next((o for o in self.outages if o.start > now), None)

    def windows_for(self, day: date) -> list[Outage] | None:
        """ГПВ windows for the queue on *day*; None when no schedule is published."""
        if day not in self.schedule_posts:
            return None
        tz = kyiv_tz()
        return [o for o in self.gpv_outages if o.start.astimezone(tz).date() == day]

    # -- side effects -------------------------------------------------------------

    @callback
    def _check_schedule_changes(self) -> None:
        """Fire EVENT_SCHEDULE_CHANGED when the queue's windows for a date change."""
        queue = self.queue
        tz = kyiv_tz()
        current = {
            day: tuple(
                (o.start.isoformat(), o.end.isoformat())
                for o in self.gpv_outages
                if o.start.astimezone(tz).date() == day
            )
            for day in self.schedule_posts
        }
        previous = self._snapshot
        self._snapshot = (queue, current)
        if previous is None or previous[0] != queue:
            return  # first data after start-up, or queue changed: nothing to compare
        for day, windows in sorted(current.items()):
            if previous[1].get(day) == windows:
                continue
            post = self.schedule_posts[day]
            self.hass.bus.async_fire(
                EVENT_SCHEDULE_CHANGED,
                {
                    "entry_id": self.entry.entry_id,
                    "queue": queue,
                    "date": day.isoformat(),
                    "windows": [{"start": s, "end": e} for s, e in windows],
                    "cancelled": post.cancelled,
                    "is_update": post.is_update,
                    "title": post.title,
                    "published_at": post.published_at.isoformat(),
                    "first_publication": day not in previous[1],
                },
            )

    @callback
    def _update_repair_issue(self) -> None:
        issue_id = f"unparsed_schedule_{self.entry.entry_id}"
        unparsed = self.schedule.data.unparsed if self.schedule.data else []
        if unparsed:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="unparsed_schedule",
                translation_placeholders={"titles": "; ".join(unparsed)},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
