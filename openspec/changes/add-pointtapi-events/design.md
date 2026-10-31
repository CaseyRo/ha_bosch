# Design

## Context

See proposal.md. `PoinTTAPIClient.put(uri, value)` already serialises `{"value": value}`, so a list value goes out as-is; the limits are the HA service layer (`async_handle_put` rejects falsy/non-scalar values) and the lack of any events read or read-back. Probe findings: `ev1` value is a list of `{name (b64), start, end, type, id}`; `list1-3` are read-only; `ev2` is 500.

## Goals / Non-Goals

**Goals:** read events; create/delete via whole-array PUT to `ev1`; never report an unverified write.

**Non-Goals:** editing the away-mode switch; using `list1-3` or `ev2`; a calendar entity or UI card; recurring events; any upstream-ready abstraction (see convergence plan).

## Decisions

- **Events, not the away switch.** The away switch stays as is; events are the scheduled mechanism.
- **Dedicated services, not widened `send_custom_put_*`.** Typed create/delete with validation is safer than letting raw services take arbitrary arrays. Raw array PUT stays out of scope.
- **Read-modify-write on the full array**, since the device only accepts the whole array. Serialise with the coordinator's existing update lock to avoid racing a poll.
- **Read back and retry every write** (bounded, e.g. 3 attempts with a short delay); fail loudly after that.
- **Fast tier** for `/events/ev1` (not `SLOW_RESOURCE_PREFIXES`) so a write is visible within one poll.

- **Caller-owned events by id, not by name.** The service returns the created id (optional service response); the integration does not filter or enforce ownership. Callers (Node-RED) track their own ids and may match on the "Away (blippstrom)" name as a fallback. App-made events are never touched because delete takes one explicit id.

## Risks / Trade-offs

- **Read-back lag.** An event made in the Bosch app took about 10 minutes to reach the gateway, and one delete was lost across a restart. A 3-attempt "short delay" read-back may report failure on a write that lands later. Decide before implementing whether verification is against the cloud (immediate) or the gateway (slow), and whether the service waits or returns pending; the caller must retry-and-read-back either way.
- **Setpoint not in the event.** The `ev1` entries carry no temperature field; the 15 °C away setpoint is assumed to come from device away settings. Confirm in the probe, since the blippstrom flow assumes 15 °C.

- Whole-array PUT can drop events another client added between read and write; mitigated by lock plus read-back, not eliminated.
- Event `type` values and the name length limit are unconfirmed; first task is to probe them on the CT200 before fixing the service schema. Only one device (101506113) is available for probing.
- A bad array PUT could clear existing events; tests must cover that the original array is preserved on failure.

## Write spike 2026-10-31 (live, device 101506113, ev1 held one event, id 1, restored byte-identical after)

- `PUT /events/ev1` with `[existing, new]` returned **400 (empty message)** for every variant tried: new id 2 and 3, no id, non-overlapping and later dates, type `holiday`. PUT of the unchanged array returns 204.
- `POST /events` returns **400** and changes nothing.
- Unresolved: whether `ev1` is a single-slot array (a second element is always rejected) or the 400 comes from an unseen field rule. Next probe: PUT a one-element array that edits id 1 in place.
