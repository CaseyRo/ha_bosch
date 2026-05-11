## Why

Two small follow-ups deferred from the v0.31.0 audit (see archived `pointtapi-restructure-and-sensors` §12):

1. **Firmware update is a string sensor instead of an HA Update entity.** Today `sensor.pointtapi_firmware_update_state` reports `"no update"` or similar as plain text. Users have to monitor the value manually — it never surfaces in HA's native Updates panel where they're already used to seeing firmware prompts for other integrations. The audit flagged this as polish-worthy.

2. **The boiler's "refill needed" signal isn't exposed.** Bosch reports `/heatSources/refillNeeded` as `"true"`/`"false"` every coordinator poll, but the integration ignores it. This is a real maintenance flag — when the heating circuit's pressure drops too low, the boiler needs water added to keep working.

Both data sources are already in `coordinator.data`. Adding the entities is small.

## What Changes

- **New Update entity:** `update.easycontrol_gateway_firmware` (HA's native `update` platform). Reports current firmware from `/gateway/versionFirmware` as `installed_version`. Derives `latest_version` from `/gateway/update/state` — when state is `"no update"` the latest version equals installed; otherwise it surfaces as "Update available" so the standard HA Updates panel picks it up. No install method (Bosch doesn't expose a programmatic install — users still trigger updates from the EasyControl app).
- **New diagnostic sensors:** `sensor.easycontrol_gateway_last_update_check` (timestamp from `/gateway/update/lastCheck`) and `sensor.easycontrol_gateway_last_update_applied` (from `/gateway/update/lastUpdate`). Both `entity_category=DIAGNOSTIC`, `device_class=TIMESTAMP`. The API appends a 2-letter weekday at the end (e.g. `"2026-05-11T01:02:00+02:00 Mo"`) — value_fn strips that before parsing.
- **New binary sensor:** `binary_sensor.boiler_refill_needed` (`device_class=PROBLEM`) from `/heatSources/refillNeeded`. Treats the API's lowercase `"true"`/`"false"` strings as boolean. Attached to the Boiler device.
- **POINTTAPI Update platform** wired up in `update.py` (or `update/__init__.py`) — analogous to how `binary_sensor.py` was wired in v0.31.0. No-op for XMPP/HTTP entries.
- **String → bool resolver enhanced** to also accept `"true"`/`"false"` (`_resolve_on_off` in `pointtapi_entities.py` currently handles only `"on"`/`"off"`). Required by `refill_needed`.
- **Translations** for the new entity names in all 7 locales.
- **The existing `sensor.pointtapi_firmware_update_state` is retained** as-is for backward compatibility. The new Update entity is additive. Users who built automations against the string sensor keep working; the Updates panel gets the new entity for everyone.

## Capabilities

### New Capabilities
- `pointtapi-firmware-update`: HA Update entity for the EasyControl gateway, plus two diagnostic timestamp sensors for last-check / last-applied. Picked up automatically by HA's Updates panel.
- `pointtapi-refill-needed`: Binary sensor that fires when the boiler reports low pressure / needs water topped up. Lets users add an automation that pings their phone before the boiler hard-faults.
- `pointtapi-update-platform-wiring`: Establishes the `update` platform's POINTTAPI branch and the `BoschPoinTTAPIUpdateEntityDescription` pattern parallel to the binary-sensor pattern from v0.31.0. Enabling infrastructure for any future Update entities (e.g. per-thermostat firmware once the API exposes it).

### Modified Capabilities
- `pointtapi-binary-sensors`: extend the default `_resolve_on_off` resolver to also accept `"true"`/`"false"` (case-insensitive after trim) in addition to `"on"`/`"off"`. The `refill_needed` API reports lowercase booleans; this generalizes the resolver so future entities reporting either dialect work without per-entity `value_fn`.

## Impact

- **Code:**
  - `custom_components/bosch/pointtapi_entities.py` — add `BoschPoinTTAPIUpdateEntityDescription` dataclass + `BoschPoinTTAPIUpdateEntity` class + `POINTTAPI_UPDATE_DESCRIPTIONS` tuple. Add 3 new sensor / binary_sensor descriptions (last_check, last_applied, refill_needed). Extend `_resolve_on_off` to accept true/false.
  - `custom_components/bosch/update.py` (new file) — `async_setup_entry` for POINTTAPI entries, parallel to `binary_sensor.py`.
  - `custom_components/bosch/manifest.json` — version bump to 0.32.0.
  - `custom_components/bosch/strings.json` + `translations/{en,de,nl,fr,it,pl,sk}.json` — keys for `easycontrol_gateway_firmware`, `last_update_check`, `last_update_applied`, `boiler_refill_needed`.
- **APIs:** read-only. All paths already polled (`/gateway/update/*` was already in `POINTTAPI_COORDINATOR_ROOTS` via references; `/heatSources/refillNeeded` ditto).
- **Dependencies:** none added.
- **HA Updates panel:** new entry appears for the gateway firmware. Click → see version string + last check/applied timestamps. No "Install" button (Bosch doesn't expose programmatic install).
- **Compatibility:** purely additive on user-facing entities. The existing `sensor.pointtapi_firmware_update_state` keeps working. No migrations required, no entity_id renames.
- **Release target:** v0.32.0 (minor bump — adds capabilities + new entities, no breaking changes).
