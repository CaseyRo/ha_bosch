## ADDED Requirements

### Requirement: One-shot entity-ID migration via async_migrate_entry

The integration SHALL implement `async_migrate_entry` that runs once per config entry on HA startup, detects the legacy entity_ids from v0.30.x and earlier, and rewrites them to the new entity_ids defined by the v0.31.0 device-partition restructure. The function SHALL be idempotent — running it on an already-migrated entry SHALL be a no-op.

#### Scenario: Fresh upgrade from v0.30.1

- **WHEN** a user upgrades from v0.30.1 to v0.31.0 and HA starts up
- **THEN** `async_migrate_entry` SHALL run, rewrite the listed entity_ids in the registry, bump `entry.version` from 1 to 2, and return `True`. Entities SHALL retain their state history across the rename.

#### Scenario: Already-migrated entry

- **WHEN** HA starts up with an entry whose version is already 2 (e.g. second restart after upgrade)
- **THEN** `async_migrate_entry` SHALL detect `entry.version >= 2` and return `True` immediately without modifying the registry

### Requirement: Specific entity_id renames

The migration SHALL rename the following entity_ids when their old form exists in the registry and their new form does not:

| Old entity_id | New entity_id |
|---|---|
| `water_heater.water_heater` | `water_heater.hot_water_tank` |
| `sensor.solar_solar_collector_temperature` | `sensor.solar_collector_temperature` |
| `sensor.solar_solar_storage_temperature` | `sensor.solar_storage_temperature` |
| `sensor.solar_solar_pump_modulation` | `sensor.solar_pump_modulation` |
| `sensor.solar_total_solar_gain` | `sensor.solar_total_gain` |

#### Scenario: All legacy IDs present

- **WHEN** the registry contains all five old entity_ids prior to migration
- **THEN** after `async_migrate_entry` runs, the registry SHALL contain all five new entity_ids and NONE of the old ones

#### Scenario: User had renamed an entity manually before upgrade

- **WHEN** the registry does NOT contain `sensor.solar_solar_collector_temperature` (e.g. user renamed it to `sensor.my_collector_temp`)
- **THEN** the migration SHALL skip that rename and leave the user-chosen ID intact — it SHALL NOT overwrite user-renamed IDs

#### Scenario: New entity_id already exists

- **WHEN** for some reason `sensor.solar_collector_temperature` is already present in the registry (e.g. previous failed migration attempt)
- **THEN** the migration SHALL skip that specific rename to avoid an entity_id collision, log a warning, and continue with the rest

### Requirement: Migration is fault-tolerant

The migration SHALL wrap each individual rename in a try/except so that a failure on one rename does NOT abort the rest. The function SHALL still bump `entry.version` to 2 after all renames are attempted, so partial failures don't cause infinite retry loops on every restart.

#### Scenario: One rename throws an exception

- **WHEN** one of the five renames raises (e.g. HA's registry API returns an error)
- **THEN** the migration SHALL log the failure at WARNING level with the affected entity_id, continue with the other four renames, and still bump `entry.version` to 2

### Requirement: Lovelace YAML is documented as not migrated

The integration SHALL NOT attempt to migrate user Lovelace YAML / dashboard configurations referencing the old entity_ids — that's outside HA's entity-registry migration surface. The release notes SHALL prominently call out this gap.

#### Scenario: Power user with custom Lovelace YAML

- **WHEN** a user has a hand-written Lovelace card that references `sensor.solar_solar_collector_temperature` directly in YAML
- **THEN** after upgrade their card SHALL show "Entity not found" until they manually update the YAML to `sensor.solar_collector_temperature` — this is documented behavior

### Requirement: Rollback is one-way

The integration SHALL NOT provide a rollback migration. Reverting from v0.31.0 to v0.30.1 leaves the registry in its v0.31.0 state (new entity_ids), which will cause v0.30.1 to register fresh entities at the original IDs without history. This SHALL be documented in the release notes.

#### Scenario: User downgrades after upgrade

- **WHEN** a user installs v0.31.0, then downgrades back to v0.30.1
- **THEN** their existing entities at the new IDs SHALL persist (HA doesn't auto-delete entities); v0.30.1 SHALL create new entities at the old IDs without history; the release notes SHALL document that downgrade is not supported
