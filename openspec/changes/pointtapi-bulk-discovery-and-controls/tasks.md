## 1. Pre-implementation investigation (boost)

- [x] 1.1 Pull a diagnostics dump from the live EasyControl device page and record `type`/`writeable`/`value` (and enums) for `/heatingCircuits/hc1/boostShortcut`, `/boostZones`, and `/boostMode`; attach findings to this change directory as `boost-probe-notes.md`
- [x] 1.2 Adjust the D4 probe ladder values (zone-list format, shortcut trigger value) in `design.md`/`boost-probe-notes.md` to match the dump before coding

## 2. Bulk polling (pointtapi-bulk-polling)

- [x] 2.1 Add `PoinTTAPIClient.bulk(paths)` — envelope build/parse, 30-path chunking, sequential chunks, auth-failure parity with `get()`, provenance comment crediting serbanb11/homecom_alt
- [x] 2.2 Unit tests for `bulk()`: chunking at 45 paths, per-path 403-inside-200 skip, unparseable envelope raises, 401 raises auth error
- [x] 2.3 Coordinator: persist discovered path list after the reference walk; add steady-state bulk fetch keeping `coordinator.data` shape; keep `/energy/historyHourly` pagination on sequential GETs
- [x] 2.4 Coordinator: wholesale fallback to sequential walk on bulk failure; WARNING throttled to once/hour; 24h rediscovery timer
- [x] 2.5 Unit tests for coordinator: bulk steady state, fallback cycle, rediscovery, data-shape equivalence against recorded v0.33 fixtures

## 3. Gateway discovery (pointtapi-gateway-discovery)

- [x] 3.1 Add `list_gateways()` (account-level GET, no `/resource`), with provenance comment
- [x] 3.2 Reorder POINTTAPI config-flow steps to OAuth-first; keep entry data keys identical to v0.33
- [x] 3.3 Implement gateway selection: auto-select single, picker for multiple (id + deviceType), manual serial-entry fallback on empty/error
- [x] 3.4 Config-flow unit tests: single-gateway auto-select, multi-gateway picker, listing-failure fallback, reauth unchanged
- [x] 3.5 Update `strings.json` + `translations/` for the new/renamed flow steps

## 4. Notifications sensor (pointtapi-notifications)

- [x] 4.1 Add `/notifications` to coordinator roots (rides bulk; optional-path tolerance)
- [x] 4.2 Add notifications sensor (count state, entries attribute, Gateway device) to the sensor table
- [x] 4.3 Unit tests: empty list → 0/[], one entry → 1/verbatim attribute, missing path → unavailable

## 5. Comfort controls (pointtapi-comfort-controls)

- [x] 5.1 Away-mode switch (`/system/awayMode/enabled`, "true"/"false" strings, Gateway device)
- [x] 5.2 Extra-DHW switch (`/dhwCircuits/dhw1/extraDhw`) and duration number (15–2880 min, step 15) on Hot Water Tank
- [x] 5.3 Thermal-disinfect config: time number (0–1439), weekDay select (Mo–Su API values + translated labels), lastResult diagnostic sensor
- [x] 5.4 Add new paths to coordinator roots where not already covered by reference walking; confirm in diagnostics
- [x] 5.5 Unit tests: value mapping, constraint rendering, PUT-and-refresh failure path (4xx keeps device-reported state)
- [x] 5.6 `strings.json` + `translations/` entries for all new entities

## 6. Native boost (pointtapi-boost-behavior delta)

- [x] 6.1 Implement the staged probe ladder in `async_turn_on` (boostShortcut struct PUT → direct boostZones+boostMode → bulk write route; struct format per boost-probe-notes.md, integer zone ids), gated by the next-refresh state check; writes restricted to `boost*` paths
- [x] 6.2 Cache probe result on the coordinator; expose verdict + per-rung outcomes in `diagnostics.py`; DEBUG-log all probe traffic
- [x] 6.3 Native-mode turn-off (deactivate via probed route, never touch zone userMode) and native-mode state derivation (boostMode/boostRemainingTime; no local timer, no boost_session)
- [x] 6.4 Keep fallback mode byte-for-byte v0.33 (manual mode + async_call_later + synthetic countdown) when probes fail
- [x] 6.5 Remaining-time sensor: confirm native path reports Bosch countdown (existing fallback branch) — adjust only the stale comment about "typically 0.0"
- [x] 6.6 Unit tests: probe ladder success at each rung, all-fail fallback, cached-route reuse, native restart recovery, fallback restart limitation (existing tests stay green)

## 7. Documentation & credits

- [x] 7.1 Write `docs/pointtapi-api.md`: bulk envelope, gateway listing, all resource paths we use with observed types/writeable flags, links to upstream sources
- [x] 7.2 README: document new features (bulk polling note, gateway picker, notifications, away mode, extra DHW, thermal disinfect config, native boost behavior)
- [x] 7.3 README: add "Acknowledgements" section crediting serbanb11/bosch-homecom-hass + homecom_alt (incl. issue #78 / @joddye2's CT200 dumps), BassXT/buderus, and bosch-thermostat/bosch-thermostat-client-python
- [x] 7.4 Verify provenance comments exist at every adopted-endpoint definition site (client bulk/list_gateways, boost ladder, new entity tables)

## 8. Release (v1.0.0)

- [x] 8.1 Bump `manifest.json` version 0.33.0 → 1.0.0; update CLAUDE.md version note
- [x] 8.2 Write release notes: config-flow reorder (existing entries unaffected), bulk polling with automatic fallback, new entities, native-boost probe behavior and its diagnostics surface
- [x] 8.3 Run `ruff check custom_components/bosch` and full `python3 -m pytest --tb=short -q unittests`; fix any fallout
- [x] 8.4 Manual smoke test against the live device: bulk steady state in logs, gateway picker on a fresh flow, boost probe verdict in diagnostics
