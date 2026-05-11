## Purpose

Expose the domestic-hot-water tank's actual temperature and active-heating state as Home Assistant entities, beyond the mode-only `water_heater.hot_water_tank` entity. Both new entities live on the Hot Water Tank device alongside the water heater and thermal-disinfect switch.

## Requirements

### Requirement: Hot water tank actual temperature sensor

The integration SHALL expose `sensor.hot_water_tank_actual_temperature` for POINTTAPI config entries, reporting the current value of `/dhwCircuits/dhw1/actualTemp` from the coordinator payload in degrees Celsius, with `device_class=TEMPERATURE` and `state_class=MEASUREMENT`.

#### Scenario: Tank temperature available in coordinator data

- **WHEN** the coordinator's most recent poll contains `/dhwCircuits/dhw1/actualTemp` with a numeric `value` (e.g. `32.0`)
- **THEN** the sensor's state SHALL be that numeric value in °C and its `last_updated` SHALL be the time of that poll

#### Scenario: Tank temperature missing from coordinator data

- **WHEN** the path `/dhwCircuits/dhw1/actualTemp` is absent from the coordinator payload (e.g. a transient 403 on that ref)
- **THEN** the sensor's state SHALL be reported as `unknown` rather than a stale value, and SHALL recover automatically on the next poll that contains the path

### Requirement: Hot water active-heating binary sensor

The integration SHALL expose `binary_sensor.hot_water_tank_heating` for POINTTAPI config entries, reflecting whether `/dhwCircuits/dhw1/state` is currently `"on"`. The entity SHALL have `device_class=HEAT` so HA's UI labels it as a heat-application indicator (not water flow).

#### Scenario: Tank actively heating

- **WHEN** the coordinator payload reports `/dhwCircuits/dhw1/state.value == "on"`
- **THEN** the binary sensor SHALL be `on`

#### Scenario: Tank idle

- **WHEN** the coordinator payload reports `/dhwCircuits/dhw1/state.value == "off"`
- **THEN** the binary sensor SHALL be `off`

#### Scenario: Unrecognized state value

- **WHEN** the coordinator payload reports `/dhwCircuits/dhw1/state.value` as anything other than `"on"` or `"off"` (case-insensitive, after trim) — for example `null`, a localized string, or a numeric value
- **THEN** the binary sensor SHALL report `unknown` (not fabricate `False`), and SHALL recover automatically when the value returns to a recognized form

### Requirement: DHW entities attach to the Hot Water Tank device

Both new DHW entities, the existing `water_heater.hot_water_tank` entity, and the `switch.hot_water_tank_thermal_disinfect` switch SHALL all be attached to a dedicated "Hot Water Tank" device with identifier `(DOMAIN, f"{uuid}_dhw1")` and `via_device=(DOMAIN, uuid)` so HA renders them as a child of the EasyControl Gateway.

#### Scenario: Device association

- **WHEN** HA's device registry is inspected for the POINTTAPI config entry
- **THEN** `sensor.hot_water_tank_actual_temperature`, `binary_sensor.hot_water_tank_heating`, `water_heater.hot_water_tank`, and `switch.hot_water_tank_thermal_disinfect` SHALL all list `identifiers={(DOMAIN, f"{uuid}_dhw1")}` matching the Hot Water Tank device, and that device SHALL have `via_device=(DOMAIN, uuid)`
