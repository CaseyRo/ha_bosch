## ADDED Requirements

### Requirement: Firmware Update entity surfaces in HA Updates panel

The integration SHALL expose `update.easycontrol_gateway_firmware` for POINTTAPI config entries — a Home Assistant `update` platform entity whose `installed_version` reflects `/gateway/versionFirmware` and whose `latest_version` differs from `installed_version` exactly when `/gateway/update/state` is anything other than `"no update"` (case-insensitive after trim). The entity SHALL be read-only (no `INSTALL`/`SKIP` features) because the API doesn't expose a programmatic install path the integration can safely call.

#### Scenario: No update available

- **WHEN** the coordinator reports `/gateway/update/state.value == "no update"` and `/gateway/versionFirmware.value == "05.04.00"`
- **THEN** `update.easycontrol_gateway_firmware.installed_version == "05.04.00"` AND `update.easycontrol_gateway_firmware.latest_version == "05.04.00"` (HA renders as up-to-date)

#### Scenario: Update is available

- **WHEN** the coordinator reports `/gateway/update/state.value` as anything other than `"no update"` (e.g. `"available"`)
- **THEN** `latest_version` SHALL be set to a synthetic string distinct from `installed_version` (concretely `"<installed> (update available)"`) so HA's Updates panel highlights the entity

#### Scenario: State value missing

- **WHEN** `/gateway/update/state` is absent from the coordinator payload
- **THEN** the entity SHALL fall back to treating it as `"no update"` (no spurious notification), and SHALL recover automatically on the next poll containing the path

#### Scenario: Read-only install

- **WHEN** an automation or the HA UI invokes the entity's install action
- **THEN** the action SHALL be unavailable (no-op) — `supported_features` excludes `INSTALL` and `SKIP`

### Requirement: Update entity attaches to the Gateway device

The Update entity SHALL be attached to the EasyControl Gateway device `(DOMAIN, uuid)` so it appears under the gateway in HA's Devices & Services page.

#### Scenario: Device association

- **WHEN** HA's device registry is inspected
- **THEN** `update.easycontrol_gateway_firmware`'s `identifiers` SHALL include `(DOMAIN, uuid)` matching the Gateway device

### Requirement: Last-check and last-update timestamp sensors

The integration SHALL expose `sensor.easycontrol_gateway_last_update_check` and `sensor.easycontrol_gateway_last_update_applied` for POINTTAPI config entries, both with `device_class=TIMESTAMP` and `entity_category=DIAGNOSTIC`, deriving their values from `/gateway/update/lastCheck` and `/gateway/update/lastUpdate`. The API appends a 2-letter English weekday (e.g. `"2026-05-11T01:02:00+02:00 Mo"`); the sensor's `value_fn` SHALL strip that tail before parsing with `datetime.fromisoformat`.

#### Scenario: Well-formed timestamp with weekday tail

- **WHEN** the coordinator reports `/gateway/update/lastCheck.value == "2026-05-11T01:02:00+02:00 Mo"`
- **THEN** the sensor's state SHALL be a `datetime` for `2026-05-11T01:02:00+02:00`

#### Scenario: Malformed or missing timestamp

- **WHEN** the value can't be parsed (unexpected format, missing path, etc.)
- **THEN** the sensor's state SHALL be `unknown` and SHALL recover automatically when the value becomes parseable again
