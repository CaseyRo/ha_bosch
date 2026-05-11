## Purpose

Expose the boiler's refill-needed maintenance signal (`/heatSources/refillNeeded`) as a `device_class=PROBLEM` binary sensor on the Boiler device. Lets users wire a notification automation before the boiler hard-faults on low pressure.

## Requirements

### Requirement: Refill-needed binary sensor

The integration SHALL expose `binary_sensor.boiler_refill_needed` for POINTTAPI config entries, reflecting whether `/heatSources/refillNeeded` is currently `"true"`. The entity SHALL have `device_class=PROBLEM` so HA renders it red while the condition holds.

#### Scenario: Boiler reports refill needed

- **WHEN** the coordinator payload reports `/heatSources/refillNeeded.value == "true"`
- **THEN** the binary sensor SHALL be `on` (PROBLEM device class — HA shows red)

#### Scenario: Boiler reports normal pressure

- **WHEN** the coordinator payload reports `/heatSources/refillNeeded.value == "false"`
- **THEN** the binary sensor SHALL be `off`

#### Scenario: Value missing or unrecognized

- **WHEN** the path is absent OR `value` is anything other than `"true"`/`"false"` (case-insensitive after trim)
- **THEN** the binary sensor SHALL be `unknown` and SHALL recover automatically on the next recognized poll

### Requirement: Refill-needed entity attaches to the Boiler device

The entity SHALL be attached to the Boiler device `(DOMAIN, f"{uuid}_boiler")` so it sits alongside the other boiler-state entities (flame, ignition starts, errors).

#### Scenario: Device association

- **WHEN** HA's device registry is inspected
- **THEN** `binary_sensor.boiler_refill_needed`'s `identifiers` SHALL include `(DOMAIN, f"{uuid}_boiler")` matching the Boiler device
