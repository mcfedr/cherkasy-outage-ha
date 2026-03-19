# Cherkasy Outage Schedule

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Validate](https://github.com/mcfedr/cherkasy-outage-ha/actions/workflows/validate.yaml/badge.svg)](https://github.com/mcfedr/cherkasy-outage-ha/actions/workflows/validate.yaml)

A Home Assistant custom integration that monitors the **Cherkasy Oblenergo** Telegram channel for scheduled power outage times, parses the schedule for your outage group, and exposes the data as HA entities.

## What it does

- Reads the schedule from the `pat_cherkasyoblenergo` Telegram channel every 30 minutes
- Parses Ukrainian-language schedule messages for your outage group (e.g. `4.1`)
- Creates sensors for today's and tomorrow's windows, the next outage start/end times, and a binary sensor that is `on` during active outage windows

### Entities created

| Entity | Description |
|---|---|
| `sensor.outage_schedule_today` | Total scheduled outage hours today (e.g. `8.0h`) |
| `sensor.outage_schedule_tomorrow` | Total scheduled outage hours tomorrow |
| `sensor.next_outage_start` | Datetime of the next outage window start |
| `sensor.next_outage_end` | Datetime of the next outage window end |
| `sensor.schedule_last_updated` | When the schedule was last fetched |
| `binary_sensor.outage_active` | `on` while currently inside a scheduled outage window |

The schedule sensors include `windows`, `windows_formatted`, `window_count`, and `date` as attributes — useful for dashboard cards and automations.

## Why Telethon?

Cherkasy Oblenergo posts schedules to a public Telegram channel. The `t.me/s/` web view serves stale cached content to unauthenticated clients. A bot API requires channel admin access. **Telethon** (user-mode client) connects as a regular Telegram account and reliably reads any public channel — the standard approach for this use case.

You will need a free Telegram API key from [my.telegram.org](https://my.telegram.org).

## Installation

### Via HACS (recommended)

1. In HACS, click the three-dot menu → **Custom repositories**
2. Add `https://github.com/mcfedr/cherkasy-outage-ha` with category **Integration**
3. Search for **Cherkasy Outage Schedule** and install
4. Restart Home Assistant

### Manual

Copy the `custom_components/cherkasy_outage` folder into your `config/custom_components/` directory and restart Home Assistant.

## Setup

1. Go to **Settings → Integrations → Add Integration → Cherkasy Outage Schedule**
2. Enter your Telegram **API ID** and **API Hash** from [my.telegram.org](https://my.telegram.org)
3. Enter your **phone number** (international format, e.g. `+380501234567`)
4. A code will be sent to your Telegram app — enter it in the next step
5. Done. The session is saved and reused automatically on every restart.

After setup, use the **Configure** button on the integration card to change the poll interval (5–120 min) or switch outage group.

## Example automation — charge battery before outage

```yaml
automation:
  - alias: "Charge battery before outage"
    trigger:
      - platform: template
        value_template: >
          {% set next = states('sensor.next_outage_start') %}
          {% if next not in ('unavailable', 'unknown', 'none') %}
            {{ (as_datetime(next) - now()).total_seconds() < 3600 }}
          {% else %}
            false
          {% endif %}
    condition:
      - condition: numeric_state
        entity_id: sensor.inverter_battery_soc
        below: 90
    action:
      - service: select.select_option
        target:
          entity_id: select.inverter_charge_program
        data:
          option: "Grid charge max"
```

## Limitations

- **Emergency outages (ГАВ)** — unscheduled emergency cuts are not yet parsed
- **Schedule cancellations** — mid-day cancellations may not be detected
- **`binary_sensor.outage_active`** — re-evaluated only on coordinator poll (every 30 min by default); add a time-based HA automation to update at exact window boundaries if needed
