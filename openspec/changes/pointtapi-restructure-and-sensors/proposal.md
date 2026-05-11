## Why

The POINTTAPI device structure in Home Assistant is hostile to the homeowner's mental model. A user opening Settings → Devices & Services → Bosch sees one catch-all "POINTTAPI" device holding ~35 entities at the same UI level: WiFi signal sits next to burner flame, annual gas goal sits next to outdoor temperature, firmware version sits next to night-setback threshold. There's no visual grouping that maps to the physical reality of "the gateway on the wall," "the gas boiler," "the hot-water tank," and "the heating zone."

The lone existing sub-device — "Solar" — is also wrong: it's created unconditionally for every install, so households without a solar collector see four permanently-`unavailable` ghost entities under a device they don't own. The translation keys on those four entities also start with `solar_` while the device is already named "Solar", giving entity_ids like `sensor.solar_solar_collector_temperature` — that double prefix leaks into automations, dashboards, voice assistants, and log lines.

A UX audit confirmed all of this and added a few flags I'd missed: outdoor temperature and indoor humidity are zone-context sensors mis-attributed to the gateway; heating-circuit numbers like max supply temp / night setback / room influence are silently routed to the gateway catch-all even though they're zone configuration; `water_heater.water_heater` reads as a typo; and multi-zone systems (zn2, zn3) currently fall through to the catch-all because the routing logic hard-codes `zn1`.

Meanwhile the integration is *missing* useful entities the API already exposes every poll: DHW tank actual temperature, DHW heating state, burner flame indicator, lifetime ignition starts. The original v0.30.2 plan was to ship just those four. Layering them onto the catch-all device first and reshuffling later would force users through two cycles of churn for what is, at heart, one design fix. This change does both at once — restructure the devices and add the new entities to the right ones from day one.

## What Changes

- **BREAKING (device structure):** Replace the current "POINTTAPI" + "Zone zn1" + "Solar" + "Water heater" device tree with a physical-thing partition:
  - **EasyControl Gateway** — wifi/firmware/update/auto-update/notification light/PIR sensitivity (the box on the wall)
  - **Boiler** — actual supply temp, modulation, power setpoint, system pressure, burner flame, ignition starts, blocking/locking/maintenance errors, display/cause code, gas usage sensors (today + this hour + annual goal)
  - **Hot Water Tank** — `water_heater` entity, DHW actual temperature, DHW heating binary, thermal disinfect switch, boost duration/temperature relating to DHW (currently routed to gateway)
  - **Heating Zone** — climate entity, valve position, zone mode select, boost switch, night setback threshold, room influence, summer/winter (threshold + mode), min/max supply, temperature calibration offset, outdoor temperature, indoor humidity
  - **Solar** *(conditional — created only if `/solarCircuits/sc1` returns live data on first refresh)* — collector temperature, tank bottom temperature, pump modulation, total solar gain
- **BREAKING (entity_id of water_heater):** Rename the device that hosts the DHW mode entity from "Water heater" to "Hot Water Tank". The entity_id changes from `water_heater.water_heater` to `water_heater.hot_water_tank` and must be migrated.
- **BREAKING (entity_id of solar entities):** Drop the `solar_` prefix from solar translation keys (`solar_collector_temperature` → `collector_temperature`, etc.). The entity_ids change from `sensor.solar_solar_collector_temperature` → `sensor.solar_collector_temperature`. Migration via `async_migrate_entry` rewrites the registry so user automations don't break.
- **BREAKING (device rename):** "POINTTAPI" → "EasyControl Gateway", "Zone zn1" → "Heating Zone". Affects display names only; entity_ids do not change for entities already on those devices.
- **New entities (DHW detail):** `sensor.hot_water_tank_actual_temperature`, `binary_sensor.hot_water_tank_heating`.
- **New entities (burner state):** `binary_sensor.boiler_flame`, `sensor.boiler_ignition_starts`.
- **Infrastructure:** wire the POINTTAPI branch in `binary_sensor.py` (currently a no-op for POINTTAPI) so the new binaries — and any future ones — register correctly. Add the table-driven `BoschPoinTTAPIBinarySensorEntityDescription` pattern.
- **Translations** for all locales we already maintain (`en`, `de`, `nl`, `fr`, `it`, `pl`, `sk`) covering both the new entity names and the renamed entity translation keys.
- **No new API calls.** All paths are already in `POINTTAPI_COORDINATOR_ROOTS`.
- **No coordinator changes.** Token refresh + hourly pagination behavior carry over from v0.30.1 unchanged.

