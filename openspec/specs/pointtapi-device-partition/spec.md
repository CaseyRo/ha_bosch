## Purpose

Group every POINTTAPI entity into a device that maps to a physical object the homeowner can identify: EasyControl Gateway, Boiler, Hot Water Tank, Heating Zone, and (conditionally) Solar. Establishes `_resolve_device_info(uuid, path, kind)` as the single source of truth for routing entities to devices, and supports multi-zone installs by parsing zone ids from paths.

## Requirements

### Requirement: Five-device physical-thing partition

The integration SHALL group POINTTAPI entities into devices that map to physical things the homeowner can identify: **EasyControl Gateway** (`(DOMAIN, uuid)`), **Boiler** (`(DOMAIN, f"{uuid}_boiler")`), **Hot Water Tank** (`(DOMAIN, f"{uuid}_dhw1")`), **Heating Zone {zone_id}** (`(DOMAIN, f"{uuid}_{zone_id}")` per zone), and optionally **Solar** (`(DOMAIN, f"{uuid}_solar")`). Every non-gateway device SHALL set `via_device=(DOMAIN, uuid)` so HA renders the gateway as the parent. The Hot Water Tank and Heating Zone slugs (`_dhw1` and `_{zone_id}` without a `_zone_` prefix) match the v0.30.x identifiers for the existing `water_heater.water_heater` and climate-entity devices, so on upgrade those devices keep their identity instead of being orphaned and recreated.

#### Scenario: All five devices appear for a solar-thermal-equipped install

- **WHEN** the integration is set up on a system that returns data for `/solarCircuits/sc1`
- **THEN** HA's device registry SHALL contain exactly: 1 Gateway, 1 Boiler, 1 Hot Water Tank, 1 Heating Zone (per active zone), and 1 Solar device — all attributed to the same `entry_id`

#### Scenario: Solar absent for non-solar install

- **WHEN** the integration is set up on a system that does NOT return data for `/solarCircuits/sc1`
- **THEN** HA's device registry SHALL contain Gateway, Boiler, Hot Water Tank, and Heating Zone — but NOT a Solar device

### Requirement: Single source of truth for device routing

The integration SHALL implement device routing via a single `_resolve_device_info(uuid, path, kind=None)` helper that every entity class (Sensor, BinarySensor, Switch, Number, Select, Climate, WaterHeater) delegates to. The helper SHALL be the only place where path-to-device-id mapping rules live.

#### Scenario: A new path is added to the coordinator roots

- **WHEN** a developer adds a new path to `POINTTAPI_COORDINATOR_ROOTS` and a corresponding entity description
- **THEN** assigning that entity to the correct device SHALL require only an entry in `_resolve_device_info`'s routing table — no edits to per-entity `__init__` methods

### Requirement: Path-based routing rules

The `_resolve_device_info` helper SHALL apply the following routing in order, with the first match winning:

| Path prefix / keyword | Device |
|---|---|
| `/solarCircuits/` | Solar |
| `/dhwCircuits/` or `thermal_disinfect` switch | Hot Water Tank |
| `/heatSources/`, `/system/appliance/`, `/energy/`, `annual_gas_goal` number | Boiler |
| `/zones/{zid}`, `/heatingCircuits/{cid}`, `/system/sensors/{humidity,temperatures}/`, zone-config numbers/selects | Heating Zone |
| Anything else (gateway-level) | EasyControl Gateway |

#### Scenario: Heating-circuit number routes to Heating Zone

- **WHEN** the integration constructs an entity for `/heatingCircuits/hc1/maxSupplyTemperature` (a Number entity)
- **THEN** its `device_info.identifiers` SHALL be `(DOMAIN, f"{uuid}_zn1")` (or the appropriate zone id), NOT `(DOMAIN, uuid)`

#### Scenario: Outdoor temperature routes to Heating Zone

- **WHEN** the integration constructs `sensor.heating_zone_outdoor_temperature` (path `/system/sensors/temperatures/outdoor_t1`)
- **THEN** its `device_info.identifiers` SHALL be `(DOMAIN, f"{uuid}_zn1")`

#### Scenario: Gas usage routes to Boiler

- **WHEN** the integration constructs any gas usage sensor (`/energy/history_*`, `/energy/historyHourly_*`, `annual_gas_goal`)
- **THEN** its `device_info.identifiers` SHALL be `(DOMAIN, f"{uuid}_boiler")`

#### Scenario: Notification light switch routes to Gateway

- **WHEN** the integration constructs `switch.easycontrol_gateway_notification_light`
- **THEN** its `device_info.identifiers` SHALL be `(DOMAIN, uuid)` (the bare gateway id)

### Requirement: Multi-zone support

The integration SHALL parse the zone id from the path (e.g. `/zones/zn1` → `zn1`, `/zones/zn2` → `zn2`) and create one Heating Zone device per distinct zone id encountered, so installs with multiple heating zones do NOT see zn2/zn3 entities fall through to the gateway catch-all.

#### Scenario: Hypothetical zn2 entity

- **WHEN** the coordinator returns data for `/zones/zn2/temperatureActual`
- **THEN** the integration SHALL create a "Heating Zone zn2" device with identifier `(DOMAIN, f"{uuid}_zn2")` and attach the corresponding climate entity to it (not to `(DOMAIN, uuid)`)

### Requirement: Human-friendly device display names

Devices SHALL use user-meaningful display names: "EasyControl Gateway", "Boiler", "Hot Water Tank", "Heating Zone {zone_id}", "Solar". The internal API names (`POINTTAPI`, `zn1`, `dhw1`) SHALL NOT appear in device display strings, EXCEPT in the zone-id suffix for multi-zone systems where the suffix is the user's only disambiguator.

#### Scenario: Single-zone system

- **WHEN** the integration is set up on a system with only `zn1` active
- **THEN** the zone device display name SHALL be "Heating Zone" (no `zn1` suffix), keeping the display tidy for the common case

#### Scenario: Multi-zone system

- **WHEN** more than one zone is detected
- **THEN** each zone device's display name SHALL include the zone id ("Heating Zone zn1", "Heating Zone zn2") so users can tell them apart
