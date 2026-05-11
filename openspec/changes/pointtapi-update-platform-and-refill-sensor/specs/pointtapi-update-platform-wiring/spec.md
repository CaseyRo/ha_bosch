## ADDED Requirements

### Requirement: POINTTAPI update platform creates entities

The integration SHALL wire `custom_components/bosch/update.py:async_setup_entry` so that for config entries with `CONF_PROTOCOL == POINTTAPI` it creates one `BoschPoinTTAPIUpdateEntity` per description in `POINTTAPI_UPDATE_DESCRIPTIONS` and forwards them to `async_add_entities`. For XMPP/HTTP entries the platform SHALL be a no-op (`async_add_entities([])`).

#### Scenario: POINTTAPI entry registration

- **WHEN** Home Assistant sets up the `update` platform for a POINTTAPI entry
- **THEN** every description in `POINTTAPI_UPDATE_DESCRIPTIONS` SHALL result in an entity registered with `platform=bosch` and the entity appears in HA's Updates panel

#### Scenario: XMPP/HTTP entry registration

- **WHEN** the `update` platform is set up for an XMPP/HTTP entry
- **THEN** no entities SHALL be created — the platform short-circuits without error

### Requirement: Table-driven update descriptions

The integration SHALL provide a frozen dataclass `BoschPoinTTAPIUpdateEntityDescription` (extending `UpdateEntityDescription`) with optional `installed_version_fn` and `latest_version_fn` callables. Adding a new Update entity SHALL require only one description entry + a translation key.

#### Scenario: Future Update entity

- **WHEN** a developer appends a new description to `POINTTAPI_UPDATE_DESCRIPTIONS` with `installed_version_fn` and `latest_version_fn` reading from existing coordinator paths
- **THEN** after restart, HA SHALL register the new `update.*` entity with no other code changes
