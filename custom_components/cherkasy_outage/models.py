"""Plain data types shared by the API client, parser and entities.

Nothing in here imports Home Assistant, so it can be unit-tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Outage:
    """One outage window, already resolved to time-zone-aware datetimes."""

    kind: str  # const.KIND_*
    start: datetime
    end: datetime
    summary: str
    description: str = ""
    # For planned/emergency works: the oblenergo status text, e.g. "Заплановано".
    status: str | None = None
    # True when the end time is only an estimate ("(план)").
    end_is_estimate: bool = False

    def contains(self, moment: datetime) -> bool:
        """Return True if *moment* is inside this window (end exclusive)."""
        return self.start <= moment < self.end

    def as_dict(self) -> dict[str, str | bool | None]:
        """Serialise for state attributes / events."""
        return {
            "kind": self.kind,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "summary": self.summary,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class SchedulePost:
    """An hourly-schedule (ГПВ) news post, parsed."""

    slug: str
    title: str
    schedule_date: date
    published_at: datetime
    is_update: bool
    # True when the post says the schedules will NOT be applied that day.
    cancelled: bool
    # queue ("4.1") -> list of (start, end) in "HH:MM" form; end may be "24:00".
    queues: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QueueInfo:
    """The account's queue assignment as reported by the cabinet API."""

    gpv: str | None  # hourly schedule sub-queue, e.g. "4.1"
    gav: str | None  # emergency schedule queue, e.g. "3"
    raw: tuple[str, ...] = ()


@dataclass(slots=True)
class AccountData:
    """Everything the account coordinator fetched in one poll."""

    queue: QueueInfo
    outages: list[Outage]
    data_as_of: str | None = None  # the API's DATETIME string, verbatim


@dataclass(slots=True)
class ScheduleData:
    """Everything the schedule coordinator knows: one post per date (latest wins)."""

    posts: dict[date, SchedulePost]
    # Posts that looked like schedules but no queue lines could be read.
    unparsed: list[str] = field(default_factory=list)
