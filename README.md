# Cherkasy Outage Schedule

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/mcfedr/cherkasy-outage-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/mcfedr/cherkasy-outage-ha/actions/workflows/validate.yml)

Home Assistant integration for **Cherkasyoblenergo** power outages. For one personal
account (особовий рахунок) it shows the hourly outage schedule (ГПВ) for the account's
queue, plus planned and emergency works, as a calendar and sensors you can automate on.

No credentials, no Telegram: it reads two public Cherkasyoblenergo APIs.

| Source | Used for | Polled |
|---|---|---|
| `www.cherkasyoblenergo.com/api/v1/posts` (news) | ГПВ schedule by queue: "Графік погодинних відключень (ГПВ) на …" and "Оновлено графік …" posts | every 10 min |
| `cabinet.cherkasyoblenergo.com/api_new/disconn.php` | the account's ГПВ and ГАВ queues; planned and emergency works for the next 7 days | every 30 min |

The cabinet API also has a "schedules" selector, but it does not return ГПВ windows for
Cherkasy city accounts, which is why the schedule comes from the news posts.

## Installation

HACS → ⋮ → **Custom repositories** → add `https://github.com/mcfedr/cherkasy-outage-ha`
(category **Integration**) → install **Cherkasy Outage Schedule** → restart Home Assistant.

Or copy `custom_components/cherkasy_outage` into your `config/custom_components/`.

## Setup

**Settings → Devices & services → Add integration → Cherkasy Outage Schedule**, then either:

- **Find by address**: branch → settlement → street → building → account, or
- **Enter account number**.

The ГПВ queue is detected from the account. If Cherkasyoblenergo reports none, you are asked
for it. **Configure** on the integration lets you override the queue (or set it back to
`auto`). The account number lives only in the config entry.

## Entities

Entity IDs assume the default device name, *Power outages*.

| Entity | State |
|---|---|
| `calendar.power_outages` | ГПВ windows for your queue, plus planned (`Планові`) and emergency (`Аварійні`) works |
| `binary_sensor.power_outages_scheduled_now` | `on` while inside any outage window (the schedule, not the grid; use your inverter or a grid sensor for that) |
| `sensor.power_outages_next_start` | start of the next window that hasn't begun |
| `sensor.power_outages_next_end` | end of the current window, or of the next one if none is active |
| `sensor.power_outages_today` / `_tomorrow` | e.g. `09:00–11:00, 19:00–21:00`; `none` when published with no outages for your queue; `unknown` until published. Attributes: `windows`, `hours`, `title`, `published_at`, `is_update` |
| `sensor.power_outages_queue` | ГПВ queue in use, e.g. `4.1` (`source`: `api`, `override` or `setup`) |
| `sensor.power_outages_emergency_queue` | ГАВ queue, e.g. `3` |
| `sensor.power_outages_schedule_published` | when the newest schedule post was published (diagnostic) |

States flip exactly at window boundaries, not at the next poll. If an API fails, the last
good data is kept for 3 polls before entities go unavailable.

### Event: `cherkasy_outage_schedule_changed`

Fired when your queue's windows for a date appear or change. That happens when tomorrow's
schedule is published, usually in the evening, and whenever an "Оновлено" correction
changes your queue. It does not fire on start-up.

```yaml
event_data:
  entry_id: …
  queue: "4.1"
  date: "2026-10-07"
  windows:
    - { start: "2026-10-07T09:00:00+03:00", end: "2026-10-07T11:00:00+03:00" }
  cancelled: false
  is_update: false
  first_publication: true
  title: "Графік погодинних відключень (ГПВ) на 7 жовтня"
  published_at: "2026-10-06T19:30:00+03:00"
```

Example: notify on every change.

```yaml
triggers:
  - trigger: event
    event_type: cherkasy_outage_schedule_changed
actions:
  - action: notify.send_message
    target:
      entity_id: notify.me
    data:
      message: >-
        ГПВ {{ trigger.event.data.queue }} on {{ trigger.event.data.date }}:
        {% for w in trigger.event.data.windows %}{{ as_datetime(w.start).strftime('%H:%M') }}–{{ as_datetime(w.end).strftime('%H:%M') }} {% else %}no outages{% endfor %}
```

## Notes

- `cabinet.cherkasyoblenergo.com` serves an incomplete TLS certificate chain. The
  integration ships the missing Sectigo intermediate and adds it to the trust store for
  that host. Verification is never turned off.
- The APIs are undocumented and may change. If a schedule post can't be read, a Repairs
  issue names the post.
- The APIs may only answer from Ukrainian networks.
- Unannounced emergency cuts only appear once Cherkasyoblenergo publishes them.

## Development

```bash
uv venv -p 3.14 && uv pip install pytest pytest-asyncio aiohttp certifi ruff
pytest                       # parser + API client, against recorded responses in tests/fixtures
ruff check . && ruff format --check .

uv venv -p 3.14 .venv-ha && uv pip install -p .venv-ha -r requirements_test_ha.txt
.venv-ha/bin/pytest tests_ha # config flow + entities inside a real HA core

CHERKASY_LIVE=1 CHERKASY_ACCOUNT=<account> pytest -k live   # hits the real APIs
```

CI runs HACS validation, hassfest, ruff and both test suites. Every push to `main` bumps the
patch version in `manifest.json`, tags it and creates a GitHub release for HACS.
