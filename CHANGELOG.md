# Changelog

All notable changes to this Bosch Home Assistant custom component will be documented in this file.

## [Unreleased]

## [1.6.0-beta.1] — 2026-09-10

The 1.6.0 beta consolidates the POINTTAPI redesign work developed across the
alpha releases into a release focused on real-world multi-zone installations,
clearer device topology, faster startup, and safer Home Assistant behavior.

This is the first 1.6.0 beta published here. It contains everything from the
`v1.6.0-beta1` and `v1.6.0-beta2` pre-releases on the
[jfhautenauven/ha_bosch](https://github.com/jfhautenauven/ha_bosch) fork, plus
the review follow-ups listed under Fixed. The `1.6.0-alpha*` entries below are
that fork's history.

### Added
- **Thermostat-valve support** — Adds ETRV valve temperature, valve position,
  signal, battery, protocol, warning, child-lock, and calibration-offset
  entities with device-aware routing and reference discovery.
- **Heating Installation Settings device** — Adds a dedicated device for
  supply limits, heating curves, summer/winter controls, night thresholds,
  room influence, global Boost control, and away mode.
- **Multi-zone controls** — Exposes zone mode for every discovered zone and
  adds Spanish and Portuguese localization for user-facing entities and
  virtual device names.

### Changed
- **Boost as a climate preset** — Keeps the user-facing Boost control on each
  climate entity instead of exposing misleading per-zone switches.
- **Optimistic Boost state** — Shows the requested intent immediately,
  preserves it through incomplete polls, and reconciles it with explicit
  Bosch state on the next successful update.
- **Device topology** — Moves thermostat-specific controls from the gateway to
  the thermostat or heating-installation device, with migrations preserving
  entity IDs and unique IDs.
- **Localization architecture** — Supports `es` and `pt` language codes and
  keeps locale keys synchronized with the canonical base strings.

### Fixed
- **Multi-zone Boost behavior** — Corrects native zone selection, partial zone
  removal, stale refresh handling, last-zone shutdown via `boostMode=off`, and
  `boostShortcut` HTTP 403 fallback to the direct route.
- **Startup responsiveness** — Publishes loaded coordinator data immediately
  instead of waiting for a later polling notification.
- **Home Assistant compatibility** — Adds `mean_type=NONE` for sum-only
  statistics imports and uses `via_device_id` where the registry API requires
  an internal device ID.
- **Registry migrations** — Cleans obsolete Boost switches and names, and
  moves existing thermostat-specific entities without breaking automations.
- **Review follow-up** — Startup diagnostics stay at DEBUG, the dead
  `/energy/historyEntries` path is removed, and the duplicate French
  heating-curve translation keys are cleaned up.
- **Gateway discovery deadline** — If the discovery time budget runs out
  before `/gateway` is fetched, the refresh now fails and retries instead of
  completing without gateway data.

### Warning
- **Rollback requires reinstall** — The beta entry migrates to config-entry
  version 11. Rolling back to an older release is not a clean downgrade: the
  registry migration history is not reversed. On current Home Assistant builds,
  a higher config-entry version can block loading until the integration is
  removed and re-added.

### Performance
- **Smarter POINTTAPI discovery** — Uses domain allowlists, bounded parallel
  reference fetching, safer traversal, fast/slow resource tiers, cached slow
  inventories, background history loading, and deliberate rediscovery.
- **Measured result** — Startup time was reduced by **74%** on a complex
  installation with ETRV valves compared with the pre-optimization behavior.

### Scope
- Installation settings: [#22](https://github.com/CaseyRo/ha_bosch/issues/22)
- Boost model: [#21](https://github.com/CaseyRo/ha_bosch/issues/21)
- Home Assistant deprecations: [#47](https://github.com/CaseyRo/ha_bosch/issues/47)
- Spanish/Portuguese localization: [#37](https://github.com/CaseyRo/ha_bosch/issues/37), [#38](https://github.com/CaseyRo/ha_bosch/issues/38)
- Future locale roadmap: [#39](https://github.com/CaseyRo/ha_bosch/issues/39), [#40](https://github.com/CaseyRo/ha_bosch/issues/40), [#41](https://github.com/CaseyRo/ha_bosch/issues/41)

## [1.6.0-alpha22] — 2026-09-08

### Fixed
- **Boost responsiveness** — Shows the user's Boost intent immediately on
  climate entities, preserves it across incomplete polls, and reconciles it
  with the next explicit Bosch state.
- **Translations** — Synchronizes all supported locales with the base strings,
  including heating-curve controls and previously missing diagnostic sensors.

## [1.6.0-alpha21] — 2026-09-08

### Added
- **Heating curve settings** — Adds minimum and maximum heating-curve
  controls to the heating installation settings device ([#22](https://github.com/CaseyRo/ha_bosch/issues/22)).

### Fixed
- **Thermostat-specific switches** — Moves away mode, motion sensitivity, and
  notification light controls from the gateway to the appropriate thermostat
  or heating-installation device, with registry migrations for existing
  entities ([#22](https://github.com/CaseyRo/ha_bosch/issues/22)).
- **Boost control semantics** — Keeps Boost as a climate preset, corrects
  multi-zone native selection and turn-off behavior, handles Bosch's distinct
  last-zone shutdown command, and removes misleading per-zone Boost switches
  ([#21](https://github.com/CaseyRo/ha_bosch/issues/21)).
- **Home Assistant compatibility** — Adds `mean_type=NONE` to sum-only
  POINTTAPI statistics imports and uses `via_device_id` where the registry API
  requires it ([#47](https://github.com/CaseyRo/ha_bosch/issues/47)).

### Performance
- **POINTTAPI startup and polling** — Replaces broad/sequential discovery with
  domain allowlists, bounded parallel reference fetching, fast/slow resource
  tiers, background history loading, and immediate entity synchronization from
  already-loaded coordinator data. On a complex installation with ETRV valves,
  measured startup time was reduced by **74%** versus the pre-optimization
  implementation.

## [1.6.0-alpha20] — 2026-09-08

### Fixed
- **POINTTAPI statistics import** — Supplies `mean_type=NONE` for sum-only
  gas statistics imports, with compatibility for older Home Assistant cores.
- **Device registry compatibility** — Uses `via_device_id` for the direct
  registry API call.

### Removed
- **POINTTAPI Boost switches** — Removes per-zone Boost switch entities and
  cleans them from the entity registry; Boost remains available as a climate
  preset.

## [1.6.0-alpha19] — 2026-09-08

### Fixed
- **Boost switch naming** — Uses the translated entity name instead of the
  zone device name, with migration v8 cleaning persisted registry overrides.

## [1.6.0-alpha18] — 2026-09-08

### Fixed
- **Boost switch registry migration** — Adds migration v7 to clean legacy and
  current registry names so translated Boost switch labels are restored.
- **Thermostat child-lock device** — Moves the main thermostat child-lock
  switch from the gateway device to the zone 1 thermostat device.
- **POINTTAPI Boost turn-off** — Clears and reapplies partial zone selections,
  preserves user selections across stale refreshes, and uses `boostMode=off`
  when the last active zone is removed.

## [1.6.0-alpha17] — 2026-09-08

### Fixed
- **POINTTAPI Boost turn-off** — Remembers the direct Boost route after a
  `boostShortcut` HTTP 403, avoiding repeated failures when other zones remain
  active.
- **Boost switch registry migration** — Clears both stored registry names and
  declares config-entry migration version 5 so translated names are restored.

## [1.6.0-alpha16] — 2026-09-08

### Fixed
- **POINTTAPI Boost availability** — Rechecks Boost capabilities after a
  zone mode change so the climate preset follows Bosch's updated state.
- **Boost switch naming** — Migrates existing entity-registry entries so the
  translated `Boost chauffage` name is restored without changing entity IDs.

## [1.6.0-alpha15] — 2026-09-08

### Added
- **POINTTAPI thermostat valves** — Adds valve offset and child-lock support
  with device-specific entity routing and regression coverage.

### Fixed
- **POINTTAPI discovery and startup** — Improves reference traversal,
  parallel discovery, startup timing diagnostics, and background history
  loading while reducing unnecessary API calls.
- **POINTTAPI boost controls** — Hardens boost route selection, fallback
  handling, zone validation, and state refresh behavior.

### Removed
- **Annual energy goals** — Removes the unused annual gas and electricity goal
  entities, API discovery paths, translations, and related routing code.

## [1.6.0-alpha14] — 2026-09-08

### Changed
- **POINTTAPI discovery allowlist** — Replaces the growing exclusion list with
  domain-specific allowlists that fetch only resources consumed by the current
  entity surface while retaining dynamic zone, program, and valve discovery.

## [1.6.0-alpha13] — 2026-09-08

### Fixed
- **POINTTAPI discovery efficiency** — Removes additional unused gateway,
  energy, DHW, appliance, zone, program, and thermostat-valve metadata calls,
  including descendant paths covered by wildcard exclusions.

## [1.6.0-alpha12] — 2026-09-08

### Changed
- **POINTTAPI startup diagnostics** — Logs the total first-refresh duration and
  every measured discovery path on every startup, including fast starts.

## [1.6.0-alpha11] — 2026-09-08

### Changed
- **POINTTAPI discovery budget** — Reduces the total startup discovery timeout
  from 120 seconds to 60 seconds so a slow or incomplete discovery cannot delay
  initialization for more than one minute.

## [1.6.0-alpha10] — 2026-09-08

### Fixed
- **POINTTAPI discovery efficiency** — Skips unused gateway metadata and
  program-week subtrees during discovery, reducing unnecessary API calls while
  preserving paths consumed by the current entity surface.

## [1.6.0-alpha9] — 2026-09-08

### Fixed
- **POINTTAPI startup performance** — Fetches nested discovery references in
  parallel with a concurrency limit of 10, avoiding the previous cumulative
  delay from hundreds of sequential resource requests.

## [1.6.0-alpha8] — 2026-09-08

### Fixed
- **POINTTAPI startup responsiveness** — Publishes current device data without
  waiting for paginated `historyHourly` loading; historical energy data now
  refreshes in the background and is included in a later coordinator update.

## [1.6.0-alpha7] — 2026-09-08

### Fixed
- **POINTTAPI startup diagnostics** — Records the total first-refresh duration
  and the elapsed time for each discovery path when startup exceeds 30 seconds.
- **POINTTAPI discovery timeout** — Bounds the complete discovery walk at 120
  seconds while preserving partial data and warning when the budget is reached.

## [1.6.0-alpha6] — 2026-09-08

### Fixed
- **POINTTAPI startup diagnostics** — Optional discovery requests now time out
  after 8 seconds instead of blocking startup for up to 30 seconds each, and
  skipped requests are reported at warning level with their resource path.

## [1.6.0-alpha5] — 2026-09-08

### Fixed
- **POINTTAPI startup performance** — Defers paginated `historyHourly`
  loading until the first regular poll so current thermostat data and controls
  become available without waiting for the historical energy walk.

## [1.6.0-alpha4] — 2026-09-08

### Fixed
- **POINTTAPI Boost synchronization** — Refreshes the live Boost mode and
  selected zones before changing the native shortcut selection, and restarts
  an active shortcut with `boostMode=off` before applying the updated zones.
- **POINTTAPI Boost registry migration** — Removes stale per-zone Boost entity
  entries so Home Assistant recreates them with the corrected label.
- **POINTTAPI Boost naming** — Uses the localized **Heating boost** label for
  per-zone Boost switches across all supported languages.

## [1.6.0-alpha3] — 2026-09-08

### Fixed
- **POINTTAPI Boost zone selection** — Activating a zone no longer activates
  stale zones that were only preselected while Boost was off.
- **POINTTAPI Boost turn-off** — A forbidden `boostShortcut` write now falls
  back to the direct `boostZones` and `boostMode` route instead of surfacing a
  403 to Home Assistant.
- **POINTTAPI Boost naming** — Per-zone Boost switches are displayed as
  `Boost` instead of inheriting the thermostat zone name.

### Security
- **Diagnostics no longer leak the appliance serial.** POINTTAPI stores the
  serial under `address`, `device_id` *and* `uuid` in the config entry, none of
  which were redacted, and `/gateway/uuid`'s value passed through untouched
  because the redactor matched a top-level `uuid` **key** that real
  `{"id": ..., "value": ...}` responses never have. Four plaintext copies in a
  file testers routinely paste into public issues.
### Added
- **Native-first Boost controls** — Redesigned POINTTAPI Boost controls with dedicated per-zone switches (`switch.*_boost`), serialized multi-zone activation via `asyncio.Lock` to prevent race conditions on rapid toggles, and integration into climate preset modes (`boost` / `none`) across all locales (#34).
- **Dedicated Heating Circuit (`hc1`) device partition** — Moved circuit-level heating settings away from individual room thermostat devices to a dedicated **Heating Installation** (`/heatingCircuits/hc1`) device to accurately reflect hardware topology.
  - **Before:** Global circuit settings (e.g. supply limits, heating slope, boost duration/temperature) were incorrectly attached to the `zn1` room device (Zone 1 / Thermostat), duplicating or misattributing installation-wide properties.
  - **After:** Supply limits (`supplyTemperatureLimitMax`, `supplyTemperatureLimitMin`), heating dynamics (`heatupCoolingSlope`, `buildingHeatup`), and global Boost settings (`boostTemperature`, `boostDuration`, `boostRemainingTime`) are properly assigned to the Heating Circuit (`/heatingCircuits/hc1`) device, ensuring clean device separation in Home Assistant (#34).
- **`binary_sensor.*_dhw_burner`** — is the burner firing *for hot water* right
  now. Derived (flame on **and** demand type `dhw`), because the POINTT
  protocol carries no such signal; two users had built it by hand first
  (#31, #33).
- **Dashboard section in the README** — the card-mod recipe that colours the
  thermostat ring by `hvac_action` instead of `hvac_mode`, validated by
  @SiemEcho across all four mode x action cases; plus which of the two hot-water
  binary sensors to use for what.
### Changed
- **Read-only number paths** — Number entities for POINTTAPI resources that are read-only (`writeable: 0` or `False`) are now hidden/unavailable, ensuring number entities only represent interactive setpoints and controls (#34).
- The sensor platform is imported for real by the test harness instead of being
  stubbed, so its setup path can be tested at all. Coverage 70.6% → 72%.
- **`dhw_heating` is now `dhw_enabled`**, with `device_class` dropped and states
  reading Enabled/Disabled. `/dhwCircuits/dhw1/state` reports whether hot water
  is *permitted*, not whether it is being heated — confirmed on a Nefit Easy by
  toggling DHW off and on and watching the flag follow the setting while the
  flame stayed off (#33). It previously shipped as name "Status", states
  "Off"/"Heating" and `device_class: HEAT`: three different claims about one
  value, and it read "Heating" whenever hot water was merely switched on.
  Existing entity ids are left alone, so automations keep working; only the
  displayed name and states change.
- **Protocol choice is translatable.** The two options in the first setup step
  were hardcoded English in Python and could never be translated.
### Fixed
- **Local (XMPP/HTTP) entities are no longer all disabled on a fresh install.**
  Every sensor, binary sensor, switch, select and number gated its
  registry-enabled default on a per-entity opt-in list read from the config
  entry — which nothing has ever written, in any released version. New local
  installs showed a climate and water-heater entity and hid the rest. Existing
  installs keep whatever they already have; only newly registered entities are
  affected.
- **Solar devices survive a failed refresh.** A missing `/solarCircuits` key
  removed the solar device *and every entity registry entry on it* — entity
  ids, customisations and history association, irrecoverably. The coordinator
  swallows per-path fetch failures, so one timeout during startup was enough.
  Removal now requires a refresh that actually succeeded and returned data.
- **Turning a zone back on after Off no longer snaps back to Off.** `Off` is
  written as manual mode at the minimum temperature; restoring the mode without
  the setpoint left the zone at 5 °C, so the next poll re-detected `Off` and
  reverted the card. The pre-`Off` setpoint is now restored with the mode.
- **A typo in the local-connection form no longer ends the flow.** Bad
  credentials aborted outright, so a mistyped access token meant restarting from
  "Add integration" and retyping the serial, token and password. The form now
  comes back with an error on it. The step also had no path for being re-entered
  with no input, where it returned `None` and the flow manager could not proceed.
- **Six languages caught up with English.** de/fr/it/nl/pl/sk were missing both
  new setup steps, all four OAuth error messages and both abort reasons, and
  still carried three steps that no longer exist — so a German user got a German
  OAuth screen, an English protocol picker and English-only errors.
- **The OAuth step no longer tells end users to run a shell script.** It
  suggested running `run_playwright_ha.sh` "from the repository" and reading a
  developer testing document — on the step most likely to fail, to people
  running HAOS with no checkout and no shell. Replaced with browser-history
  advice that a non-developer can act on.

## [1.5.1-beta.1] — 2026-08-31

### Fixed
- **Thermal disinfect status** — the newly observed `running` value from
  `/dhwCircuits/dhw1/thermalDisinfect/lastResult` now has a friendly translated
  label in all supported languages.

### Removed
- **`bosch.move_old_statistic_data`** — the service was declared in
  `services.yaml` and `const.py` but never registered, so calling it always
  failed. Both declarations are gone; nothing referenced them.

### Repository
- Releases now carry a `bosch.zip` asset built from the integration directory,
  so the README download counter reports a real number (#27).
- CI measures coverage and fails below 70% (baseline 71%) (#28).

## [1.5.0] — 2026-08-29 — Thermostat-valve entities, appliance status, fast/slow polling

Pre-released as 1.5.0-beta.1 through beta.3, which supersede 1.4.0-beta.1 —
1.4.0 never went stable. @jfhautenauven ran beta.3 on his 12-valve production
install and reported no defects in normal use; #20 had already run there for a
week before merge, and the child-lock write was confirmed end-to-end on real
hardware (#25). The #18 items below still have no hardware confirmation: the
appliance status table in particular is transcribed from manufacturer
documentation, not observed.

### Added
- **Thermostat-valve entities** — per-valve child lock (binary sensor),
  valve position and actual temperature sensors, and a writable calibration
  offset number, resolved from `/devices/device{id}/etrv/*` with a
  `/devices/list/thermostat_valve/{id}` fallback. Contributed by
  @jfhautenauven (#20).
- **Per-zone actual temperature sensor** — `/zones/{id}/temperatureActual`
  exposed as `zone_average_temperature`, the zone-level aggregate the climate
  entity already reports as its current temperature. Contributed by
  @jfhautenauven (#20).
- **README entity matrix** — every POINTTAPI entity with platform, translation
  key, resource path and scope. Contributed by @jfhautenauven (#20).

### Changed
- **Fast/slow polling cadence** — `/gateway`, `/energy`, `/solarCircuits`,
  `/programs`, `/system/appliance` and the `/devices` inventory refresh every
  5 minutes; temperatures, modes and live valve telemetry (`/devices/list`,
  `etrv/*`, `thermostat/*`) stay on the 60-second cycle. Discovery reruns
  daily; energy history every 30 minutes. Contributed by @jfhautenauven (#20).
- **Boost switch renamed "Heating boost"** in all seven locales, so it no
  longer reads as a generic boost next to the DHW controls (#20).
- **Integer-like counters** (`numberOfStarts`, valve ids and similar) that
  arrive as `12.0` or `"12"` now render as integers (#20).
- **Thermostat-valve labels and protocol display** polished; translation
  parity restored across de/en/fr/it/nl/pl/sk (#20).
- **`_discover_roots`** replaces the three copy-pasted zone/program/device root
  walkers; `_pointtapi_number_descriptions` composes `CONSTANT + dynamic` like
  the select descriptions already did. Closes most of #19 (#20).

### Fixed (1.5.0-beta.2)
- **Thermostat-valve child-lock switches attach to their valve device** — the
  switch constructor ignored the description's `device_info_fn`, so every
  child-lock switch landed on the gateway device in beta.1. Discovery is now
  strict on the `childLock/enabled` leaf (no parent-node fallback switch) and
  handles `/devices/deviceN/thermostat/*` layouts beside `etrv/*` for valve
  position, actual temperature and offset. Contributed by @jfhautenauven (#23).

### Fixed (1.5.0-beta.3)
- **Generic services work on cloud entries** — `bosch.send_custom_get` and
  `bosch.send_custom_put_*` routed through the XMPP client's `raw_query` /
  `raw_put` even for POINTTAPI entries, so they were advertised and then raised.
  They now branch on protocol; `bosch.refresh_gateway` is the new name for a
  manual refresh (a coordinator refresh on cloud entries) and
  `bosch.update_thermostat` stays as a deprecated alias. `debug_scan` remains
  XMPP-only: diagnostics plus `send_custom_get` cover the cloud case.
  Contributed by @jfhautenauven (#24, #25).
- **beta.2 valve regressions** — duplicate `unique_id` errors from the
  broadened valve-position/temperature matching, and a phantom
  "Thermostat valve" device for `thermostat`-typed nodes, are fixed; the
  coordinator now follows one more reference level so the child-lock
  `enabled` leaf is actually fetched (the switch read `unavailable`). Child-lock
  write confirmed end-to-end on real hardware. Contributed by @jfhautenauven (#25).
- **Stale thermostat-valve devices can be deleted from their device page** —
  `async_remove_config_entry_device` allows deleting a valve device the gateway
  no longer reports; users upgrading from beta.2 should delete the one ghost
  valve device once. Nothing is removed automatically at startup (#25).

### Changed (1.5.0-beta.3)
- **Device metadata** — the gateway resolves manufacturer and model from
  `/gateway/productId` (Bosch CT200, Buderus TC100.2); zone devices report
  `EasyControl`; POINTTAPI child devices carry a manufacturer. Contributed by
  @jfhautenauven (#25). Thermostat-valve devices deliberately carry **no**
  model: the API exposes no product id for radiator thermostats and real
  installs run `homematicip` valves, so a hardcoded name would be wrong.
- **Two flue-gas appliance status codes** added to the display+cause table
  (`1C`/526, `1F`/525), translated in all seven locales (#25).

### Removed
- **Persistent startup cache** — added mid-PR to accelerate boot, then made
  unreachable by the startup-ordering fix in the same PR (the first live
  refresh reassigned the slow-data dict before any entity could read it).
  Deleted rather than carried: a `.storage` blob per config entry that needed
  a secrets audit on every new gateway field, for no consumer (#20).

### Added (1.4.0-beta.1)
- **Appliance status sensor** — `/system/appliance/displayCode` and `causeCode`
  resolved against a Bosch/Buderus display+cause table to a readable state
  (`heating_operation`, `no_flame_after_ignition`, …), with the raw codes kept
  on the entity attributes. Locking and blocking faults take precedence over
  the normal status. Contributed by @jfhautenauven (#18).
- **Per-zone assigned-program selects** — the zone's `clockProgram` is now
  writable, offering the decoded schedule names as options. Contributed by
  @jfhautenauven (#18).
- **Per-zone optimum start state sensor** — created only for zones that
  advertise `optimumStartState`. Contributed by @jfhautenauven (#18).
- **Heat demand type sensor** — `/heatSources/flameIndication` exposed as
  off / central heating / hot water. Contributed by @jfhautenauven (#18).
- **Conditional entity creation** — zigbee firmware version, electricity annual
  goal and energy efficiency are created only when the appliance advertises
  them, and the annual gas goal is now conditional too, so gateways without
  those resources stop showing permanently-unavailable entities. Contributed by
  @jfhautenauven (#18).
- **Electricity day and month averages report kWh** — as plain informational
  sensors. They deliberately carry no `device_class`/`state_class`: an average
  falls as well as rises, and `TOTAL` would make HA read every dip as a meter
  reset. Promote them once someone has watched the value across a full day on
  real hardware (#18).

### Changed
- **Burner flame binary sensor reads `actualModulation`** instead of parsing
  `flameIndication`, whose string dialect (`off`/`ch`/`dhw`) an on/off parser
  cannot read reliably. Contributed by @jfhautenauven (#18).
- **Thermostat valve presentation** — battery `ok` is normalised to `OK`, and
  the assigned zone shows the room name rather than the zone number.
  Contributed by @jfhautenauven (#18).
- **Zone climate preset control removed** — `AUTO` and `HEAT` already write the
  same `userMode`, so the preset was a second control for one setting (#18).
- **Energy efficiency sensor moved to the Energy performance device** (#18).

### Fixed
- **Thermal disinfect switch reflects its real state** — the path uses `on`/`off`
  rather than `true`/`false`, so the switch previously read as off while
  running. Contributed by @jfhautenauven (#18).
- **An ambiguous cause code no longer raises a fault** — the cause-only fallback
  is built only from causes whose display-code variants agree. Cause 273 is a
  24-hour safety shutdown under display `3F` but normal flame monitoring under
  `0U`, and 280 is a restart-time fault under `7L` but a normal fan start under
  `0U`; a boiler that was simply lighting up would have announced a safety
  shutdown. Ambiguous causes read `unknown` and keep the raw codes in the
  attributes (#18).

## [1.3.1] — 2026-08-17 — Quiet teardown on cloud entries

### Fixed
- **No more hourly "Unable to remove unknown service bosch/debug_scan"** —
  `debug_scan` only registers on the XMPP/HTTP path, but every unload removed
  it unconditionally, so a POINTTAPI (cloud) entry asked Home Assistant to
  remove a service it never had. Harmless, but it shouted about it in
  @altugyurtbasi's log every reload since April. Both services are now guarded
  on `has_service` rather than special-casing the debug one, since
  `bosch.update` has the same exposure when setup fails before registration
  (#7).

## [1.3.0] — 2026-08-12 — Per-valve telemetry, assigned program, schedule/manual climate

Pre-released as 1.3.0-beta.1 and held back from 1.2.0 until someone could run
it on real multi-zone hardware. @LukyHurdy1 did, on a 12-zone Czech install,
and reported battery `ok`, signal 69%, protocol `homematicip` and a working
warning sensor — the confirmation this release ships on (#16).

### Added
- **Per-thermostat-valve telemetry** — each ETRV from `/devices/list` becomes
  its own device named after its room, with signal strength, battery, assigned
  zone and radio protocol as diagnostics, plus a problem binary sensor that
  trips on a non-zero warning code. Contributed by @jfhautenauven (#16, #17).
- **Assigned program per zone** — a sensor resolving each zone's `clockProgram`
  to the schedule's decoded name (`/programs/pgN/name`), falling back to the
  program id when the name is absent. Contributed by @jfhautenauven (#17).
- **Schedule vs. manual control on climate entities** — `AUTO` now follows the
  zone's program and `HEAT` switches it to manual (both write
  `/zones/{id}/userMode`), exposed as a preset too. Zones also report an HVAC
  action (heating / idle). Contributed by @jfhautenauven (#17).
- **Electricity day and month averages** — created only when the appliance
  reports those resources. Contributed by @jfhautenauven (#17).
- **Reference-driven `/programs` and `/devices` discovery** — both now expand
  from their listing references like `/zones` already did, falling back to the
  static root when a gateway doesn't advertise them. Contributed by
  @jfhautenauven (#17).

### Changed
- **Energy entities moved to their own device** — gas/energy history and the
  annual gas goal now live under "Energy performance" instead of "Boiler".
  Entity ids are unchanged, so energy dashboard and statistics are unaffected;
  only the device grouping differs (#17).

### Fixed
- **Valve signal strength no longer trips Home Assistant's unit check** — the
  sensor claimed the `signal_strength` device class while reporting a
  percentage, which HA only allows for dB/dBm. A test now validates every
  sensor's unit against its device class (#17).
- **Zones no longer report "Cooling"** — an unrecognised zone status mapped to
  the cooling HVAC action on heating-only appliances; unknown statuses are now
  reported as unknown. The full status vocabulary is still unconfirmed —
  `circulation` is known to occur and deserves a real mapping (#17).
- **Accents restored in French, Polish and Slovak device and sensor names**
  (#17).

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
