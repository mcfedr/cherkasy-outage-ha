"""Config flow for Cherkasy Outage integration."""
from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_API_HASH,
    CONF_API_ID,
    CONF_AUTH_CODE,
    CONF_CHANNEL,
    CONF_GROUP,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_POLL_INTERVAL,
    DEFAULT_CHANNEL,
    DEFAULT_GROUP,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    SESSION_FILE,
)
from .telegram_reader import TelegramReader

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_ID): vol.Coerce(int),
        vol.Required(CONF_API_HASH): str,
        vol.Required(CONF_PHONE): str,
        vol.Optional(CONF_CHANNEL, default=DEFAULT_CHANNEL): str,
        vol.Optional(CONF_GROUP, default=DEFAULT_GROUP): str,
    }
)

STEP_AUTH_CODE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AUTH_CODE): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
    }
)


class CherkasyOutageConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the multi-step config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict[str, Any] = {}
        self._reader: TelegramReader | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1: collect credentials and send auth code."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session_path = self.hass.config.path(SESSION_FILE)
            reader = TelegramReader(
                api_id=int(user_input[CONF_API_ID]),
                api_hash=user_input[CONF_API_HASH],
                session_path=session_path,
            )
            try:
                await reader.send_code_request(user_input[CONF_PHONE])
            except Exception as err:
                _LOGGER.exception("Failed to send Telegram auth code")
                errors["base"] = "cannot_connect"
            else:
                self._reader = reader
                self._user_input = user_input
                return await self.async_step_auth_code()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_auth_code(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 2: verify the auth code sent to the user's Telegram app."""
        errors: dict[str, str] = {}

        if user_input is not None:
            code = user_input[CONF_AUTH_CODE].strip()
            password = user_input.get(CONF_PASSWORD) or None
            try:
                await self._reader.sign_in(
                    self._user_input[CONF_PHONE], code, password
                )
            except PhoneCodeInvalidError:
                errors[CONF_AUTH_CODE] = "invalid_auth"
            except PhoneCodeExpiredError:
                errors[CONF_AUTH_CODE] = "code_expired"
            except SessionPasswordNeededError:
                errors[CONF_PASSWORD] = "password_required"
            except Exception as err:
                _LOGGER.exception("Unexpected error during Telegram sign-in")
                errors["base"] = "unknown"
            else:
                await self._reader.disconnect()
                return self.async_create_entry(
                    title=f"Cherkasy Outage — group {self._user_input[CONF_GROUP]}",
                    data={
                        CONF_API_ID: self._user_input[CONF_API_ID],
                        CONF_API_HASH: self._user_input[CONF_API_HASH],
                        CONF_PHONE: self._user_input[CONF_PHONE],
                        CONF_CHANNEL: self._user_input[CONF_CHANNEL],
                        CONF_GROUP: self._user_input[CONF_GROUP],
                        CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
                    },
                )

        return self.async_show_form(
            step_id="auth_code",
            data_schema=STEP_AUTH_CODE_SCHEMA,
            errors=errors,
            description_placeholders={"phone": self._user_input.get(CONF_PHONE, "")},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CherkasyOutageOptionsFlow:
        return CherkasyOutageOptionsFlow(config_entry)


class CherkasyOutageOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to change poll interval and group after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_POLL_INTERVAL,
            self._config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )
        current_group = self._config_entry.options.get(
            CONF_GROUP,
            self._config_entry.data.get(CONF_GROUP, DEFAULT_GROUP),
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_GROUP, default=current_group): str,
                vol.Optional(
                    CONF_POLL_INTERVAL, default=current_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
