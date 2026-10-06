"""Config and options flow, inside a real Home Assistant core."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cherkasy_outage.const import (
    CONF_ACCOUNT,
    CONF_ADDRESS,
    CONF_CITY_ID,
    CONF_DEPARTMENT_ID,
    CONF_HOUSE,
    CONF_QUEUE,
    CONF_QUEUE_OVERRIDE,
    CONF_STREET_ID,
    DOMAIN,
)

from .conftest import ACCOUNT, CabinetRouter, NewsRouter, fixture_text


async def _start(hass: HomeAssistant, path: str) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": path})


async def test_flow_by_address(
    hass: HomeAssistant, cabinet_router: CabinetRouter, news_router: NewsRouter
) -> None:
    result = await _start(hass, "department")
    assert result["step_id"] == "department"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEPARTMENT_ID: "1"}
    )
    assert result["step_id"] == "city"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CITY_ID: "1"})
    assert result["step_id"] == "street_search"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"street_search": "Зін"}
    )
    assert result["step_id"] == "street"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET_ID: "115"}
    )
    assert result["step_id"] == "house"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOUSE: "12"})
    assert result["step_id"] == "select_account"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ACCOUNT: ACCOUNT}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "м. Черкаси, вул. Тестова, 1"
    assert result["data"] == {
        CONF_DEPARTMENT_ID: "1",
        CONF_CITY_ID: "1",
        CONF_STREET_ID: "115",
        CONF_HOUSE: "12",
        CONF_ACCOUNT: ACCOUNT,
        CONF_ADDRESS: "м. Черкаси, вул. Тестова, 1",
        CONF_QUEUE: "4.1",
    }
    assert result["result"].unique_id == ACCOUNT
    street_request = next(r for r in cabinet_router.requests if r.get("op") == "street_list")
    assert street_request["search_name"] == "Зін"


async def test_flow_by_account_number(
    hass: HomeAssistant, cabinet_router: CabinetRouter, news_router: NewsRouter
) -> None:
    result = await _start(hass, "account")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ACCOUNT: "abc"}
    )
    assert result["errors"] == {CONF_ACCOUNT: "invalid_account"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ACCOUNT: f" {ACCOUNT} "}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Account {ACCOUNT}"
    assert result["data"] == {CONF_ACCOUNT: ACCOUNT, CONF_QUEUE: "4.1"}


async def test_unknown_account_asks_for_queue(
    hass: HomeAssistant, cabinet_router: CabinetRouter, news_router: NewsRouter
) -> None:
    cabinet_router.queue = fixture_text("cabinet_account_unknown.json")
    result = await _start(hass, "account")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ACCOUNT: "71010099999"}
    )
    assert result["step_id"] == "queue"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_QUEUE: "4"})
    assert result["errors"] == {CONF_QUEUE: "invalid_queue"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_QUEUE: "3.2"})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_QUEUE] == "3.2"


async def test_duplicate_account_aborts(
    hass: HomeAssistant, cabinet_router: CabinetRouter, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await _start(hass, "account")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ACCOUNT: ACCOUNT}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_api_down_aborts(hass: HomeAssistant, cabinet_router: CabinetRouter) -> None:
    cabinet_router.fail = True
    result = await _start(hass, "department")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_options_flow_overrides_queue(
    hass: HomeAssistant,
    cabinet_router: CabinetRouter,
    news_router: NewsRouter,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.power_outages_queue").state == "4.1"

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_QUEUE_OVERRIDE: "bad"}
    )
    assert result["errors"] == {CONF_QUEUE_OVERRIDE: "invalid_queue"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_QUEUE_OVERRIDE: "5.2"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    state = hass.states.get("sensor.power_outages_queue")
    assert state.state == "5.2"
    assert state.attributes["source"] == "override"
    assert state.attributes["api_queue"] == "4.1"
