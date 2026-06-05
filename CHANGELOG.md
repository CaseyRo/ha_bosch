# Changelog

All notable changes to this Bosch Home Assistant custom component will be documented in this file.

## [Unreleased]

## [1.0.0] — 2026-06-05 — POINTTAPI: bulk polling, gateway discovery, native boost

A milestone release: the POINTTAPI path adopts capabilities mapped by the
HomeCom Easy open-source ecosystem and verified against a live CT200. Every
new behavior degrades gracefully to the previous (v0.33) behavior if Bosch
changes the unofficial API. See `docs/pointtapi-api.md` for the endpoint
reference and the new README **Acknowledgements** section for credits
(serbanb11/homecom_alt, @joddye2's CT200 dumps, BassXT/buderus,
bosch-thermostat-client).

### Changed
- **Bulk polling** — steady-state polls now batch ~50 resource reads into 2
  `POST /bulk` requests instead of 40–50 sequential GETs every 60 s. The
  reference walk remains as discovery (first refresh + every 24 h) and as
  automatic per-cycle fallback when bulk misbehaves (WARNING throttled to
  once per hour). `coordinator.data` shape is unchanged.
- **Config flow reordered (OAuth-first)** — sign in first, then your gateway
  is auto-discovered from your Bosch account (`GET /gateways/`): one device
  auto-selects, several show a picker, and manual serial entry remains the
  fallback. **Existing entries are unaffected** — no re-setup needed; reauth
  unchanged.
- **Native boost** — the boost switch now triggers the device's real boost.
  Probes (2026-06-05) showed Bosch lifted the 403 on the boost write routes
  and revealed `boostShortcut` — the app's one-shot boost struct. The switch
  tries `boostShortcut`, then `boostZones`+`boostMode`, confirms activation
  against the next refresh, caches the working route (visible in
  diagnostics as `boost_probe_result`), and falls back to the v0.33
  manual-mode workaround if native fails. Under native boost the remaining
  time sensor shows Bosch's server-side countdown and boost survives HA
  restarts.

### Added
- **Notifications** sensor — active cloud alert count with raw entries as
  attributes (parity with the XMPP path's notification sensor)
- **Away mode** switch (`/system/awayMode/enabled`)
- **Extra hot water** switch + **duration** number (15–2880 min, step 15)
- **Thermal disinfect** config: start-time number (minute-of-day), weekday
  select (Mo–Su), last-result diagnostic sensor
- `docs/pointtapi-api.md` — observed-API reference with provenance
- Path-absent entities (switch/number/select + notifications) now report
  `unavailable` instead of a stale default state

### Developer notes
- `PoinTTAPIClient.bulk(paths)` and `list_gateways()` (+ module-level
  `async_list_gateways`) — wire formats credited inline
- Coordinator: discovery-then-bulk with 24 h rediscovery;
  `/energy/historyHourly` pagination stays on sequential GETs
- 181 unit tests passing; new suites for bulk envelope, gateway discovery,
  comfort controls, and the boost probe ladder

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
