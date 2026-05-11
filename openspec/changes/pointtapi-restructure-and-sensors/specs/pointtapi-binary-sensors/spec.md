## ADDED Requirements

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

### Requirement: Default boolean resolver maps "on"/"off" strings to bool

For descriptions WITHOUT a `value_fn`, the entity's `is_on` property SHALL resolve as follows from `coordinator.data[description.key]["value"]`:
- `True` if the trimmed, lower-cased value equals `"on"`
- `False` if the trimmed, lower-cased value equals `"off"`
- `None` (HA shows "unknown") for any other value, including `null`, numeric types, and unrecognized strings

#### Scenario: Lower-case on/off

- **WHEN** the value is `"on"` or `"off"`
- **THEN** `is_on` SHALL be `True` / `False` respectively

#### Scenario: Mixed case

- **WHEN** the value is `"On"`, `"OFF"`, or `" on "` (surrounding whitespace)
- **THEN** `is_on` SHALL still resolve correctly after trim + lower-case

#### Scenario: Unknown or malformed value

- **WHEN** the value is `None`, an integer, or a string not in `{"on","off"}` after normalization
- **THEN** `is_on` SHALL be `None` so HA renders the entity as `unknown`

### Requirement: Entity descriptions with explicit value_fn override the default

When a description provides a `value_fn`, it SHALL take precedence over the default on/off string resolver and the function's return value SHALL be used directly.

#### Scenario: Custom resolver supplied

- **WHEN** a description has `value_fn=lambda data: data["/some/path"]["value"] > 0`
- **THEN** the binary sensor's `is_on` SHALL be the boolean returned by that function, with `None` treated as `unknown`
