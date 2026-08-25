## Purpose

Gives the POINTTAPI path parity with the XMPP path's notification surface: a gateway-level sensor reporting the count of active Bosch alerts, with the raw entries as an attribute for automations and bug reports.

## Requirements

### Requirement: Coordinator fetches /notifications

`/notifications` SHALL be added to the coordinator's polled path set (riding the bulk call in steady state). A missing or erroring `/notifications` resource SHALL be tolerated exactly like other optional paths — skipped with a debug log, never failing the refresh.

#### Scenario: Notifications unavailable on a given firmware

- **WHEN** `/notifications` returns 404 for a device
- **THEN** the refresh SHALL complete normally and the notifications sensor SHALL report `unavailable`

### Requirement: Notifications sensor exposes count and entries

A sensor on the EasyControl Gateway device SHALL expose the active notification count as its state, with the raw notification entries (e.g. dcd/ccd codes, timestamps) as the `notifications` extra state attribute. The entry list SHALL be read from the response's `values` key, falling back to `value` — the live CT200 returns `value` (type `errorList`, per `boost-probe-notes.md`) while homecom_alt observed `values` on the cloud route. With zero active notifications the state SHALL be `0` and the attribute an empty list. This gives the POINTTAPI path parity with the XMPP path's `NotificationSensor`.

#### Scenario: No active alerts

- **WHEN** `/notifications` returns `{"value": []}` (or `{"values": []}`)
- **THEN** the sensor state SHALL be `0` and `extra_state_attributes["notifications"]` SHALL be `[]`

#### Scenario: One active alert

- **WHEN** `/notifications` returns one entry in `values`
- **THEN** the sensor state SHALL be `1` and the entry SHALL appear verbatim in the `notifications` attribute

#### Scenario: Routed to the Gateway device

- **WHEN** the notifications sensor is constructed
- **THEN** its `device_info.identifiers` SHALL be `(DOMAIN, uuid)` per the `pointtapi-device-partition` gateway catch-all
