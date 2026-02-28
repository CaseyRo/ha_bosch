# Changelog

All notable changes to this Bosch Home Assistant custom component will be documented in this file.

## [Unreleased]

## [0.28.7] — 2026-02-28 — POINTTAPI: Bug fixes + heat source sensors

### Fixed
- **Climate set temperature** — PUT now targets `/zones/{zone_id}/manualTemperatureHeating` instead of the read-only `temperatureHeatingSetpoint`; fixes HTTP 403 error when calling `climate.set_temperature`
- **Gas sensor unit & label** — corrected device class from `ENERGY` → `GAS`, unit from `kWh` → `m³` (the API returns gas volume, not energy), and renamed sensors from "today" → "yesterday" (the API value reflects the last completed day)
- **Night switch mode** — added `"off"` to select options; entity no longer shows blank state when the boiler reports `"off"`, and switching away from `"off"` now works
- **Summer/winter mode** — added `"off"` to select options; same fix as above

### Added
- **Actual supply temperature** sensor (`/heatSources/actualSupplyTemperature`) — diagnostic, °C
- **Actual modulation** sensor (`/heatSources/actualModulation`) — diagnostic, %
- Both sensors poll via the new `/heatSources` coordinator root (added to `POINTTAPI_COORDINATOR_ROOTS`)
- Translations for all new/renamed sensor keys in: en, de, fr, it, nl, pl, sk

---

## [2026-02-27] POINTTAPI: 25 new entities

**Sensors (11)**
- `gas_heating_today` / `gas_hot_water_today` / `gas_total_today` — kWh from `/energy/history`, today's last entry
- `blocking_error`, `locking_error`, `maintenance_request`, `display_code`, `cause_code` — diagnostic
- `firmware_version`, `supply_temp_setpoint`, `boiler_power` — diagnostic

**Switches (3)**
- Auto firmware update (`/gateway/update/enabled`)
- Notification light (`/gateway/notificationLight/enabled`)
- Thermal disinfect (`/dhwCircuits/dhw1/thermalDisinfect/state`) — on DHW device

**Numbers (7)**
- Max/min supply temp, night setback threshold, summer/winter threshold, room influence, temp calibration offset, annual gas goal (kWh)

**Selects (4)** — new platform for POINTTAPI
- Zone mode (`clock`/`manual`), PIR sensitivity (`high`/`medium`/`low`), summer/winter mode (`automatic`/`manual`), night switch mode (`automatic`/`reduced`)

All paths already polled by coordinator — no new API calls. All writeable entities do optimistic update + coordinator refresh.

### Fixed
- Fixed blocking SSL operations warning by wrapping gateway instantiation in executor thread
  - SSL operations (`set_default_verify_paths`, `load_default_certs`, `load_verify_locations`) 
    occur during gateway creation and are now executed in a thread pool executor
  - Applies to both HTTP and XMPP protocol connections
  - Fixes Home Assistant warnings about blocking calls in the event loop

### Changed
- Restored original codebase from GitHub repository
- Kept only the `_patch_bosch_sensor_print()` fix for RecursionError prevention
- Removed all custom logging prefixes and executor thread workarounds

### Technical Details
- Gateway creation now uses `hass.async_add_executor_job()` to run blocking SSL operations
- HTTP session is created in event loop before executor call
- Exception handling added for gateway creation failures

## Notes

This component is based on the official repository:
https://github.com/bosch-thermostat/home-assistant-bosch-custom-component

The only modification from the original is:
1. The `_patch_bosch_sensor_print()` function to prevent RecursionError
2. Wrapping gateway creation in executor thread to avoid SSL blocking warnings
