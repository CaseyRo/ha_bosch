## 1. Device-routing refactor

- [x] 1.1 Add module-level `_resolve_device_info(uuid: str, path: str, kind: str | None = None) -> DeviceInfo` helper in `custom_components/bosch/pointtapi_entities.py`. Implement the routing table from `design.md` §3 (solar → Solar, dhw/thermal_disinfect → Hot Water Tank, heatSources/system/appliance/energy/annual_gas_goal → Boiler, zones/heatingCircuits/system/sensors/zone-config → Heating Zone, everything else → Gateway). Parse zone id from `/zones/{zid}` and `/heatingCircuits/{cid}` paths.
- [x] 1.2 Replace every `_attr_device_info = DeviceInfo(...)` block in `BoschPoinTTAPISensorEntity.__init__`, `BoschPoinTTAPIClimateEntity.__init__`, `BoschPoinTTAPIWaterHeaterEntity.__init__`, `BoschPoinTTAPISwitchEntity.__init__`, `BoschPoinTTAPINumberEntity.__init__`, `BoschPoinTTAPISelectEntity.__init__`, `BoschPoinTTAPIBoostSwitchEntity.__init__` with `self._attr_device_info = _resolve_device_info(uuid, description.key)`.
- [x] 1.3 For the new BinarySensor class (see §3.1), wire device info through the same helper.
- [x] 1.4 Update the Gateway device's display name from "POINTTAPI" → "EasyControl Gateway".
- [x] 1.5 Update the zone-device display name logic: if only one zone exists, render as "Heating Zone"; if multiple, append the zone id (`"Heating Zone zn1"`, `"Heating Zone zn2"`).
- [x] 1.6 Verify routing is correct by listing every existing description in `_pointtapi_sensor_descriptions()`, `_pointtapi_number_descriptions()`, `_pointtapi_select_descriptions()`, `_pointtapi_switch_descriptions()` and recording where each entity should land. Spot-check at least: outdoor temperature → Heating Zone, gas_total_today → Boiler, max_supply_temperature → Heating Zone, thermal_disinfect → Hot Water Tank, notification_light → Gateway, boost (the switch) → Heating Zone (it operates on the zone setpoint), boost_temperature/duration → Heating Zone, annual_gas_goal → Boiler.

## 2. POINTTAPI binary-sensor infrastructure

- [x] 2.1 Add `BoschPoinTTAPIBinarySensorEntityDescription` frozen dataclass to `pointtapi_entities.py` (extends `BinarySensorEntityDescription`, includes optional `value_fn: Callable[[dict], bool | None] | None = None`).
- [x] 2.2 Add `BoschPoinTTAPIBinarySensorEntity(CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], BinarySensorEntity)` with `_attr_has_entity_name = True`, unique_id `f"{entry_id}_pointtapi_binary_sensor_{slug}"`, device routing via `_resolve_device_info`, and a default on/off resolver that returns `True`/`False`/`None`.
- [x] 2.3 Add `POINTTAPI_BINARY_SENSOR_DESCRIPTIONS` tuple (populated in §3 and §4).
- [x] 2.4 Replace the POINTTAPI no-op in `custom_components/bosch/binary_sensor.py:async_setup_entry` with a coordinator-based add-entities pattern matching `sensor/__init__.py`. Keep the existing XMPP/HTTP path below untouched.

## 3. DHW detail entities (Hot Water Tank device)

- [x] 3.1 Add `BoschPoinTTAPISensorEntityDescription(key="/dhwCircuits/dhw1/actualTemp", translation_key="dhw_actual_temperature", device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS, state_class=SensorStateClass.MEASUREMENT)` to `_pointtapi_sensor_descriptions()`.
- [x] 3.2 Add `BoschPoinTTAPIBinarySensorEntityDescription(key="/dhwCircuits/dhw1/state", translation_key="dhw_heating", device_class=BinarySensorDeviceClass.HEAT)` to `POINTTAPI_BINARY_SENSOR_DESCRIPTIONS`.

## 4. Burner / heat-source entities (Boiler device)

- [x] 4.1 Add `BoschPoinTTAPIBinarySensorEntityDescription(key="/heatSources/flameIndication", translation_key="burner_flame", device_class=BinarySensorDeviceClass.RUNNING)`.
- [x] 4.2 Add `BoschPoinTTAPISensorEntityDescription(key="/heatSources/numberOfStarts", translation_key="boiler_ignition_starts", state_class=SensorStateClass.TOTAL_INCREASING)` (no device_class, no unit — API reports unit as `""`).

## 5. Solar translation-key cleanup

- [x] 5.1 Rename four solar descriptions' `translation_key` values (drop the `solar_` prefix):
  - `solar_collector_temperature` → `collector_temperature`
  - `solar_storage_temperature` → `storage_temperature`
  - `solar_pump_modulation` → `pump_modulation`
  - `solar_total_gain` → `total_gain`
- [x] 5.2 Confirm the solar descriptions route to the Solar device via `_resolve_device_info` (no change to `key=` paths needed).

## 6. Conditional Solar device creation

