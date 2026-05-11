## Purpose

Create the Solar device and its four entities only when `/solarCircuits/sc1` returns live data on the first coordinator refresh. Non-solar households see no Solar entries at all — no `unavailable` ghosts under a device they don't own.

## Requirements

### Requirement: Solar device created only when solar data is present

The integration SHALL create the "Solar" device and its associated entities (collector temperature, storage temperature, pump modulation, total gain) ONLY when the first coordinator refresh after setup returns a usable response for `/solarCircuits/sc1` (a dict with at least one of the four expected ref keys populated with a `value`).

#### Scenario: Install with solar collector

- **WHEN** the integration is set up on a system whose first poll returns populated solar refs (e.g. `collectorTemperature.value` is a number)
- **THEN** the Solar device SHALL appear in HA's device registry and all four solar entities SHALL be registered with `disabled_by=None`

#### Scenario: Install without solar collector

- **WHEN** the integration is set up on a system whose first poll returns no `/solarCircuits/sc1` data (path missing, returns 403, or returns an empty dict)
- **THEN** the Solar device SHALL NOT appear in HA's device registry and the four solar entities SHALL NOT be registered — the user's HA UI SHALL be free of solar references entirely

### Requirement: Existing Solar device + entities removed for non-solar installs on upgrade

When an install previously had unconditionally-created Solar entities (from v0.30.x or earlier) but the system has no solar hardware, the integration SHALL detect this on first run after upgrade and remove the orphaned Solar device + entities from the registry.

#### Scenario: Upgrade from v0.30.1 on a non-solar system

- **WHEN** a user upgrading from v0.30.x has the legacy `(DOMAIN, f"{uuid}_solar")` device in their registry but their first v0.31.0 coordinator refresh returns no solar data
- **THEN** the integration SHALL delete the Solar device and its four entities from the device + entity registries during `async_migrate_entry` or on first refresh, leaving no orphan entries

### Requirement: Late-arriving solar requires explicit reload

The integration SHALL NOT automatically detect solar hardware appearing AFTER the initial setup (e.g. user adds a collector to their Bosch account weeks later). Re-running the conditional-solar check SHALL require the user to reload the config entry (Settings → Devices & Services → Bosch → ⋮ → Reload).

#### Scenario: Solar added later

- **WHEN** a user adds a solar collector to their Bosch account after the integration is set up and the next coordinator poll suddenly returns `/solarCircuits/sc1` data
- **THEN** the integration SHALL NOT spontaneously create the Solar device — that requires a reload (documented in release notes)
