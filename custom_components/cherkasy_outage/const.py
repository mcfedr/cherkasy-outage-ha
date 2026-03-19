"""Constants for the Cherkasy Outage integration."""

DOMAIN = "cherkasy_outage"

# Config entry keys
CONF_API_ID = "api_id"
CONF_API_HASH = "api_hash"
CONF_PHONE = "phone"
CONF_CHANNEL = "channel"
CONF_GROUP = "group"
CONF_POLL_INTERVAL = "poll_interval"
CONF_AUTH_CODE = "auth_code"
CONF_PASSWORD = "password"

# Defaults
DEFAULT_CHANNEL = "pat_cherkasyoblenergo"
DEFAULT_GROUP = "4.1"
DEFAULT_POLL_INTERVAL = 30  # minutes
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 120

# Session file stored in HA config directory
SESSION_FILE = "cherkasy_outage_telethon"

# Number of recent messages to fetch
FETCH_LIMIT = 30

# Ukrainian month names → month number
UA_MONTHS: dict[str, int] = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}

# Entity IDs / unique ID suffixes
ENTITY_SCHEDULE_TODAY = "schedule_today"
ENTITY_SCHEDULE_TOMORROW = "schedule_tomorrow"
ENTITY_NEXT_OUTAGE_START = "next_outage_start"
ENTITY_NEXT_OUTAGE_END = "next_outage_end"
ENTITY_LAST_UPDATED = "last_updated"
ENTITY_OUTAGE_ACTIVE = "outage_active"