## Capabilities

### New Capabilities
- `pointtapi-device-partition`: Defines the physical-thing device tree (Gateway, Boiler, Hot Water Tank, Heating Zone, optional Solar) and how every POINTTAPI entity routes to the correct device. Codifies the rule that entities belong to physical objects, not API protocols.
- `pointtapi-dhw-detail`: Tank actual temperature sensor + active-heating binary sensor on the Hot Water Tank device.
- `pointtapi-burner-state`: Flame binary sensor + lifetime ignition starts sensor on the Boiler device.
- `pointtapi-binary-sensors`: Establishes the POINTTAPI branch of the `binary_sensor` platform (currently a no-op) using the same table-driven dataclass pattern the sensor platform already uses.
- `pointtapi-conditional-solar`: Only creates the Solar device and its four entities when `/solarCircuits/sc1` returns live data on first coordinator refresh. Removes the four `unavailable` ghost entities for non-solar installs.
- `pointtapi-entity-migration`: One-shot `async_migrate_entry` that renames legacy entity_ids (`water_heater.water_heater` → `water_heater.hot_water_tank`, `sensor.solar_solar_*` → `sensor.solar_*`) so existing user automations, dashboards, and scripts keep working.

### Modified Capabilities
<!-- none — there are no existing main specs in openspec/specs/ yet (this is the first artifact-driven change). Everything is additive on the capability surface. -->

## Impact

- **Code:**
  - `custom_components/bosch/pointtapi_entities.py` — central change. Refactor every entity's `__init__` device-info section to use a shared `_resolve_device_info(uuid, path, kind)` helper that returns the right `DeviceInfo` for each of the 5 devices. Add `BoschPoinTTAPIBinarySensorEntityDescription` + entity class + factory. Add 4 new descriptions (2 sensor, 2 binary_sensor). Rename solar translation keys.
  - `custom_components/bosch/binary_sensor.py` — replace POINTTAPI no-op with coordinator-based add-entities.
  - `custom_components/bosch/__init__.py` — add `async_migrate_entry` handler keyed off entry version (current data has no version → migrate to v=2). Conditional Solar device creation gated on first coordinator refresh.
  - `custom_components/bosch/sensor/__init__.py` — only register solar sensor entities when coordinator's first poll returned data for `/solarCircuits/sc1`.
  - `custom_components/bosch/strings.json` + `translations/{en,de,nl,fr,it,pl,sk}.json` — new keys for the four new entities, renamed keys for the four solar entities, renamed device-display strings.
- **APIs:** read-only. No new GETs, no new PUTs, no new pagination.
- **Dependencies:** none added.
- **HA energy dashboard:** unchanged. Solar total gain (now `sensor.solar_total_gain`) remains TOTAL_INCREASING + kWh, just under a more honest entity_id.
- **Compatibility:** **BREAKING entity_ids** for water_heater and solar entities. Migrated via `async_migrate_entry` so automations using the old IDs continue to work after one HA restart. User-facing card YAML / dashboard configurations are NOT migrated by HA — users with hand-written Lovelace YAML referencing `sensor.solar_solar_*` will need to update those manually. Release notes will call this out prominently.
- **Migration safety:** the migration function is idempotent — re-running on an already-migrated entry is a no-op. Rollback to v0.30.1 leaves the entity registry in its v0.31.0 state, which is harmless (new IDs continue to exist; nothing new tries to register the old ones).
- **Multi-zone systems:** scope-limited. The new routing treats zone names as opaque, so any `/zones/<id>` / `/heatingCircuits/<id>` paths get their own device. Today only `zn1`/`hc1` are populated, but zn2/zn3 would land on their own devices instead of falling through to the gateway catch-all.
- **Release target:** v0.31.0 (minor bump — breaking entity_id rename via migration).
