## ADDED Requirements

### Requirement: Burner flame binary sensor

The integration SHALL expose `binary_sensor.boiler_flame` for POINTTAPI config entries, reflecting whether `/heatSources/flameIndication` is currently `"on"`. The entity SHALL have `device_class=RUNNING`.

#### Scenario: Flame on

- **WHEN** the coordinator payload reports `/heatSources/flameIndication.value == "on"`
- **THEN** the binary sensor SHALL be `on`

#### Scenario: Flame off

- **WHEN** the coordinator payload reports `/heatSources/flameIndication.value == "off"`
- **THEN** the binary sensor SHALL be `off`

#### Scenario: Flame value missing or unrecognized

- **WHEN** the path is absent from the payload OR `value` is anything other than `"on"`/`"off"` (case-insensitive after trim)
- **THEN** the binary sensor SHALL be `unknown` and SHALL recover automatically on the next poll with a recognized value

### Requirement: Lifetime ignition starts sensor

The integration SHALL expose `sensor.boiler_ignition_starts` for POINTTAPI config entries, reporting the value of `/heatSources/numberOfStarts` as a monotonically-increasing counter with `state_class=TOTAL_INCREASING` and no `device_class` or unit (the API reports `unit==""`).

#### Scenario: Counter increases between polls

- **WHEN** two successive coordinator polls report a higher `numberOfStarts` (e.g. `14636` → `14637`)
- **THEN** the sensor's state SHALL update accordingly and HA's Long-Term Statistics SHALL record the increase as a positive delta

#### Scenario: Counter resets (boiler service / replacement)

- **WHEN** a poll reports a `numberOfStarts` value lower than the previously-recorded state (e.g. board replacement resets to 0)
- **THEN** the sensor SHALL accept the new value as-is and HA's Long-Term Statistics SHALL begin a new accumulation cycle (HA's native TOTAL_INCREASING semantics)

#### Scenario: Counter missing from payload

- **WHEN** the path `/heatSources/numberOfStarts` is absent from the coordinator payload
- **THEN** the sensor's state SHALL be `unknown` and the previously-recorded long-term-statistics total SHALL NOT be invalidated

### Requirement: Burner entities attach to the Boiler device

Both new burner-state entities SHALL be attached to a dedicated "Boiler" device with identifier `(DOMAIN, f"{uuid}_boiler")` and `via_device=(DOMAIN, uuid)`. The same Boiler device SHALL also host all other boiler-related entities (actual supply temperature, modulation, power setpoint, system pressure, blocking/locking/maintenance errors, display/cause code, and gas usage sensors).

#### Scenario: Device association

- **WHEN** HA's device registry is inspected for the POINTTAPI config entry
- **THEN** `binary_sensor.boiler_flame`, `sensor.boiler_ignition_starts`, and all other boiler-related entities SHALL list `identifiers={(DOMAIN, f"{uuid}_boiler")}` matching the Boiler device, and that device SHALL have `via_device=(DOMAIN, uuid)`
