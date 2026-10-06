"""Entities, timing, events and resilience, inside a real Home Assistant core."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.cherkasy_outage.const import DOMAIN, EVENT_SCHEDULE_CHANGED
from custom_components.cherkasy_outage.diagnostics import async_get_config_entry_diagnostics

from .conftest import ACCOUNT, SLUG_6_UPDATED, SLUG_7, CabinetRouter, NewsRouter, fixture_text

KYIV = ZoneInfo("Europe/Kyiv")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config.async_set_time_zone("Europe/Kyiv")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Poll both coordinators now (HA's own scheduling is not under test)."""
    runtime = entry.runtime_data
    await runtime.schedule.async_refresh()
    await runtime.account.async_refresh()
    await hass.async_block_till_done()


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    # Advance the wall clock *and* fire every loop timer due within that window
    # (the loop's monotonic clock is not frozen, so pass an explicit target).
    freezer.tick(delta)
    async_fire_time_changed(hass, dt_util.utcnow() + delta)
    await hass.async_block_till_done()


@pytest.fixture
def at_10_on_7th(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    freezer.move_to(datetime(2026, 10, 7, 10, 0, tzinfo=KYIV))
    return freezer


async def test_entities_during_an_outage(
    hass: HomeAssistant,
    cabinet_router: CabinetRouter,
    news_router: NewsRouter,
    config_entry: MockConfigEntry,
    at_10_on_7th: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get("binary_sensor.power_outages_scheduled_now").state == STATE_ON
    assert hass.states.get("sensor.power_outages_today").state == "09:00–11:00, 19:00–21:00"
    assert hass.states.get("sensor.power_outages_tomorrow").state == STATE_UNKNOWN
    assert hass.states.get("sensor.power_outages_queue").state == "4.1"
    assert hass.states.get("sensor.power_outages_emergency_queue").state == "3"
    assert dt_util.parse_datetime(
        hass.states.get("sensor.power_outages_next_start").state
    ) == datetime(2026, 10, 7, 19, tzinfo=KYIV)
    assert dt_util.parse_datetime(
        hass.states.get("sensor.power_outages_next_end").state
    ) == datetime(2026, 10, 7, 11, tzinfo=KYIV)
    calendar = hass.states.get("calendar.power_outages")
    assert calendar.state == STATE_ON
    assert calendar.attributes["message"] == "ГПВ 4.1"

    # Flips off exactly at 11:00 without waiting for a poll.
    await _tick(hass, at_10_on_7th, timedelta(hours=1))
    assert hass.states.get("binary_sensor.power_outages_scheduled_now").state == STATE_OFF
    assert dt_util.parse_datetime(
        hass.states.get("sensor.power_outages_next_end").state
    ) == datetime(2026, 10, 7, 21, tzinfo=KYIV)


async def test_calendar_events(
    hass: HomeAssistant,
    cabinet_router: CabinetRouter,
    news_router: NewsRouter,
    config_entry: MockConfigEntry,
    at_10_on_7th: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, config_entry)
    response = await hass.services.async_call(
        CALENDAR_DOMAIN,
        "get_events",
        {
            "entity_id": "calendar.power_outages",
            "start_date_time": "2026-10-06T00:00:00+03:00",
            "end_date_time": "2026-10-08T00:00:00+03:00",
        },
        blocking=True,
        return_response=True,
    )
    events = [
        (e["start"], e["end"], e["summary"]) for e in response["calendar.power_outages"]["events"]
    ]
    assert events == [
        # 6 Oct comes from the *updated* post (same for 4.1 here), 7 Oct from its post.
        ("2026-10-06T21:00:00+03:00", "2026-10-06T23:00:00+03:00", "ГПВ 4.1"),
        ("2026-10-07T09:00:00+03:00", "2026-10-07T11:00:00+03:00", "ГПВ 4.1"),
        ("2026-10-07T19:00:00+03:00", "2026-10-07T21:00:00+03:00", "ГПВ 4.1"),
    ]


async def test_planned_works_join_the_calendar(
    hass: HomeAssistant,
    cabinet_router: CabinetRouter,
    news_router: NewsRouter,
    config_entry: MockConfigEntry,
    at_10_on_7th: FrozenDateTimeFactory,
) -> None:
    cabinet_router.planned = json.dumps(
        {
            "DATETIME": "09:00 07.10.2026",
            "DISCONNECTIONS": [
                {
                    "DISCONN_TYPE": "Планові",
                    "DATE_START": "09:00 08.10.2026",
                    "DATE_STOP": "16:00 08.10.2026 (план)",
                    "STATE_INT": "0",
                    "STATE_CHAR": "Заплановано",
                    "ADDRESS": "<strong>м. Черкаси</strong><br>вул. Тестова 1",
                }
            ],
        }
    )
    await _setup(hass, config_entry)
    response = await hass.services.async_call(
        CALENDAR_DOMAIN,
        "get_events",
        {
            "entity_id": "calendar.power_outages",
            "start_date_time": "2026-10-08T00:00:00+03:00",
            "end_date_time": "2026-10-09T00:00:00+03:00",
        },
        blocking=True,
        return_response=True,
    )
    (event,) = response["calendar.power_outages"]["events"]
    assert event["summary"] == "Планові"
    assert event["description"].startswith("Заплановано\nм. Черкаси")


async def test_schedule_change_fires_event(
    hass: HomeAssistant,
    cabinet_router: CabinetRouter,
    news_router: NewsRouter,
    config_entry: MockConfigEntry,
    at_10_on_7th: FrozenDateTimeFactory,
) -> None:
    news_router.hide(SLUG_7)  # 7 Oct's schedule isn't published yet
    await _setup(hass, config_entry)
    assert hass.states.get("sensor.power_outages_today").state == STATE_UNKNOWN

    events: list[Event] = []
    hass.bus.async_listen(EVENT_SCHEDULE_CHANGED, events.append)

    news_router.listing = json.loads(fixture_text("news_list.json"))
    await _refresh(hass, config_entry)

    assert len(events) == 1
    data = events[0].data
    assert data["date"] == "2026-10-07"
    assert data["queue"] == "4.1"
    assert data["first_publication"] is True
    assert data["windows"] == [
        {"start": "2026-10-07T09:00:00+03:00", "end": "2026-10-07T11:00:00+03:00"},
        {"start": "2026-10-07T19:00:00+03:00", "end": "2026-10-07T21:00:00+03:00"},
    ]
    assert hass.states.get("sensor.power_outages_today").state == "09:00–11:00, 19:00–21:00"

    # Polling again with nothing new fires nothing.
    await _refresh(hass, config_entry)
    assert len(events) == 1


async def test_rides_out_short_api_failures(
    hass: HomeAssistant,
    cabinet_router: CabinetRouter,
    news_router: NewsRouter,
    config_entry: MockConfigEntry,
    at_10_on_7th: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, config_entry)
    news_router.fail = True
    cabinet_router.fail = True

    await _refresh(hass, config_entry)
    await _refresh(hass, config_entry)
    # Two failed polls each: still serving the last good data.
    assert hass.states.get("sensor.power_outages_today").state == "09:00–11:00, 19:00–21:00"
    assert hass.states.get("sensor.power_outages_queue").state == "4.1"

    await _refresh(hass, config_entry)
    assert hass.states.get("sensor.power_outages_today").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.power_outages_scheduled_now").state == STATE_UNAVAILABLE

    news_router.fail = False
    cabinet_router.fail = False
    await _refresh(hass, config_entry)
    assert hass.states.get("sensor.power_outages_queue").state == "4.1"
    assert hass.states.get("binary_sensor.power_outages_scheduled_now").state != STATE_UNAVAILABLE


async def test_unreadable_schedule_raises_repair(
    hass: HomeAssistant,
    cabinet_router: CabinetRouter,
    news_router: NewsRouter,
    config_entry: MockConfigEntry,
    at_10_on_7th: FrozenDateTimeFactory,
) -> None:
    news_router.posts[SLUG_7]["data"]["content"] = "<p>Графік — у вкладенні.</p>"
    await _setup(hass, config_entry)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"unparsed_schedule_{config_entry.entry_id}")
    assert issue is not None
    assert "7 жовтня" in issue.translation_placeholders["titles"]
    assert hass.states.get("sensor.power_outages_today").state == STATE_UNKNOWN


async def test_setup_retries_when_api_down(
    hass: HomeAssistant,
    cabinet_router: CabinetRouter,
    news_router: NewsRouter,
    config_entry: MockConfigEntry,
) -> None:
    news_router.fail = True
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_and_diagnostics(
    hass: HomeAssistant,
    cabinet_router: CabinetRouter,
    news_router: NewsRouter,
    config_entry: MockConfigEntry,
    at_10_on_7th: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert ACCOUNT not in json.dumps(diag, default=str)
    assert diag["queue"] == "4.1"
    assert "2026-10-07" in diag["schedule"]
    assert diag["schedule"]["2026-10-06"]["slug"] == SLUG_6_UPDATED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
