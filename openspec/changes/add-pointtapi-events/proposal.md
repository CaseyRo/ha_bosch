# Proposal

## Why

The CT200 models time-limited overrides (holiday / away periods) as *events*, not as the `/system/awayMode/enabled` switch. Probe of 2026-10-30: `/events/ev1` is the one writable `eventArray`; `list1`–`list3` are read-only views of it; `/events/ev2` returns 500. The integration cannot read or create events today, and `send_custom_put_*` only sends scalars, so an array PUT is impossible without a client change.

The first consumer is the blippstrom Node-RED presence flow (nr-blippstrom-v2): when both phones are away it offers an away period, creates an event named "Away (blippstrom)" (type away, end = last away day inclusive = return date minus 2 days, so the house is warm on return), and later deletes only the events it created. App-made events must stay untouched. It triggers on phone occupancy, never `house_mode`.

## What Changes

- Read `/events/ev1` into coordinator data and expose the entries (name, start, end, type, id) on a sensor.
- Add a PUT path that sends a list value to `/events/ev1` (the existing `put()` already JSON-wraps `value`; the gap is the service/entry layer, which only passes scalars).
- Add services to create and delete an event slot. Each is read-modify-write on the whole array, with the write read back and retried until the device reflects it.
- Names are base64 on the wire; the integration encodes/decodes them.
- Create returns the new event id as a service response, so a caller can later delete exactly what it created; delete only ever removes the id given.
- The existing away-mode switch is unchanged and stays the instant on/off control.

## Capabilities

### New Capabilities
- `pointtapi-events`: reading the event array and creating/deleting events on the EasyControl via `/events/ev1`, with verified writes.

### Modified Capabilities
<!-- none: away-mode switch requirements are untouched -->

## Impact

- `pointtapi_client.py` (array-valued PUT is already possible; add read-back helper), `pointtapi_coordinator.py` (fast-tier read of `/events/ev1`, skip `list1-3` and `ev2`), `pointtapi_entities.py` (events sensor), `services.py` / `services.yaml` / translations (create/delete services), `diagnostics.py` (redact event names: they may carry household names, cf. #78 auto-away redaction).
- Staging code per `docs/convergence-plan.md`: keep the change small, no new abstractions upstream would have to unpick.
