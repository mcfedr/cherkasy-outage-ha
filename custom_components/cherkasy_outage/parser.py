"""Parsers for Cherkasyoblenergo responses.

Pure functions only (no Home Assistant imports) so they can be tested against the
recorded fixtures in ``tests/fixtures``. All times the oblenergo publishes are Kyiv
local time; callers pass the ``tzinfo`` to attach.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, tzinfo
import html
import re
from typing import Any

from .const import KIND_GPV
from .models import Outage, QueueInfo, SchedulePost

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

_BLOCK_END_RE = re.compile(r"</(?:p|div|li|h\d)>|<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_IN_TEXT_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(UA_MONTHS) + r")", re.IGNORECASE)
# "4.1 09:00 - 11:00, 19:00 - 21:00" (separator after the queue is optional)
_QUEUE_LINE_RE = re.compile(r"^\s*(\d{1,2}\.\d)(?!\d)\s*[:\-–—]?\s*(.*)$")
_WINDOW_RE = re.compile(r"(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})")
_CANCELLED_RE = re.compile(
    r"не\s+(?:буд\w*\s+)?застосов\w*|застосов\w*\s+не\s+буд\w*|скасов\w*|не\s+діят\w*",
    re.IGNORECASE,
)
_CABINET_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s+(\d{1,2})\.(\d{1,2})\.(\d{4})")
_GPV_QUEUE_RE = re.compile(r"(\d+)\s*черг\w*\D{0,5}(\d+)\s*підчерг", re.IGNORECASE)
_DOTTED_QUEUE_RE = re.compile(r"(\d+\.\d+)")
_PLAIN_QUEUE_RE = re.compile(r"(\d+)\s*черг", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def as_list(value: Any) -> list[Any]:
    """Normalise an API collection: arrays come back as lists or index-keyed objects."""
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def html_to_text(content: str) -> str:
    """Turn the oblenergo's HTML snippets into plain text, one block per line."""
    text = _BLOCK_END_RE.sub("\n", content or "")
    text = html.unescape(_TAG_RE.sub("", text)).replace("\xa0", " ")
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _at(day: date, hhmm: str, tz: tzinfo) -> datetime:
    """Resolve "HH:MM" on *day* (allowing "24:00") to an aware datetime."""
    hours, minutes = (int(part) for part in hhmm.split(":"))
    if hours == 24 and minutes == 0:
        return datetime.combine(day + timedelta(days=1), time(0, 0), tz)
    return datetime.combine(day, time(hours, minutes), tz)


def merge_outages(outages: Iterable[Outage]) -> list[Outage]:
    """Drop duplicates and merge overlapping/adjacent windows of the same kind."""
    merged: list[Outage] = []
    for outage in sorted(set(outages), key=lambda o: (o.kind, o.summary, o.start, o.end)):
        last = merged[-1] if merged else None
        if (
            last is not None
            and last.kind == outage.kind
            and last.summary == outage.summary
            and outage.start <= last.end
        ):
            if outage.end > last.end:
                merged[-1] = Outage(
                    kind=last.kind,
                    start=last.start,
                    end=outage.end,
                    summary=last.summary,
                    description=last.description,
                    status=last.status,
                    end_is_estimate=outage.end_is_estimate,
                )
            continue
        merged.append(outage)
    return sorted(merged, key=lambda o: (o.start, o.end, o.kind))


# ---------------------------------------------------------------------------
# News posts (hourly ГПВ schedule by queue)
# ---------------------------------------------------------------------------


def is_schedule_title(title: str) -> bool:
    """True for "Графік погодинних відключень (ГПВ) на 7 жовтня" and its updates."""
    lower = (title or "").lower()
    return "погодинн" in lower and "відключ" in lower


