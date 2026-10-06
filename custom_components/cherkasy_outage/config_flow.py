"""Config flow: find the account by address (or enter it), detect its queue."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import OblenergoClient, OblenergoError
from .const import (
    CONF_ACCOUNT,
    CONF_ADDRESS,
    CONF_CITY_ID,
    CONF_DEPARTMENT_ID,
    CONF_HOUSE,
    CONF_QUEUE,
    CONF_QUEUE_OVERRIDE,
    CONF_STREET_ID,
    DOMAIN,
    KNOWN_QUEUES,
    QUEUE_AUTO,
)
from .coordinator import OutageConfigEntry
from .helpers import async_get_client, kyiv_tz

_LOGGER = logging.getLogger(__name__)

CONF_STREET_SEARCH = "street_search"
_ACCOUNT_RE = re.compile(r"^\d{6,14}$")
_QUEUE_RE = re.compile(r"^\d{1,2}\.\d$")


def _select(options: list[SelectOptionDict], *, custom: bool = False) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=custom,
            sort=False,
        )
    )


def _options(items: list[dict[str, str]], value_key: str, label_key: str) -> list[SelectOptionDict]:
    return [
        SelectOptionDict(
            value=str(item[value_key]), label=str(item.get(label_key, item[value_key]))
        )
        for item in items
        if item.get(value_key)
    ]


def _queue_selector() -> SelectSelector:
    return _select([SelectOptionDict(value=q, label=q) for q in KNOWN_QUEUES], custom=True)


class CherkasyOutageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one personal account (особовий рахунок)."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: OblenergoClient | None = None
        self._data: dict[str, Any] = {}
        self._labels: dict[str, str] = {}
        self._choices: list[SelectOptionDict] = []

    async def _api(self) -> OblenergoClient:
        if self._client is None:
            self._client = await async_get_client(self.hass)
        return self._client

    # -- entry point --------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["department", "account"])

    # -- by address ---------------------------------------------------------------

    async def async_step_department(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_DEPARTMENT_ID] = user_input[CONF_DEPARTMENT_ID]
            return await self.async_step_city()
        try:
            options = _options(await (await self._api()).departments(), "ID", "NAME")
        except OblenergoError as err:
            _LOGGER.warning("Could not load departments: %s", err)
            return self.async_abort(reason="cannot_connect")
        default = "1" if any(o["value"] == "1" for o in options) else vol.UNDEFINED
        return self.async_show_form(
            step_id="department",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEPARTMENT_ID, default=default): _select(options)}
            ),
        )

    async def async_step_city(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_CITY_ID] = user_input[CONF_CITY_ID]
            self._labels["city"] = next(
                (o["label"] for o in self._choices if o["value"] == user_input[CONF_CITY_ID]), ""
            )
            return await self.async_step_street_search()
        try:
            self._choices = _options(
                await (await self._api()).cities(self._data[CONF_DEPARTMENT_ID]), "ID", "NAME"
            )
        except OblenergoError:
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="city",
            data_schema=vol.Schema({vol.Required(CONF_CITY_ID): _select(self._choices)}),
        )

    async def async_step_street_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                streets = await (await self._api()).streets(
                    self._data[CONF_CITY_ID], user_input[CONF_STREET_SEARCH].strip()
                )
            except OblenergoError:
                errors["base"] = "cannot_connect"
            else:
                self._choices = _options(streets, "ID", "NAME")
                if self._choices:
                    return await self.async_step_street()
                errors[CONF_STREET_SEARCH] = "no_streets"
        return self.async_show_form(
            step_id="street_search",
            data_schema=vol.Schema({vol.Required(CONF_STREET_SEARCH): TextSelector()}),
            errors=errors,
        )

    async def async_step_street(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_STREET_ID] = user_input[CONF_STREET_ID]
            self._labels["street"] = next(
                (o["label"] for o in self._choices if o["value"] == user_input[CONF_STREET_ID]), ""
            )
            return await self.async_step_house()
        return self.async_show_form(
            step_id="street",
            data_schema=vol.Schema({vol.Required(CONF_STREET_ID): _select(self._choices)}),
        )

    async def async_step_house(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_HOUSE] = user_input[CONF_HOUSE]
            return await self.async_step_select_account()
        try:
            houses = await (await self._api()).houses(self._data[CONF_STREET_ID])
        except OblenergoError:
            return self.async_abort(reason="cannot_connect")
        options = _options(houses, "HOUSE", "HOUSE")
        return self.async_show_form(
            step_id="house",
            data_schema=vol.Schema({vol.Required(CONF_HOUSE): _select(options, custom=True)}),
        )

    async def async_step_select_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            account = user_input[CONF_ACCOUNT]
            self._data[CONF_ACCOUNT] = account
            self._data[CONF_ADDRESS] = self._labels.get(account) or ", ".join(
                p
                for p in (
                    self._labels.get("city"),
                    self._labels.get("street"),
                    self._data[CONF_HOUSE],
                )
                if p
            )
            return await self._async_finish_account()
        try:
            accounts = await (await self._api()).accounts_at(
                self._data[CONF_STREET_ID], self._data[CONF_HOUSE]
            )
        except OblenergoError:
            return self.async_abort(reason="cannot_connect")
        if not accounts:
            return self.async_abort(reason="no_accounts")
        options = []
        for item in accounts:
            if not item.get("LS"):
                continue
            ls = str(item["LS"])
            self._labels[ls] = str(item.get("ADDRESS") or "")
            options.append(
                SelectOptionDict(
                    value=ls, label=f"{ls} — {item.get('NAME', '')} ({item.get('ADDRESS', '')})"
                )
            )
        return self.async_show_form(
            step_id="select_account",
            data_schema=vol.Schema({vol.Required(CONF_ACCOUNT): _select(options)}),
        )

    # -- by account number --------------------------------------------------------

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            account = re.sub(r"\D", "", user_input[CONF_ACCOUNT])
            if _ACCOUNT_RE.match(account):
                self._data[CONF_ACCOUNT] = account
                return await self._async_finish_account()
            errors[CONF_ACCOUNT] = "invalid_account"
        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema({vol.Required(CONF_ACCOUNT): TextSelector()}),
            errors=errors,
        )

    # -- common tail ----------------------------------------------------------------

    async def _async_finish_account(self) -> ConfigFlowResult:
        account = self._data[CONF_ACCOUNT]
        await self.async_set_unique_id(account)
        self._abort_if_unique_id_configured()
        try:
            queue, _ = await (await self._api()).queue_info(account, dt_util.now(kyiv_tz()).date())
        except OblenergoError as err:
            _LOGGER.warning("Could not look up queue for account: %s", err)
            return self.async_abort(reason="cannot_connect")
        if queue.gpv:
            self._data[CONF_QUEUE] = queue.gpv
            return self._create()
        # The API knows nothing about this account (or has no queue for it yet):
        # let the user carry on with a queue they know.
        return await self.async_step_queue()

    async def async_step_queue(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            queue = user_input[CONF_QUEUE].strip()
            if _QUEUE_RE.match(queue):
                self._data[CONF_QUEUE] = queue
                return self._create()
            errors[CONF_QUEUE] = "invalid_queue"
        return self.async_show_form(
            step_id="queue",
            data_schema=vol.Schema({vol.Required(CONF_QUEUE): _queue_selector()}),
            errors=errors,
            description_placeholders={"account": self._data[CONF_ACCOUNT]},
        )

    def _create(self) -> ConfigFlowResult:
        title = self._data.get(CONF_ADDRESS) or f"Account {self._data[CONF_ACCOUNT]}"
        return self.async_create_entry(title=title, data=self._data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: OutageConfigEntry) -> OptionsFlowHandler:
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlowWithReload):
    """Override the detected ГПВ queue."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            queue = str(user_input[CONF_QUEUE_OVERRIDE]).strip()
            if queue == QUEUE_AUTO or _QUEUE_RE.match(queue):
                return self.async_create_entry(data={CONF_QUEUE_OVERRIDE: queue})
            errors[CONF_QUEUE_OVERRIDE] = "invalid_queue"
        options = [SelectOptionDict(value=QUEUE_AUTO, label=QUEUE_AUTO)] + [
            SelectOptionDict(value=q, label=q) for q in KNOWN_QUEUES
        ]
        current = self.config_entry.options.get(CONF_QUEUE_OVERRIDE, QUEUE_AUTO)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_QUEUE_OVERRIDE, default=current): _select(options, custom=True)}
            ),
            errors=errors,
        )
