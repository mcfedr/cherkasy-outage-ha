"""Parse Cherkasy Oblenergo Telegram messages into structured outage schedules."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from .const import UA_MONTHS

_LOGGER = logging.getLogger(__name__)

# Matches lines like: "4.1 04:00 - 06:00, 09:00 - 12:00"
# Group 1 = outage group, Group 2 = rest of the line with time ranges
GROUP_PATTERN = re.compile(
    r"^(\d+\.\d+)\s+((?:\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}[,\s]*)+)",
    re.MULTILINE,
)

# Matches individual time windows: "04:00 - 06:00" or "04:00–06:00"
TIME_RANGE_PATTERN = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")

# Matches Ukrainian date phrases: "на 19 березня 2026" or "19 березня 2026"
DATE_PATTERN = re.compile(
    r"(?:на\s+)?(\d{1,2})\s+(" + "|".join(UA_MONTHS.keys()) + r")(?:\s+(\d{4}))?",
    re.IGNORECASE,
)

# Keywords that identify schedule messages
_SCHEDULE_KEYWORDS = (
    "графік погодинних",
    "години відсутності",
    "відключення електроенергії",
    "черговий графік",
)

# Keyword indicating this is an updated/revised schedule
_UPDATE_KEYWORD = "оновлений"


def _is_schedule_message(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _SCHEDULE_KEYWORDS)


def _is_update(text: str) -> bool:
    return _UPDATE_KEYWORD in text.lower()


def _extract_date_from_message(text: str, msg_date: datetime) -> date | None:
    """Parse a Ukrainian date phrase from *text*. Falls back to *msg_date* year."""
    m = DATE_PATTERN.search(text)
    if not m:
        return None
    day = int(m.group(1))
    month = UA_MONTHS.get(m.group(2).lower())
    if month is None:
        return None
    year = int(m.group(3)) if m.group(3) else msg_date.year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_windows(group_line: str) -> list[dict[str, str]]:
    """Extract time windows from a group line, e.g. '04:00 - 06:00, 16:00 - 20:00'."""
    windows: list[dict[str, str]] = []
    for m in TIME_RANGE_PATTERN.finditer(group_line):
        start_str = m.group(1)
        end_str = m.group(2)
        # Normalise "24:00" → "00:00" for end times (midnight end)
        if end_str == "24:00":
            end_str = "00:00"
        windows.append({"start": start_str, "end": end_str})
    return windows


def _windows_for_group(text: str, group: str) -> list[dict[str, str]] | None:
    """Find the line for *group* in *text* and parse its windows. Returns None if not found."""
    for m in GROUP_PATTERN.finditer(text):
        if m.group(1) == group:
            return _parse_windows(m.group(2))
    return None


def _format_windows(windows: list[dict[str, str]]) -> str:
    """Return a human-readable string like '04:00–06:00, 16:00–20:00'."""
    return ", ".join(f"{w['start']}–{w['end']}" for w in windows)


def _total_hours(windows: list[dict[str, str]]) -> float:
    """Sum of all window durations in hours."""
    total = timedelta()
    for w in windows:
        h_s, m_s = map(int, w["start"].split(":"))
        h_e, m_e = map(int, w["end"].split(":"))
        start_t = timedelta(hours=h_s, minutes=m_s)
        # Handle midnight-end windows (end == 00:00 means next midnight)
        if h_e == 0 and m_e == 0:
            end_t = timedelta(hours=24)
        else:
            end_t = timedelta(hours=h_e, minutes=m_e)
        if end_t > start_t:
            total += end_t - start_t
    return round(total.total_seconds() / 3600, 1)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def parse_schedule(
    messages: list[dict[str, Any]],
    group: str,
    today: date | None = None,
) -> dict[str, Any]:
    """Parse schedule for *group* from *messages*.

    Returns a dict with keys:
      "today", "tomorrow" — each a dict with "date", "windows", "windows_formatted",
                            "total_hours", "raw" (or None if no data)
      "last_updated"      — ISO datetime string of the most recent relevant message
      "group"             — the group string
    """
    if today is None:
        today = date.today()
    tomorrow = today + timedelta(days=1)

    # Accumulate candidates: date → list of (msg_timestamp, is_update, windows, raw)
    candidates: dict[date, list[tuple[datetime, bool, list, str]]] = {}

    for msg in messages:
        text = msg.get("text", "") or ""
        if not _is_schedule_message(text):
            continue
        msg_date: datetime = msg["date"]
        sched_date = _extract_date_from_message(text, msg_date)
        if sched_date is None:
            _LOGGER.debug("Could not extract date from message %s", msg.get("id"))
            continue
        if sched_date not in (today, tomorrow):
            continue
        windows = _windows_for_group(text, group)
        if windows is None:
            _LOGGER.debug(
                "Group %s not found in message %s dated %s", group, msg.get("id"), sched_date
            )
            continue
        ts = msg.get("edit_date") or msg_date
        is_upd = _is_update(text)
        candidates.setdefault(sched_date, []).append((ts, is_upd, windows, text))

    def _best(day: date) -> dict[str, Any] | None:
        entries = candidates.get(day)
        if not entries:
            return None
        # Prefer "updated" messages; within the same priority, take the most recent
        entries.sort(key=lambda e: (e[1], e[0]))
        _, _, windows, raw = entries[-1]
        return {
            "date": day.isoformat(),
            "windows": windows,
            "windows_formatted": _format_windows(windows),
            "total_hours": _total_hours(windows),
            "raw": raw,
        }

    all_ts = [
        (msg.get("edit_date") or msg["date"])
        for msg in messages
        if _is_schedule_message(msg.get("text", "") or "")
    ]
    last_updated = max(all_ts).isoformat() if all_ts else None

    return {
        "today": _best(today),
        "tomorrow": _best(tomorrow),
        "last_updated": last_updated,
        "group": group,
    }


def get_next_outage(
    windows: list[dict[str, str]],
    ref_time: time,
    windows_date: date | None = None,
    ref_date: date | None = None,
) -> dict[str, str] | None:
    """Return the first window in *windows* that hasn't fully passed by *ref_time*.

    If *windows_date* and *ref_date* are provided, skips windows from past dates.
    """
    if windows_date and ref_date and windows_date < ref_date:
        return None
    for w in windows:
        h_e, m_e = map(int, w["end"].split(":"))
        if h_e == 0 and m_e == 0:
            # Midnight-end window never passes during the day
            return w
        end_t = time(h_e, m_e)
        if end_t > ref_time:
            return w
    return None


def is_currently_in_outage(windows: list[dict[str, str]], ref_time: time) -> bool:
    """Return True if *ref_time* falls within any window."""
    for w in windows:
        h_s, m_s = map(int, w["start"].split(":"))
        h_e, m_e = map(int, w["end"].split(":"))
        start_t = time(h_s, m_s)
        if h_e == 0 and m_e == 0:
            # Midnight-end window: active from start until end of day
            if ref_time >= start_t:
                return True
        else:
            end_t = time(h_e, m_e)
            if start_t <= ref_time < end_t:
                return True
    return False
