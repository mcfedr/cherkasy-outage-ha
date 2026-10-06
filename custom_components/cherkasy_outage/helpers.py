"""Small Home Assistant glue shared by the config flow and the integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .api import OblenergoClient, create_ssl_context
from .const import DOMAIN, TIME_ZONE

_SSL_KEY: HassKey = HassKey(f"{DOMAIN}_cabinet_ssl")


async def async_get_client(hass: HomeAssistant) -> OblenergoClient:
    """Return a client using HA's shared session and a cached TLS context."""
    context = hass.data.get(_SSL_KEY)
    if context is None:
        context = await hass.async_add_executor_job(create_ssl_context)
        hass.data[_SSL_KEY] = context
    return OblenergoClient(async_get_clientsession(hass), context)


def kyiv_tz():
    """The time zone all oblenergo data is published in."""
    return dt_util.get_time_zone(TIME_ZONE)
