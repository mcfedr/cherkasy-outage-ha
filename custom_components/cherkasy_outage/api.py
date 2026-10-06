"""Async client for the two Cherkasyoblenergo APIs.

* cabinet.cherkasyoblenergo.com/api_new/disconn.php – address dictionaries, the
  account's queue assignment and planned / emergency works.
* www.cherkasyoblenergo.com/api/v1/posts – news posts, which is where the hourly
  ГПВ schedule by queue is published (the cabinet API does not carry it for
  Cherkasy city accounts).
"""

from __future__ import annotations

import asyncio
from datetime import date, tzinfo
import json
import logging
import ssl
from typing import Any

import aiohttp

from .const import (
    CABINET_URL,
    KIND_EMERGENCY,
    KIND_PLANNED,
    NEWS_LIST_URL,
    NEWS_PAGE_SIZE,
    NEWS_POST_URL,
    SELECTOR_EMERGENCY,
    SELECTOR_PLANNED,
    SELECTOR_SCHEDULES,
)
from .models import Outage, QueueInfo
from .parser import as_list, parse_disconnections, parse_queue_info

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# cabinet.cherkasyoblenergo.com only sends its leaf certificate, without the
# intermediate. Browsers fetch the missing intermediate themselves; Python does not,
# so we add it to the trust store for requests to that host. Verification stays on.
# Subject: Sectigo Public Server Authentication CA DV R36 (valid until 2036-03-21),
# issued by Sectigo Public Server Authentication Root R46, which is in certifi.
SECTIGO_DV_R36_PEM = """\
-----BEGIN CERTIFICATE-----
MIIGTDCCBDSgAwIBAgIQOXpmzCdWNi4NqofKbqvjsTANBgkqhkiG9w0BAQwFADBf
MQswCQYDVQQGEwJHQjEYMBYGA1UEChMPU2VjdGlnbyBMaW1pdGVkMTYwNAYDVQQD
Ey1TZWN0aWdvIFB1YmxpYyBTZXJ2ZXIgQXV0aGVudGljYXRpb24gUm9vdCBSNDYw
HhcNMjEwMzIyMDAwMDAwWhcNMzYwMzIxMjM1OTU5WjBgMQswCQYDVQQGEwJHQjEY
MBYGA1UEChMPU2VjdGlnbyBMaW1pdGVkMTcwNQYDVQQDEy5TZWN0aWdvIFB1Ymxp
YyBTZXJ2ZXIgQXV0aGVudGljYXRpb24gQ0EgRFYgUjM2MIIBojANBgkqhkiG9w0B
AQEFAAOCAY8AMIIBigKCAYEAljZf2HIz7+SPUPQCQObZYcrxLTHYdf1ZtMRe7Yeq
RPSwygz16qJ9cAWtWNTcuICc++p8Dct7zNGxCpqmEtqifO7NvuB5dEVexXn9RFFH
12Hm+NtPRQgXIFjx6MSJcNWuVO3XGE57L1mHlcQYj+g4hny90aFh2SCZCDEVkAja
EMMfYPKuCjHuuF+bzHFb/9gV8P9+ekcHENF2nR1efGWSKwnfG5RawlkaQDpRtZTm
M64TIsv/r7cyFO4nSjs1jLdXYdz5q3a4L0NoabZfbdxVb+CUEHfB0bpulZQtH1Rv
38e/lIdP7OTTIlZh6OYL6NhxP8So0/sht/4J9mqIGxRFc0/pC8suja+wcIUna0HB
pXKfXTKpzgis+zmXDL06ASJf5E4A2/m+Hp6b84sfPAwQ766rI65mh50S0Di9E3Pn
2WcaJc+PILsBmYpgtmgWTR9eV9otfKRUBfzHUHcVgarub/XluEpRlTtZudU5xbFN
xx/DgMrXLUAPaI60fZ6wA+PTAgMBAAGjggGBMIIBfTAfBgNVHSMEGDAWgBRWc1hk
lfmSGrASKgRieaFAFYghSTAdBgNVHQ4EFgQUaMASFhgOr872h6YyV6NGUV3LBycw
DgYDVR0PAQH/BAQDAgGGMBIGA1UdEwEB/wQIMAYBAf8CAQAwHQYDVR0lBBYwFAYI
KwYBBQUHAwEGCCsGAQUFBwMCMBsGA1UdIAQUMBIwBgYEVR0gADAIBgZngQwBAgEw
VAYDVR0fBE0wSzBJoEegRYZDaHR0cDovL2NybC5zZWN0aWdvLmNvbS9TZWN0aWdv
UHVibGljU2VydmVyQXV0aGVudGljYXRpb25Sb290UjQ2LmNybDCBhAYIKwYBBQUH
AQEEeDB2ME8GCCsGAQUFBzAChkNodHRwOi8vY3J0LnNlY3RpZ28uY29tL1NlY3Rp
Z29QdWJsaWNTZXJ2ZXJBdXRoZW50aWNhdGlvblJvb3RSNDYucDdjMCMGCCsGAQUF
BzABhhdodHRwOi8vb2NzcC5zZWN0aWdvLmNvbTANBgkqhkiG9w0BAQwFAAOCAgEA
YtOC9Fy+TqECFw40IospI92kLGgoSZGPOSQXMBqmsGWZUQ7rux7cj1du6d9rD6C8
ze1B2eQjkrGkIL/OF1s7vSmgYVafsRoZd/IHUrkoQvX8FZwUsmPu7amgBfaY3g+d
q1x0jNGKb6I6Bzdl6LgMD9qxp+3i7GQOnd9J8LFSietY6Z4jUBzVoOoz8iAU84OF
h2HhAuiPw1ai0VnY38RTI+8kepGWVfGxfBWzwH9uIjeooIeaosVFvE8cmYUB4TSH
5dUyD0jHct2+8ceKEtIoFU/FfHq/mDaVnvcDCZXtIgitdMFQdMZaVehmObyhRdDD
4NQCs0gaI9AAgFj4L9QtkARzhQLNyRf87Kln+YU0lgCGr9HLg3rGO8q+Y4ppLsOd
unQZ6ZxPNGIfOApbPVf5hCe58EZwiWdHIMn9lPP6+F404y8NNugbQixBber+x536
WrZhFZLjEkhp7fFXf9r32rNPfb74X/U90Bdy4lzp3+X1ukh1BuMxA/EEhDoTOS3l
7ABvc7BYSQubQ2490OcdkIzUh3ZwDrakMVrbaTxUM2p24N6dB+ns2zptWCva6jzW
r8IWKIMxzxLPv5Kt3ePKcUdvkBU/smqujSczTzzSjIoR5QqQA6lN1ZRSnuHIWCvh
JEltkYnTAH41QJ6SAWO66GrrUESwN/cgZzL4JLEqz1Y=
-----END CERTIFICATE-----
"""


