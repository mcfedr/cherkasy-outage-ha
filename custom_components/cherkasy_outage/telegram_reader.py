"""Telethon-based Telegram channel reader."""
from __future__ import annotations

import logging
import os
from typing import Any

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from .const import FETCH_LIMIT

_LOGGER = logging.getLogger(__name__)


class TelegramReader:
    """Manages a Telethon user-mode connection to read a public Telegram channel."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_path: str,
    ) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_path = session_path
        self._client: TelegramClient | None = None
        self._phone_code_hash: str | None = None

    # ------------------------------------------------------------------
    # Auth helpers (config flow only)
    # ------------------------------------------------------------------

    async def send_code_request(self, phone: str) -> None:
        """Send an auth code to *phone* via Telegram. Stores phone_code_hash."""
        client = TelegramClient(self._session_path, self._api_id, self._api_hash)
        await client.connect()
        result = await client.send_code_request(phone)
        self._phone_code_hash = result.phone_code_hash
        self._client = client

    async def sign_in(self, phone: str, code: str, password: str | None = None) -> None:
        """Complete sign-in with the code the user received.

        Raises SessionPasswordNeededError if 2FA is required and *password* is None.
        Raises PhoneCodeInvalidError / PhoneCodeExpiredError on bad/expired code.
        """
        if self._client is None:
            raise RuntimeError("send_code_request must be called before sign_in")
        try:
            await self._client.sign_in(
                phone, code, phone_code_hash=self._phone_code_hash
            )
        except SessionPasswordNeededError:
            if password:
                await self._client.sign_in(password=password)
            else:
                raise
        finally:
            self._phone_code_hash = None

    # ------------------------------------------------------------------
    # Normal operation
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect (and verify) using a saved session. Raises if not authorised."""
        client = TelegramClient(self._session_path, self._api_id, self._api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise PermissionError(
                "Telegram session is not authorised. "
                "Please reconfigure the integration to re-authenticate."
            )
        self._client = client
        _LOGGER.debug("Telegram client connected and authorised")

    async def fetch_recent_messages(
        self, channel: str, limit: int = FETCH_LIMIT
    ) -> list[dict[str, Any]]:
        """Return the last *limit* messages from *channel* as plain dicts."""
        if self._client is None:
            raise RuntimeError("Not connected — call connect() first")
        messages: list[dict[str, Any]] = []
        async for msg in self._client.iter_messages(channel, limit=limit):
            if msg.text:
                messages.append(
                    {
                        "id": msg.id,
                        "text": msg.text,
                        "date": msg.date,
                        "edit_date": msg.edit_date,
                    }
                )
        _LOGGER.debug("Fetched %d messages from %s", len(messages), channel)
        return messages

    async def disconnect(self) -> None:
        """Cleanly close the Telethon connection."""
        if self._client is not None:
            await self._client.disconnect()
            self._client = None
            _LOGGER.debug("Telegram client disconnected")

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected()
