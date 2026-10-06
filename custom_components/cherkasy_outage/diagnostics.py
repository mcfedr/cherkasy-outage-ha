"""Diagnostics download (account number and address redacted)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ACCOUNT, CONF_ADDRESS, CONF_HOUSE, CONF_STREET_ID
from .coordinator import OutageConfigEntry

TO_REDACT = {
    CONF_ACCOUNT,
    CONF_ADDRESS,
    CONF_HOUSE,
    CONF_STREET_ID,
    "title",
    "unique_id",
    "description",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OutageConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    account = runtime.account.data
    return {
        "entry": async_redact_data(
            {"data": dict(entry.data), "options": dict(entry.options)}, TO_REDACT
        ),
        "queue": runtime.queue,
        "queue_source": runtime.queue_source,
        "account": async_redact_data(
            {
                "queue": asdict(account.queue) if account else None,
                "data_as_of": account.data_as_of if account else None,
                "outages": [asdict(o) for o in account.outages] if account else [],
            },
            TO_REDACT,
        ),
        "schedule": {
            str(day): {
                "slug": post.slug,
                "title": post.title,
                "published_at": post.published_at.isoformat(),
                "is_update": post.is_update,
                "cancelled": post.cancelled,
                "queues": post.queues,
            }
            for day, post in runtime.schedule_posts.items()
        },
        "unparsed_posts": runtime.schedule.data.unparsed if runtime.schedule.data else [],
        "schedule_last_update_success": runtime.schedule.last_update_success,
        "account_last_update_success": runtime.account.last_update_success,
    }