class OblenergoError(Exception):
    """Base error for this client."""


class OblenergoConnectionError(OblenergoError):
    """The API could not be reached or returned an HTTP error."""


class OblenergoResponseError(OblenergoError):
    """The API answered with something we could not understand."""


def create_ssl_context() -> ssl.SSLContext:
    """Build the TLS context for the cabinet host. Blocking: run it in an executor."""
    import certifi  # bundled with Home Assistant

    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cadata=SECTIGO_DV_R36_PEM)
    return context


def _ddmmyyyy(day: date) -> str:
    return day.strftime("%d.%m.%Y")


class OblenergoClient:
    """Thin async wrapper over the oblenergo HTTP APIs."""

    def __init__(self, session: aiohttp.ClientSession, cabinet_ssl: ssl.SSLContext) -> None:
        self._session = session
        self._cabinet_ssl = cabinet_ssl

    async def _get_json(self, url: str, params: dict[str, Any], **kwargs: Any) -> Any:
        try:
            async with self._session.get(
                url, params=params, timeout=REQUEST_TIMEOUT, **kwargs
            ) as response:
                response.raise_for_status()
                # The cabinet API labels JSON as x-javascript, so decode the text ourselves.
                text = await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise OblenergoConnectionError(f"{url}: {err}") from err
        try:
            return json.loads(text)
        except ValueError as err:
            raise OblenergoResponseError(f"{url}: invalid JSON: {text[:200]!r}") from err

    async def _cabinet(self, **params: Any) -> Any:
        data = await self._get_json(CABINET_URL, params, ssl=self._cabinet_ssl)
        if isinstance(data, dict) and data.get("result") == "Operation not supported":
            raise OblenergoResponseError(f"cabinet API rejected op={params.get('op')}")
        return data

    # -- address dictionaries (config flow) ---------------------------------

    async def departments(self) -> list[dict[str, str]]:
        return as_list(await self._cabinet(op="department_list"))

    async def cities(self, department_id: str) -> list[dict[str, str]]:
        return as_list(await self._cabinet(op="city_list", dept_id=department_id))

    async def streets(self, city_id: str, search: str = "") -> list[dict[str, str]]:
        return as_list(await self._cabinet(op="street_list", city_id=city_id, search_name=search))

    async def houses(self, street_id: str) -> list[dict[str, str]]:
        return as_list(await self._cabinet(op="house_list", street_id=street_id, search_name=""))

    async def accounts_at(self, street_id: str, house: str) -> list[dict[str, str]]:
        return as_list(await self._cabinet(op="ls_list_by_addr", street_id=street_id, house=house))

    # -- account data --------------------------------------------------------

    async def _disconnections(
        self, account: str, selector: int, start: date, end: date
    ) -> dict[str, Any]:
        data = await self._cabinet(
            op="disconn_by_ls",
            abon_ls=account,
            disconn_selector=selector,
            n_date=_ddmmyyyy(start),
            k_date=_ddmmyyyy(end),
        )
        if not isinstance(data, dict) or "DISCONNECTIONS" not in data:
            raise OblenergoResponseError(f"unexpected disconn_by_ls response: {str(data)[:200]}")
        return data

    async def queue_info(self, account: str, today: date) -> tuple[QueueInfo, str | None]:
        """The account's ГПВ/ГАВ queues (empty for an unknown account)."""
        data = await self._disconnections(account, SELECTOR_SCHEDULES, today, today)
        return parse_queue_info(data.get("DISCONN_QUEUQ")), data.get("DATETIME")

    async def works(self, account: str, start: date, end: date, tz: tzinfo) -> list[Outage]:
        """Planned and emergency works affecting the account between two dates."""
        planned, emergency = await asyncio.gather(
            self._disconnections(account, SELECTOR_PLANNED, start, end),
            self._disconnections(account, SELECTOR_EMERGENCY, start, end),
        )
        return parse_disconnections(
            planned.get("DISCONNECTIONS"), KIND_PLANNED, tz
        ) + parse_disconnections(emergency.get("DISCONNECTIONS"), KIND_EMERGENCY, tz)

    # -- news posts ----------------------------------------------------------

    async def latest_posts(self) -> list[dict[str, Any]]:
        """Newest news posts (metadata only: title, slug, publishedAt…)."""
        data = await self._get_json(
            NEWS_LIST_URL, {"lang": "uk", "page": 0, "size": NEWS_PAGE_SIZE}
        )
        if not isinstance(data, dict) or not data.get("success"):
            raise OblenergoResponseError(f"unexpected news list response: {str(data)[:200]}")
        return as_list((data.get("data") or {}).get("content"))

    async def post(self, slug: str) -> dict[str, Any]:
        """A single news post including its HTML content."""
        data = await self._get_json(NEWS_POST_URL.format(slug=slug), {"lang": "uk"})
        if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
            raise OblenergoResponseError(f"unexpected news post response for {slug}")
        return data["data"]


def published_at_of(post: dict[str, Any]) -> str:
    """The post's publish timestamp string (falls back to createdAt)."""
    return str(post.get("publishedAt") or post.get("createdAt") or "")


__all__ = [
    "OblenergoClient",
    "OblenergoConnectionError",
    "OblenergoError",
    "OblenergoResponseError",
    "create_ssl_context",
    "published_at_of",
]
