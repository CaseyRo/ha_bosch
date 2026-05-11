## 1. Update platform infrastructure

- [x] 1.1 Add `BoschPoinTTAPIUpdateEntityDescription` frozen dataclass to `pointtapi_entities.py` (extends `UpdateEntityDescription`, fields `installed_version_fn: Callable[[dict], str | None] | None = None` and `latest_version_fn: Callable[[dict], str | None] | None = None`).
- [x] 1.2 Add `BoschPoinTTAPIUpdateEntity(CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], UpdateEntity)` — `_attr_has_entity_name = True`, `_attr_supported_features = UpdateEntityFeature(0)`, unique_id `f"{entry_id}_pointtapi_update_{slug}"`, device routing via `_resolve_device_info`. Implements `installed_version` and `latest_version` properties calling the description's fns.
- [x] 1.3 Define `POINTTAPI_UPDATE_DESCRIPTIONS` tuple with one entry for the gateway firmware:
  - `key="/gateway/versionFirmware"`, `translation_key="firmware_update"`, `entity_category=DIAGNOSTIC`
  - `installed_version_fn` reads `_val(data, "/gateway/versionFirmware")`
  - `latest_version_fn` reads `_val(data, "/gateway/update/state")`; if it equals `"no update"` (case-insensitive after trim) returns installed_version, else returns `f"{installed} (update available)"`
- [x] 1.4 Create `custom_components/bosch/update.py` with `async_setup_entry(hass, config_entry, async_add_entities)` that short-circuits non-POINTTAPI entries and otherwise creates one entity per description.

## 2. Diagnostic timestamp sensors

- [x] 2.1 Add a `_parse_update_timestamp(raw_value)` helper that strips trailing ` Mo`/`Tu`/...`Su` weekday suffix and parses via `datetime.fromisoformat`. Returns `None` on parse failure.
- [x] 2.2 Add two `BoschPoinTTAPISensorEntityDescription` entries to `_pointtapi_sensor_descriptions()`:
  - `key="/gateway/update/lastCheck"`, `translation_key="last_update_check"`, `device_class=TIMESTAMP`, `entity_category=DIAGNOSTIC`, `value_fn` using the helper
  - `key="/gateway/update/lastUpdate"`, `translation_key="last_update_applied"`, `device_class=TIMESTAMP`, `entity_category=DIAGNOSTIC`, `value_fn` using the helper

## 3. Refill-needed binary sensor

- [x] 3.1 Extend `_resolve_on_off` in `pointtapi_entities.py` to also accept `"true"`/`"false"` (case-insensitive after trim). Existing `"on"`/`"off"` behavior preserved.
- [x] 3.2 Add `BoschPoinTTAPIBinarySensorEntityDescription(key="/heatSources/refillNeeded", translation_key="refill_needed", device_class=BinarySensorDeviceClass.PROBLEM)` to `POINTTAPI_BINARY_SENSOR_DESCRIPTIONS`. Device routes via `_resolve_device_info` (`/heatSources/*` → Boiler).

## 4. Coordinator: ensure `/gateway/update/lastCheck` and `lastUpdate` are populated

- [x] 4.1 Verify by inspection that `/gateway/update` is already polled as part of `POINTTAPI_COORDINATOR_ROOTS` (it's a refEnum, so the coordinator should fetch its references including `lastCheck` and `lastUpdate`). If not present, add `/gateway/update/lastCheck` and `/gateway/update/lastUpdate` to the roots — but most likely they're already picked up via reference traversal.

## 5. Translations

- [x] 5.1 Add four new keys to `strings.json` and `translations/en.json`:
  - `firmware_update` (under `entity.update`) → "Firmware"
  - `last_update_check` (under `entity.sensor`) → "Last update check"
  - `last_update_applied` (under `entity.sensor`) → "Last update applied"
  - `refill_needed` (under `entity.binary_sensor`) → "Refill needed"
- [x] 5.2 Localize for `de`, `nl`, `fr`, `it`, `pl`, `sk` (Python script as in v0.31.0).

## 6. Lint + smoke tests

- [x] 6.1 `uvx ruff check custom_components/bosch` passes.
- [x] 6.2 Extend `unittests/test_pointtapi_routing.py` (or add `unittests/test_pointtapi_update.py`) with cases for:
  - `_resolve_on_off("true")` → True, `_resolve_on_off("false")` → False, `_resolve_on_off("TRUE")` → True
  - `_resolve_on_off("on")` → True (regression — old behavior still works)
  - `_parse_update_timestamp("2026-05-11T01:02:00+02:00 Mo")` returns a datetime with the right tzinfo
  - `_parse_update_timestamp("bogus")` returns None

## 7. Live verification on the user's HA box

- [x] 7.1 Bump `manifest.json` to `0.32.0`.
- [x] 7.2 `bash ./sync-to-ha.sh` and restart HA container.
- [x] 7.3 Confirm `update.easycontrol_gateway_firmware` appears in the HA Updates panel with installed_version `05.04.00`. With state currently `"no update"`, the entity should show as up-to-date (no badge).
- [x] 7.4 Confirm `binary_sensor.boiler_refill_needed` exists, value `off`, device class `problem`, attached to Boiler device.
- [x] 7.5 Confirm `sensor.easycontrol_gateway_last_update_check` and `_last_update_applied` exist with parsed datetime values. Verify the weekday tail was stripped.
- [x] 7.6 No new WARNING/ERROR lines in `docker logs homeassistant` filtered for `bosch|pointtapi` since restart.

## 8. Release

- [ ] 8.1 Commit `v0.32.0: HA Update platform entity + refill-needed binary + timestamp diagnostics`.
- [ ] 8.2 Tag `v0.32.0`, push master + tag.
- [ ] 8.3 `gh release create v0.32.0 --latest` with notes summarizing the four new entities and noting the resolver generalization (no breaking changes, purely additive).
- [ ] 8.4 Confirm CI green.

## 9. Archive

- [ ] 9.1 Run `/opsx:verify` on this change.
- [ ] 9.2 Run `/opsx:archive` to sync delta specs to main and move the change to archive.
