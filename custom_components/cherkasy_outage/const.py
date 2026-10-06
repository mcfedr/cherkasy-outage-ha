"""Constants for the Cherkasy Outage Schedule integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "cherkasy_outage"

# The oblenergo publishes everything in Kyiv local time, whatever the HA time zone is.
TIME_ZONE: Final = "Europe/Kyiv"

CABINET_URL: Final = "https://cabinet.cherkasyoblenergo.com/api_new/disconn.php"
NEWS_LIST_URL: Final = "https://www.cherkasyoblenergo.com/api/v1/posts/category/news"
NEWS_POST_URL: Final = "https://www.cherkasyoblenergo.com/api/v1/posts/{slug}"

# Config entry data
CONF_ACCOUNT: Final = "account"
CONF_ADDRESS: Final = "address"
CONF_DEPARTMENT_ID: Final = "department_id"
CONF_CITY_ID: Final = "city_id"
CONF_STREET_ID: Final = "street_id"
CONF_HOUSE: Final = "house"
CONF_QUEUE: Final = "queue"  # ГПВ queue detected (or entered) at setup time

# Config entry options
CONF_QUEUE_OVERRIDE: Final = "queue_override"
QUEUE_AUTO: Final = "auto"

# Every ГПВ sub-queue the oblenergo has used so far (1.1 … 6.2).
KNOWN_QUEUES: Final = [f"{q}.{s}" for q in range(1, 7) for s in (1, 2)]

# Polling
SCHEDULE_SCAN_INTERVAL: Final = timedelta(minutes=10)
ACCOUNT_SCAN_INTERVAL: Final = timedelta(minutes=30)
# Keep serving the last good data for this many failed polls before going unavailable.
MAX_CONSECUTIVE_FAILURES: Final = 3

# How far ahead to ask for planned / emergency works.
ACCOUNT_LOOKAHEAD_DAYS: Final = 7
# How many news posts to scan for schedule posts (newest first).
NEWS_PAGE_SIZE: Final = 20
# Schedule posts older than this (by publish time) are ignored.
SCHEDULE_POST_MAX_AGE: Final = timedelta(days=3)

# cabinet API disconn_selector values
SELECTOR_PLANNED: Final = 0
SELECTOR_EMERGENCY: Final = 1
SELECTOR_SCHEDULES: Final = 2

# Outage kinds
KIND_GPV: Final = "gpv"
KIND_PLANNED: Final = "planned"
KIND_EMERGENCY: Final = "emergency"

EVENT_SCHEDULE_CHANGED: Final = f"{DOMAIN}_schedule_changed"