def parse_published_at(value: str, tz: tzinfo) -> datetime | None:
    """Parse the API's naive ISO timestamp (Kyiv local time)."""
    try:
        parsed = datetime.fromisoformat(value)
    except TypeError, ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def _schedule_date(title: str, text: str, published_at: datetime) -> date | None:
    match = _DATE_IN_TEXT_RE.search(title) or _DATE_IN_TEXT_RE.search(text)
    if not match:
        return None
    day, month = int(match.group(1)), UA_MONTHS[match.group(2).lower()]
    base = published_at.date()
    candidates = []
    for year in (base.year - 1, base.year, base.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    # Pick the year that puts the date closest to when the post was published
    # (handles posts on 31 December about 1 January).
    return min(candidates, key=lambda d: abs((d - base).days))


def parse_queue_lines(text: str) -> dict[str, list[tuple[str, str]]]:
    """Extract "queue -> [(start, end), ...]" from the plain-text body of a post."""
    queues: dict[str, list[tuple[str, str]]] = {}
    for line in text.splitlines():
        match = _QUEUE_LINE_RE.match(line)
        if not match:
            continue
        windows = [
            (f"{int(h1):02d}:{m1}", f"{int(h2):02d}:{m2}")
            for h1, m1, h2, m2 in _WINDOW_RE.findall(match.group(2))
        ]
        queues.setdefault(match.group(1), []).extend(windows)
    return queues


def parse_schedule_post(
    *, slug: str, title: str, content: str, published_at: datetime
) -> SchedulePost | None:
    """Parse one ГПВ news post. Returns None if it isn't a schedule post or has no date."""
    if not is_schedule_title(title):
        return None
    text = html_to_text(content)
    schedule_date = _schedule_date(title, text, published_at)
    if schedule_date is None:
        return None
    queues = parse_queue_lines(text)
    cancelled = not queues and bool(_CANCELLED_RE.search(f"{title}\n{text}"))
    return SchedulePost(
        slug=slug,
        title=title,
        schedule_date=schedule_date,
        published_at=published_at,
        is_update="оновл" in title.lower(),
        cancelled=cancelled,
        queues=queues,
    )


def latest_per_date(posts: Iterable[SchedulePost]) -> dict[date, SchedulePost]:
    """Keep the most recently published usable post for each schedule date."""
    latest: dict[date, SchedulePost] = {}
    for post in posts:
        if not post.queues and not post.cancelled:
            continue
        current = latest.get(post.schedule_date)
        if current is None or (post.published_at, post.is_update) > (
            current.published_at,
            current.is_update,
        ):
            latest[post.schedule_date] = post
    return latest


def schedule_outages(posts: dict[date, SchedulePost], queue: str, tz: tzinfo) -> list[Outage]:
    """All ГПВ windows for *queue*, across every known schedule date."""
    outages: list[Outage] = []
    for day, post in posts.items():
        for start_s, end_s in post.queues.get(queue, []):
            start = _at(day, start_s, tz)
            end = _at(day, end_s, tz)
            if end <= start:  # e.g. "23:00 - 01:00" runs past midnight
                end += timedelta(days=1)
            outages.append(
                Outage(
                    kind=KIND_GPV,
                    start=start,
                    end=end,
                    summary=f"ГПВ {queue}",
                    description=post.title,
                )
            )
    return merge_outages(outages)


# ---------------------------------------------------------------------------
# Cabinet API (account queue, planned and emergency works)
# ---------------------------------------------------------------------------


def parse_cabinet_time(value: str | None, tz: tzinfo) -> tuple[datetime | None, bool]:
    """Parse "10:18 06.10.2026" / "16:00 08.10.2026 (план)" -> (datetime, is_estimate)."""
    if not value:
        return None, False
    match = _CABINET_TIME_RE.search(value)
    if not match:
        return None, False
    hours, minutes, day, month, year = (int(g) for g in match.groups())
    try:
        parsed = datetime(year, month, day, hours, minutes, tzinfo=tz)
    except ValueError:
        return None, False
    return parsed, "план" in value.lower()


def parse_disconnections(raw: Any, kind: str, tz: tzinfo) -> list[Outage]:
    """Parse the DISCONNECTIONS array of a disconn_by_ls / disconn_by_dept response."""
    outages: list[Outage] = []
    for item in as_list(raw):
        if not isinstance(item, dict):
            continue
        start, _ = parse_cabinet_time(item.get("DATE_START"), tz)
        end, estimate = parse_cabinet_time(item.get("DATE_STOP"), tz)
        if start is None or end is None or end <= start:
            continue
        details = [
            html_to_text(item.get("DATE_TIME") or ""),
            html_to_text(item.get("ADDRESS") or ""),
        ]
        outages.append(
            Outage(
                kind=kind,
                start=start,
                end=end,
                summary=str(item.get("DISCONN_TYPE") or kind),
                description="\n".join(d for d in details if d),
                status=item.get("STATE_CHAR"),
                end_is_estimate=estimate,
            )
        )
    return outages


def parse_queue_info(raw: Any) -> QueueInfo:
    """Read the account's ГПВ sub-queue and ГАВ queue from DISCONN_QUEUQ."""
    texts = tuple(
        str(item.get("QUEUE_INFO", "")).strip()
        for item in as_list(raw)
        if isinstance(item, dict) and item.get("QUEUE_INFO")
    )
    gpv: str | None = None
    gav: str | None = None
    for text in texts:
        lower = text.lower()
        if "погодинн" in lower and gpv is None:
            if match := _GPV_QUEUE_RE.search(text):
                gpv = f"{int(match.group(1))}.{int(match.group(2))}"
            elif match := _DOTTED_QUEUE_RE.search(text):
                gpv = match.group(1)
        elif (
            "аварійн" in lower
            and "спеціальн" not in lower
            and gav is None
            and (match := _PLAIN_QUEUE_RE.search(text))
        ):
            gav = match.group(1)
    return QueueInfo(gpv=gpv, gav=gav, raw=texts)
