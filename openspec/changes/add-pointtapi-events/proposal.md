# Proposal

## Why

The CT200 models time-limited overrides (holiday / away periods) as *events*, not as the `/system/awayMode/enabled` switch. The blippstrom Node-RED presence flow (nr-blippstrom-v2, `bosch-away-flow`, design D9) needs to schedule an away period from Home Assistant. Probes 2026-10-30..11-03 showed each `evN` slot holds exactly one event, the slot is fully editable by a one-element PUT, a slot exists only while it holds an event, and no route to create a slot is known (`PUT /events/ev2` 404, `POST /events` 400).

## What Changes

Standing-slot model (Casey, 2026-11-03): `/events/ev1` stays forever as `Away (blippstrom)`, parked at `2099-12-30..2099-12-31`. Node-RED moves it to the trip dates and parks it again on return. Nothing creates or deletes a slot.

- Add service `bosch.set_away_event` (`device_id`, `name`, `start`, `end`; dates `YYYY-MM-DD`). It reads `ev1`, PUTs a one-element array (id kept) under the gateway update lock, reads back with bounded retry, and returns `{name, start, end, verified}` as an optional service response.
- Validates `start <= end` and name length; raises on read-back mismatch or if `ev1` is missing.
- Names are base64 on the wire; the service encodes/decodes them.

## Capabilities

### New Capabilities
- `pointtapi-events`: moving the standing away event on the EasyControl via `/events/ev1`, with verified writes.

### Modified Capabilities
<!-- none -->

## Impact

`__init__.py` (`set_away_event`), `services.py` / `services.yaml` / `const.py`, tests, CHANGELOG. Follow-ups, not blockers: events sensor, diagnostics redaction of event names, app capture for slot creation.
