# Changelog

All notable changes to this Bosch Home Assistant custom component will be documented in this file.

## [1.2.0] — 2026-08-11 — Multi-zone climate, localization, per-zone valve + open-window

Pre-released as beta.1–beta.7 and confirmed on two multi-zone CT200 installs
(#11) — @jfhautenauven (12 ETRVs) and @janfuu-cpu (5 ETRVs), who between them
found every regression in this list.

### Added
- **Multi-zone climate discovery (POINTTAPI)** — the coordinator walks the
  `/zones` listing instead of hardcoding `/zones/zn1`; one climate entity per
  discovered zone, each zone device named after its room (#11).
- **Localized entity names and states** — POINTTAPI switches, numbers, selects
  and diagnostics translated in all 7 supported languages (en/de/fr/it/nl/pl/sk);
  diagnostic states are translated too (blocking error `false` → "No error" /
  "Pas d'erreur" / "Kein Fehler"). Contributed by @jfhautenauven (#13).
- **Per-zone valve position sensors** — one diagnostic sensor per zone instead
  of zn1 only, discovered from each zone's own reference list. Contributed by
  @jfhautenauven (#14).
- **Open-window detection per zone** — an enable switch and a window binary
  sensor per zone, created only when the appliance advertises
  `openWindowDetection` for that zone. Contributed by @jfhautenauven (#14).
- **Select robustness** — unknown API values mark the select unavailable
  instead of showing a ghost state; unsupported options are rejected on write.
  Contributed by @jfhautenauven (#14).
- **WiFi firmware version and energy-efficiency sensors** — the latter
  (`/gateway/ui/eco`) only when the gateway advertises it. Supply temperature,
  return temperature (new) and modulation are regular sensors now instead of
  diagnostics. Contributed by @jfhautenauven (#15).

### Removed
- **Firmware-update-state sensor** — redundant with the update entity.
  Existing installs keep an orphaned registry entry; delete it once by hand
  (#15).

### Fixed
- **Zone device names are human-readable** — the PointT API base64-encodes room
  names; they are now decoded (`Rmx1ci9aZW50cmFsZQ==` → `Flur/Zentrale`).
  Contributed by @jfhautenauven (#12).
- **Master zone is named after its room on multi-zone installs** — zn1 (the
  zone the CT200 itself sits in) kept the bare legacy "Heating Zone" device
  name while all other zones showed room names, which read as the room being
  missing (#11). Single-zone installs keep "Heating Zone" unchanged. All
  entities attached to a zone device now resolve the room name consistently.
- **No ghost solar entities on non-solar installations** — the four solar
  sensors are only created when a solar resource reports a real, available
  value; stale solar registry entries from earlier versions are removed
  automatically on reload. Contributed by @jfhautenauven (#12, #13).

### Breaking
- **Thermal disinfect weekday select states are lowercase** (`Mo` → `mo`, …) so
  Home Assistant can translate them for display. Automations calling
  `select.select_option` with the old capitalized values must switch to
  lowercase; the value written to the Bosch API is unchanged (#13).

## [1.1.0] — 2026-07-10 — Easier OAuth onboarding + malformed-data hardening

### Added
- **Sign-in accepts any pasted callback** — the OAuth step now takes the full
  `com.bosch.tt.dashtt.pointt://app/login?code=…` URL, a bare `code=…&state=…`
  fragment, or just the code value on its own. Previously only a URL that both
  contained `code=` and had a scheme parsed; a scheme-less fragment silently
  failed. Removes the common "blank page after login, can't capture the code"
  onboarding snag (upstream issue #554). Sign-in instructions clarified (EN).

### Fixed
- **No longer crashes on non-numeric cloud values** — the `Number` and `Climate`
  coordinator-update callbacks coerced untrusted API values with a bare
  `float()`, so a single malformed reading raised out of HA's dispatch and
  aborted the whole update cycle. Both now guard and fall back to `unavailable` /
  `HEAT`. Root-caused at the shared handlers (all 12 number descriptions + the
  climate entity).
- **Gas backfill survives odd rows** — `pointtapi_statistics` guarded two crash
  paths: a Feb-29 history date remapped onto a non-leap current year raised
  `ValueError` outside the date guard, and a non-numeric reading in the
  running-sum loop raised `TypeError`. Bad rows are now skipped instead of
  aborting the first-refresh backfill.

### Tests
- **+85 unit tests** hardening the POINTTAPI path against malformed/looping
  cloud responses (188 → 269 total): OAuth callback parsing and token refresh
  (`ensure_valid_token`), coordinator `historyHourly` cursor pagination + update
  error-mapping, statistics-backfill robustness, and entity
  absent-path→`unavailable` + optimistic-write guarantees. Coverage moved
  oauth 75→97%, coordinator 68→84%, entities 59→73%, statistics 0→covered.

## [1.0.1] — 2026-06-05 — Fix boost one-shot listener AttributeError

### Fixed
- **Boost off no longer raises `AttributeError` on every coordinator cycle**
  (CDI-1172) — `_clear_boost_flag` called
  `coordinator.async_remove_listener`, which does not exist on HA's
  `DataUpdateCoordinator`, so the one-shot listener crashed each refresh and
  never unregistered. The switch now stores the unsub callable returned by
  `async_add_listener` and calls it from the one-shot (guarding against
  double registration while a one-shot is pending).

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
