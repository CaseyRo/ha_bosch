## Purpose

Wire the Home Assistant `binary_sensor` platform for the POINTTAPI (EasyControl cloud) protocol path. Establishes the table-driven entity description pattern, a default `"on"`/`"off"` string-to-bool resolver, and the per-entity `value_fn` escape hatch. Pre-requisite for any POINTTAPI binary sensor — including those introduced in `pointtapi-dhw-detail` and `pointtapi-burner-state`.

## Requirements

### Requirement: POINTTAPI binary-sensor platform creates entities

The `binary_sensor` platform's `async_setup_entry` SHALL, for config entries whose `CONF_PROTOCOL == POINTTAPI`, create one entity per description returned by `_pointtapi_binary_sensor_descriptions()` and forward them to `async_add_entities`. The platform SHALL NOT short-circuit POINTTAPI entries with an empty list.

#### Scenario: Setup creates binary sensors for POINTTAPI

- **WHEN** Home Assistant sets up the `binary_sensor` platform for a POINTTAPI config entry
- **THEN** `async_add_entities` SHALL receive one `BoschPoinTTAPIBinarySensorEntity` per description and those entities SHALL appear in HA's entity registry under `platform=bosch`

#### Scenario: Setup creates no binary sensors for non-POINTTAPI

- **WHEN** Home Assistant sets up the `binary_sensor` platform for an XMPP/HTTP config entry
- **THEN** behavior SHALL match the prior implementation (no regression to the dispatcher-based path used by legacy gateways)

### Requirement: Binary-sensor descriptions are table-driven

The integration SHALL provide a frozen dataclass `BoschPoinTTAPIBinarySensorEntityDescription` extending `BinarySensorEntityDescription` with an optional `value_fn: Callable[[dict], bool | None] | None = None` field. Adding a new POINTTAPI binary sensor SHALL require only appending one description to `_pointtapi_binary_sensor_descriptions()` plus a translation key entry — no new entity class.

#### Scenario: Adding a future binary sensor

- **WHEN** a developer adds a new `BoschPoinTTAPIBinarySensorEntityDescription` entry for a path already polled by the coordinator
- **THEN** after restart, HA SHALL register the corresponding `binary_sensor.pointtapi_*` entity with no additional class or platform code

### Requirement: Default boolean resolver maps "on"/"off" AND "true"/"false" strings to bool

For descriptions WITHOUT a `value_fn`, the entity's `is_on` property SHALL resolve as follows from `coordinator.data[description.key]["value"]`:
- `True` if the trimmed, lower-cased value is one of `{"on", "true"}`
- `False` if the trimmed, lower-cased value is one of `{"off", "false"}`
- `None` (HA shows "unknown") for any other value, including `null`, numeric types, and unrecognized strings

This generalization covers both API dialects observed in POINTTAPI responses: `/dhwCircuits/dhw1/state` and `/heatSources/flameIndication` report `"on"`/`"off"`, while `/heatSources/refillNeeded` reports `"true"`/`"false"`. Centralizing both forms in the resolver means new binary sensors picking up either dialect work without a per-entity `value_fn`.

#### Scenario: Lower-case on/off

- **WHEN** the value is `"on"` or `"off"`
- **THEN** `is_on` SHALL be `True` / `False` respectively

#### Scenario: Lower-case true/false

- **WHEN** the value is `"true"` or `"false"`
- **THEN** `is_on` SHALL be `True` / `False` respectively

#### Scenario: Mixed case (either dialect)

- **WHEN** the value is `"On"`, `"OFF"`, `" on "`, `"TRUE"`, or `" false "` (surrounding whitespace, any case)
- **THEN** `is_on` SHALL still resolve correctly after trim + lower-case

#### Scenario: Unknown or malformed value

- **WHEN** the value is `None`, an integer, or a string not in `{"on","off","true","false"}` after normalization
- **THEN** `is_on` SHALL be `None` so HA renders the entity as `unknown`

### Requirement: Entity descriptions with explicit value_fn override the default

When a description provides a `value_fn`, it SHALL take precedence over the default on/off string resolver and the function's return value SHALL be used directly.

#### Scenario: Custom resolver supplied

- **WHEN** a description has `value_fn=lambda data: data["/some/path"]["value"] > 0`
- **THEN** the binary sensor's `is_on` SHALL be the boolean returned by that function, with `None` treated as `unknown`
