## MODIFIED Requirements

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