- [x] 6.1 In `custom_components/bosch/sensor/__init__.py:async_setup_entry`, after the first coordinator refresh, check whether `coordinator.data.get("/solarCircuits/sc1")` returned a populated dict (presence of `references`). Build a `solar_has_refs: bool` flag.
- [x] 6.2 Conditionally include the four `/solarCircuits/sc1/*` descriptions in the entities list passed to `async_add_entities` based on `solar_has_refs`. When false, those descriptions are filtered out.
- [ ] 6.3 During migration (§7), if no `/solarCircuits/sc1` data was returned but legacy solar entities + device exist in the registry, delete the orphan Solar device + four legacy entity registry entries. **Deferred:** the conditional skip in §6.2 prevents NEW non-solar installs from creating ghosts; existing v0.30.x non-solar installs (the user's own gateway has solar so no orphan today) will still have ghost entities — can be cleaned via the entity registry UI or a follow-up change. Not blocking for v0.31.0.

## 7. Entity-ID migration (`async_migrate_entry`)

- [x] 7.1 Add `async def async_migrate_entry(hass, entry: ConfigEntry) -> bool` to `custom_components/bosch/__init__.py`. Skip if `entry.version >= 2` (idempotent). Skip if `entry.data.get(CONF_PROTOCOL) != POINTTAPI` (XMPP entries are untouched, but still bump version to keep semantics aligned).
- [x] 7.2 Inside the migration, build the rename map from `design.md` §5 (5 entries). For each: only rewrite if old ID exists AND new ID does not. Wrap each rename in try/except, log failures at WARNING.
- [ ] 7.3 Handle the orphan-Solar-device cleanup. **Deferred** — see §6.3.
- [x] 7.4 Bump `entry.version = 2` via `hass.config_entries.async_update_entry(entry, version=2)` after all renames are attempted (even if some failed).
- [ ] 7.5 Add a `MINOR_VERSION` constant if the codebase doesn't have one, set to 2. **Skipped** — HA only requires `entry.version`, the `MINOR_VERSION` isn't needed for this migration; can revisit if a future migration needs sub-version granularity.

## 8. Translations

- [x] 8.1 In `custom_components/bosch/strings.json` and `translations/en.json`:
  - Add the new keys (`dhw_actual_temperature`, `dhw_heating`, `burner_flame`, `boiler_ignition_starts`) under the appropriate `entity.sensor` / `entity.binary_sensor` sections.
  - Rename the four solar keys (drop `solar_` prefix): the new keys are `collector_temperature`, `storage_temperature`, `pump_modulation`, `total_gain`.
- [x] 8.2 `de.json` — localized names added.
- [x] 8.3 `nl.json` — localized names added.
- [x] 8.4 `fr.json`, `it.json`, `pl.json`, `sk.json` — localized names added.
- [x] 8.5 Validated every translation file parses as JSON (the Python script that wrote them parsed first).

## 9. Lint + unit-style verification (local)

- [x] 9.1 `uvx ruff check custom_components/bosch` passes with no errors.
- [x] 9.2 Smoke tests added at `unittests/test_pointtapi_routing.py` covering path → device routing for solar, DHW, boiler, zone, gateway, plus multi-zone (zn2) and single-zone display-name behavior. CI will run on Python 3.12 + 3.13.

## 10. Live verification on the user's HA box

- [x] 10.1 Bump `custom_components/bosch/manifest.json` version from `0.30.1` → `0.31.0`.
- [x] 10.2 `bash ./sync-to-ha.sh` to push to the remote.
- [x] 10.3 Restart HA container (`ssh ubuntu-smurf-mirror "docker restart homeassistant"`).
- [x] 10.4 Device registry confirmed: 5 devices live with new names — EasyControl Gateway, Boiler, Hot Water Tank, Heating Zone, Solar. No leftover "POINTTAPI" or "Zone zn1" devices.
- [x] 10.5 Entity_id renames took effect: 4 `sensor.solar_*` renames applied + `water_heater.hot_water_tank`. Old IDs no longer in registry.
- [x] 10.6 Four new entities live with values: `sensor.hot_water_tank_tank_temperature` = 31.2 °C, `binary_sensor.hot_water_tank_heating` = off, `binary_sensor.boiler_flame` = off, `sensor.boiler_ignition_starts` = 14636. (Initial entity_id was `sensor.hot_water_tank_tank_temperature` due to "Tank temperature" + device name "Hot Water Tank" doubling — fixed translation strings to "Temperature" so new installs get `sensor.hot_water_tank_temperature`; existing install can rename via HA UI.)
- [x] 10.7 No new WARNING/ERROR lines in docker logs for bosch|pointtapi since restart.
- [x] 10.8 Migration confirmed working — 4 solar renames + 1 water_heater rename all visible in the entity registry.

## 11. Release

- [ ] 11.1 Commit changes with message `v0.31.0: physical-device restructure, DHW + burner sensors, conditional Solar, entity migration`.
- [ ] 11.2 Tag `v0.31.0` and push master + tag.
- [ ] 11.3 `gh release create v0.31.0 --latest` with notes that prominently call out: (a) breaking entity_id renames migrated automatically, (b) Lovelace YAML may need hand-updates for the renamed entity_ids, (c) the new device tree, (d) conditional Solar for non-solar households, (e) link to the openspec change directory.
- [ ] 11.4 Confirm CI is green on the v0.31.0 push.

## 12. Post-release follow-up

- [ ] 12.1 Add a brief note to `auth_singlekey_automation.md` memory if anything changed about the auth flow (likely no change, but verify).
- [ ] 12.2 Open a follow-up openspec change `pointtapi-firmware-update-platform` if and when we want to migrate `update_state` to the proper HA `update` platform (audit recommendation, deferred).
- [ ] 12.3 Open a follow-up openspec change for any additional `/heatSources/refillNeeded` binary sensor if the user wants it after seeing v0.31.0 in production.
