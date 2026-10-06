"""Parser tests against responses recorded from the live APIs on 2026-10-06."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custom_components.cherkasy_outage.const import KIND_EMERGENCY, KIND_GPV, KIND_PLANNED
from custom_components.cherkasy_outage.models import Outage, SchedulePost
from custom_components.cherkasy_outage.parser import (
    as_list,
    html_to_text,
    is_schedule_title,
    latest_per_date,
    merge_outages,
    parse_cabinet_time,
    parse_disconnections,
    parse_published_at,
    parse_queue_info,
    parse_queue_lines,
    parse_schedule_post,
    schedule_outages,
)

from .conftest import KYIV, load_fixture

POST_7 = "news_post_hrafik-pohodynnykh-vidklyuchen-hpv-na-7-zhovtnya.json"
POST_6 = "news_post_hrafik-pohodynnykh-vidklyuchen-hpv-na-6-zhovtnya.json"
POST_6_UPDATED = "news_post_onovleno-hrafik-pohodynnykh-vidklyuchen-hpv-na-6-zhovtnya.json"


def _post(name: str) -> SchedulePost | None:
    data = load_fixture(name)["data"]
    return parse_schedule_post(
        slug=data["slug"],
        title=data["title"],
        content=data["content"],
        published_at=parse_published_at(data["publishedAt"], KYIV),
    )


# -- news posts -------------------------------------------------------------------


def test_schedule_titles() -> None:
    assert is_schedule_title("Графік погодинних відключень (ГПВ) на 7 жовтня")
    assert is_schedule_title("Оновлено графік погодинних відключень (ГПВ) на 6 жовтня")
    assert not is_schedule_title(
        "Для промисловості та бізнесу Черкаської області 7 жовтня діятимуть графіки обмеження потужності (ГОП)"
    )
    assert not is_schedule_title("З Днем захисників і захисниць України!")


def test_news_list_has_three_schedule_posts() -> None:
    posts = load_fixture("news_list.json")["data"]["content"]
    titles = [p["title"] for p in posts if is_schedule_title(p["title"])]
    assert len(titles) == 3


def test_parse_7_october_post() -> None:
    post = _post(POST_7)
    assert post is not None
    assert post.schedule_date == date(2026, 10, 7)
    assert not post.is_update
    assert not post.cancelled
    assert len(post.queues) == 12
    # Times in the HTML are split across <span>s; they must still come out whole.
    assert post.queues["4.1"] == [("09:00", "11:00"), ("19:00", "21:00")]
    assert post.queues["5.1"] == [("00:00", "01:00"), ("11:00", "13:00"), ("19:00", "21:00")]
    assert post.queues["1.2"] == [("01:00", "03:00"), ("15:00", "17:00"), ("23:00", "24:00")]


def test_updated_post_wins_for_its_date() -> None:
    original, updated = _post(POST_6), _post(POST_6_UPDATED)
    assert original is not None and updated is not None
    assert updated.is_update
    assert original.queues["1.1"] == [("15:00", "17:00")]
    assert updated.queues["1.1"] == [("15:00", "17:00"), ("22:00", "24:00")]
    latest = latest_per_date([updated, original])
    assert latest[date(2026, 10, 6)] is updated
    latest = latest_per_date([original, updated])
    assert latest[date(2026, 10, 6)] is updated


def test_non_schedule_post_is_ignored() -> None:
    data = load_fixture("news_post_gop.json")["data"]
    assert (
        parse_schedule_post(
            slug=data["slug"],
            title=data["title"],
            content=data["content"],
            published_at=parse_published_at(data["publishedAt"], KYIV),
        )
        is None
    )


def test_schedule_outages_for_queue() -> None:
    post = _post(POST_7)
    assert post is not None
    outages = schedule_outages({post.schedule_date: post}, "4.1", KYIV)
    assert [(o.start, o.end) for o in outages] == [
        (datetime(2026, 10, 7, 9, tzinfo=KYIV), datetime(2026, 10, 7, 11, tzinfo=KYIV)),
        (datetime(2026, 10, 7, 19, tzinfo=KYIV), datetime(2026, 10, 7, 21, tzinfo=KYIV)),
    ]
    assert all(o.kind == KIND_GPV and o.summary == "ГПВ 4.1" for o in outages)


def test_24_00_ends_at_next_midnight() -> None:
    post = _post(POST_7)
    assert post is not None
    outages = schedule_outages({post.schedule_date: post}, "1.1", KYIV)
    assert outages[-1].end == datetime(2026, 10, 8, 0, 0, tzinfo=KYIV)


def test_windows_across_days_merge() -> None:
    """23:00-24:00 on one day and 00:00-01:00 the next are one outage."""
    day1 = SchedulePost(
        "a",
        "x на 1 жовтня",
        date(2026, 10, 1),
        datetime(2026, 9, 30, 19, tzinfo=KYIV),
        False,
        False,
        {"5.1": [("23:00", "24:00")]},
    )
    day2 = SchedulePost(
        "b",
        "x на 2 жовтня",
        date(2026, 10, 2),
        datetime(2026, 10, 1, 19, tzinfo=KYIV),
        False,
        False,
        {"5.1": [("00:00", "01:00")]},
    )
    outages = schedule_outages({day1.schedule_date: day1, day2.schedule_date: day2}, "5.1", KYIV)
    assert len(outages) == 1
    assert outages[0].start == datetime(2026, 10, 1, 23, tzinfo=KYIV)
    assert outages[0].end == datetime(2026, 10, 2, 1, tzinfo=KYIV)


def test_unknown_queue_has_no_outages() -> None:
    post = _post(POST_7)
    assert post is not None
    assert schedule_outages({post.schedule_date: post}, "9.9", KYIV) == []


def test_dst_end_day_uses_correct_offsets() -> None:
    """25 Oct 2026 is the DST switch: times stay wall-clock Kyiv time."""
    post = SchedulePost(
        "s",
        "t",
        date(2026, 10, 25),
        datetime(2026, 10, 24, 19, tzinfo=KYIV),
        False,
        False,
        {"4.1": [("01:00", "05:00")]},
    )
    (outage,) = schedule_outages({post.schedule_date: post}, "4.1", KYIV)
    assert outage.start.utcoffset() == timedelta(hours=3)
    assert outage.end.utcoffset() == timedelta(hours=2)


def test_year_inferred_across_new_year() -> None:
    post = parse_schedule_post(
        slug="s",
        title="Графік погодинних відключень (ГПВ) на 1 січня",
        content="<p>4.1 08:00 - 10:00</p>",
        published_at=datetime(2026, 12, 31, 19, tzinfo=KYIV),
    )
    assert post is not None
    assert post.schedule_date == date(2027, 1, 1)


def test_cancellation_post() -> None:
    post = parse_schedule_post(
        slug="s",
        title="Графік погодинних відключень (ГПВ) на 8 жовтня",
        content="<p>8 жовтня графіки погодинних відключень застосовуватися не будуть.</p>",
        published_at=datetime(2026, 10, 7, 20, tzinfo=KYIV),
    )
    assert post is not None
    assert post.cancelled
    assert post.queues == {}
    assert date(2026, 10, 8) in latest_per_date([post])


def test_post_without_queue_lines_is_not_usable() -> None:
    post = parse_schedule_post(
        slug="s",
        title="Графік погодинних відключень (ГПВ) на 8 жовтня",
        content="<p>Графік буде опубліковано пізніше.</p>",
        published_at=datetime(2026, 10, 7, 20, tzinfo=KYIV),
    )
    assert post is not None
    assert not post.cancelled
    assert latest_per_date([post]) == {}


def test_queue_lines_variants() -> None:
    text = "4.1: 09.00-11.00; 19:00 – 21:00\n4.2 — 10:00—12:00\n06.10.2026 not a queue\n5.1"
    assert parse_queue_lines(text) == {
        "4.1": [("09:00", "11:00"), ("19:00", "21:00")],
        "4.2": [("10:00", "12:00")],
        "5.1": [],
    }


def test_html_to_text() -> None:
    assert html_to_text("<p>4.1&nbsp;<span>09</span><span>:00 - 11:00</span></p><p>x</p>") == (
        "4.1 09:00 - 11:00\nx"
    )


# -- cabinet API -----------------------------------------------------------------


def test_as_list_handles_objects_keyed_by_index() -> None:
    assert as_list({"0": {"a": 1}, "1": {"a": 2}}) == [{"a": 1}, {"a": 2}]
    assert as_list([1]) == [1]
    assert as_list(None) == []
    assert as_list("x") == []


def test_parse_cabinet_time() -> None:
    assert parse_cabinet_time("10:18 06.10.2026", KYIV) == (
        datetime(2026, 10, 6, 10, 18, tzinfo=KYIV),
        False,
    )
    assert parse_cabinet_time("16:00 08.10.2026 (план)", KYIV) == (
        datetime(2026, 10, 8, 16, tzinfo=KYIV),
        True,
    )
    assert parse_cabinet_time("", KYIV) == (None, False)
    assert parse_cabinet_time("garbage", KYIV) == (None, False)


def test_queue_info_for_account() -> None:
    queue = parse_queue_info(load_fixture("cabinet_account_queue.json")["DISCONN_QUEUQ"])
    assert queue.gpv == "4.1"
    assert queue.gav == "3"
    assert len(queue.raw) == 2


def test_queue_info_unknown_account() -> None:
    queue = parse_queue_info(load_fixture("cabinet_account_unknown.json")["DISCONN_QUEUQ"])
    assert queue.gpv is None and queue.gav is None and queue.raw == ()


def test_queue_info_ignores_special_emergency_schedule() -> None:
    queue = parse_queue_info(
        [
            {"QUEUE_INFO": "Графік спеціальних аварійних відключень - 1 черга"},
            {"QUEUE_INFO": "Графік аварійних відключень - 2 черга"},
        ]
    )
    assert queue.gav == "2"


@pytest.mark.parametrize(
    ("fixture", "kind"),
    [
        ("cabinet_dept_selector0.json", KIND_PLANNED),
        ("cabinet_dept_selector1.json", KIND_EMERGENCY),
        ("cabinet_dept_selector2.json", KIND_GPV),
    ],
)
def test_parse_disconnections(fixture: str, kind: str) -> None:
    raw = load_fixture(fixture)["DISCONNECTIONS"]
    outages = parse_disconnections(raw, kind, KYIV)
    assert len(outages) == len(raw)
    for outage, item in zip(outages, raw, strict=True):
        assert outage.kind == kind
        assert outage.summary == item["DISCONN_TYPE"]
        assert outage.status == item["STATE_CHAR"]
        assert outage.end > outage.start
        assert outage.end_is_estimate == ("(план)" in item["DATE_STOP"])
        assert "<" not in outage.description


def test_parse_disconnections_skips_bad_rows() -> None:
    raw = {
        "0": {
            "DISCONN_TYPE": "Планові",
            "DATE_START": "09:00 08.10.2026",
            "DATE_STOP": "16:00 08.10.2026",
        },
        "1": {"DISCONN_TYPE": "Планові", "DATE_START": "", "DATE_STOP": "16:00 08.10.2026"},
        "2": {
            "DISCONN_TYPE": "Планові",
            "DATE_START": "17:00 08.10.2026",
            "DATE_STOP": "16:00 08.10.2026",
        },
        "3": "junk",
    }
    assert len(parse_disconnections(raw, KIND_PLANNED, KYIV)) == 1


def test_empty_account_response() -> None:
    assert (
        parse_disconnections(
            load_fixture("cabinet_account_planned_empty.json")["DISCONNECTIONS"], KIND_PLANNED, KYIV
        )
        == []
    )


# -- merging -------------------------------------------------------------------------


def _o(kind: str, start: int, end: int, summary: str = "s") -> Outage:
    base = datetime(2026, 10, 7, tzinfo=KYIV)
    return Outage(kind, base + timedelta(hours=start), base + timedelta(hours=end), summary)


def test_merge_outages() -> None:
    merged = merge_outages(
        [
            _o(KIND_GPV, 9, 11),
            _o(KIND_GPV, 9, 11),  # duplicate
            _o(KIND_GPV, 11, 12),  # adjacent
            _o(KIND_GPV, 10, 11),  # contained
            _o(KIND_PLANNED, 10, 14),  # other kind overlaps: kept separate
            _o(KIND_GPV, 19, 21),
        ]
    )
    assert [(o.kind, o.start.hour, o.end.hour) for o in merged] == [
        (KIND_GPV, 9, 12),
        (KIND_PLANNED, 10, 14),
        (KIND_GPV, 19, 21),
    ]
