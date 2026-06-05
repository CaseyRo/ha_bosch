## ADDED Requirements

### Requirement: Away mode switch

A switch entity on the EasyControl Gateway device SHALL read `/system/awayMode/enabled` (string `"true"`/`"false"` per the CT200 dump in bosch-homecom-hass#78) and PUT the toggled string value on turn-on/turn-off, followed by a coordinator refresh request. The entity SHALL be unavailable when the path is absent from coordinator data.

#### Scenario: Enable away mode

- **WHEN** the user turns the away-mode switch on
- **THEN** the integration SHALL PUT `/system/awayMode/enabled = "true"` and request a refresh; the switch reports `on` once coordinator data confirms `"true"`

### Requirement: Extra hot water switch and duration

A switch on the Hot Water Tank device SHALL read `/dhwCircuits/dhw1/extraDhw` (`"on"`/`"off"`, `writeable: 1`) and PUT the toggled value. A number entity on the same device SHALL expose `/dhwCircuits/dhw1/extraDhwDuration` with the probe-confirmed constraints: minutes, min 15, max 2880, step 15. Both SHALL be unavailable when their paths are absent. Note: on instant hot-water systems the live device reports these resources with `available: "false"` while still serving values (probe of 2026-06-05) — entities SHALL treat present-but-`available: "false"` data as available-with-state rather than erroring, matching how existing POINTTAPI entities handle such resources.

#### Scenario: Start an extra-DHW run

- **WHEN** the user sets duration to 60 and turns the extra-DHW switch on
- **THEN** the integration SHALL PUT `extraDhwDuration = 60` (on the number set) and `extraDhw = "on"` (on the switch toggle), each followed by a refresh request

#### Scenario: Duration constraints enforced

- **WHEN** the number entity is rendered
- **THEN** HA SHALL show min 15, max 2880, step 15, unit minutes — matching the device's advertised `minValue`/`maxValue`/`stepSize`

### Requirement: Thermal disinfect configuration entities

The existing thermal-disinfect switch (`/dhwCircuits/dhw1/thermalDisinfect/state`) SHALL be complemented on the Hot Water Tank device by: a config-category number for `/dhwCircuits/dhw1/thermalDisinfect/time` (minute-of-day, min 0, max 1439, step 1), a config-category select for `/dhwCircuits/dhw1/thermalDisinfect/weekDay` (options exactly `Mo`, `Tu`, `We`, `Th`, `Fr`, `Sa`, `Su` as the API values, with translated labels), and a diagnostic-category sensor for `/dhwCircuits/dhw1/thermalDisinfect/lastResult`.

#### Scenario: Schedule disinfect for Monday 01:00

- **WHEN** the user selects weekday `Mo` and sets time to 60
- **THEN** the integration SHALL PUT `thermalDisinfect/weekDay = "Mo"` and `thermalDisinfect/time = 60`

#### Scenario: Last result surfaces

- **WHEN** coordinator data holds `thermalDisinfect/lastResult` with value `done`
- **THEN** the diagnostic sensor SHALL report `done`

### Requirement: New control writes use the established PUT-and-refresh pattern

All new writable entities SHALL follow the existing POINTTAPI write pattern: PUT via `coordinator.client`, log-and-refresh on failure (no exception surfaced to the UI beyond entity state), and re-read state from coordinator data rather than assuming the write succeeded.

#### Scenario: Write rejected by the cloud

- **WHEN** a PUT to `/system/awayMode/enabled` fails with a 4xx
- **THEN** the integration SHALL log a warning, request a refresh, and the switch SHALL continue to reflect the device-reported state (not the attempted value)
