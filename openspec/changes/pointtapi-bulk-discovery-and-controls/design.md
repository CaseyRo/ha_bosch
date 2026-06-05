## Context

The POINTTAPI path polls ~12 root paths plus one-to-two levels of references every 60s — roughly 40-50 sequential GETs per cycle in `_fetch_paths()` (`pointtapi_coordinator.py`). Research into the HomeCom Easy ecosystem (June 2026) confirmed our CT200/RRC2 gateway is served by the same pointt-api backend and OAuth client (`762162C0-…FADC`) used by the actively-developed HomeCom Easy app, and surfaced capabilities we don't use:

- `POST /pointt-api/api/v1/bulk` — batch read/write, ≤30 resource paths per call (observed by [serbanb11/homecom_alt](https://github.com/serbanb11/homecom_alt), `base.py`)
- `GET /pointt-api/api/v1/gateways/` — account-level gateway listing (scope `pointt.gateway.list`, already in our token)
- `/notifications`, `/system/awayMode/enabled`, `/dhwCircuits/dhw1/extraDhw[Duration]`, `/dhwCircuits/dhw1/thermalDisinfect/{time,weekDay,lastResult}` — confirmed present and (where relevant) `writeable: 1` by a real CT200 resource dump ([bosch-homecom-hass#78](https://github.com/serbanb11/bosch-homecom-hass/issues/78), contributed by @joddye2)
- `/heatingCircuits/hc1/boostShortcut` and `/heatingCircuits/hc1/boostZones` — boost-related resources we have never probed; candidates for replacing the local-timer boost workaround codified in `pointtapi-boost-behavior`

Current boost behavior is a client-side simulation (manual mode + `async_call_later` + synthetic countdown) because direct `PUT /heatingCircuits/hc1/boostMode` returns 403. The homecom_alt project observed that the pointt-api applies per-path, per-route ACLs (e.g. bulk paths *with* the `/resource` prefix → `serverStatus` 403), so the bulk write route and the unprobed boost resources are both plausible escapes.

This release ships as **v1.0.0** (from 0.33.0) — a milestone signaling POINTTAPI-path maturity.

## Goals / Non-Goals

**Goals:**
- Cut per-poll HTTP requests from ~40-50 to ≤4 in steady state via bulk, without changing `coordinator.data`'s `{path: response}` shape (zero entity churn)
- Auto-discover gateways in the config flow; keep manual serial entry as fallback
- POINTTAPI parity for notifications; new away-mode / extra-DHW / thermal-disinfect controls
- Native-first boost with graceful fallback to the existing workaround
- Thorough documentation: README feature table, a `docs/pointtapi-api.md` endpoint reference, and explicit credits to upstream open-source efforts
- Every new behavior degrades to today's behavior if Bosch changes the unofficial API

**Non-Goals:**
- Multi-zone support (zones beyond `zn1`) — separate change; `pointtapi-device-partition` already anticipates it
- Per-room RF device entities (`/devices/*` battery/signal) — deliberately deferred (user de-selected)
- Switching the XMPP path to any new transport; nothing in this change touches the `bosch_thermostat_client` path
- Migrating OAuth to a different client or scope set (we already match the HomeCom Easy app)

## Decisions

### D1: Bulk fetch keeps the path-keyed contract; reference walking survives as discovery
The coordinator's public contract — `coordinator.data: dict[path, response]` — is untouched. Internally, `_fetch_paths()` becomes:
1. **First refresh (and after any 24h re-discovery):** run the existing reference walk once via sequential GETs to *discover* the path set, then persist that flat path list on the coordinator (`self._bulk_paths`).
2. **Steady state:** issue `ceil(N/30)` bulk POSTs over the discovered list. Responses map back into `{path: payload}`.
3. **Per-path failures inside a bulk envelope** (non-200 `serverStatus`/`gatewayResponse.status`) are logged at debug and the path is skipped that cycle — same semantics as today's per-GET exception handling.
4. **Bulk endpoint failure** (HTTP error, unparseable envelope) → that cycle falls back to the sequential GET walk wholesale. A counter logs persistent bulk failures at warning level once per hour, not per cycle.

*Why not bulk-only?* The bulk endpoint is unofficial twice over (observed by a third party, on a different device class). The GET walk is our proven baseline; keeping it as both discovery mechanism and fallback means a Bosch-side bulk regression degrades to v0.33 behavior instead of breaking the integration.

*Alternative considered:* hardcoding the bulk path list (like homecom_alt's RRC2 class). Rejected — our reference walk already adapts to per-installation resources (solar present/absent, etc.), and discovery-then-bulk preserves that.

### D2: Bulk wire format follows homecom_alt's observed envelope
`POST https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/bulk` with body `[{"gatewayId": <device_id>, "resourcePaths": [<path>, …]}]` — paths *without* the `/resource` prefix (with-prefix returns `serverStatus` 403 + null `gatewayResponse`). Response: `[0].resourcePaths[].{resourcePath, serverStatus, gatewayResponse: {status, payload}}`; a path's payload is valid only when both statuses are 200. Implemented as `PoinTTAPIClient.bulk(paths: list[str]) -> dict[str, Any]`, chunking at 30, with a code comment crediting homecom_alt as the source of the format. `get()`/`put()` are unchanged.

### D3: Config flow goes OAuth-first; device id becomes a picker
Step order changes from `device_id → oauth` to `oauth → gateway picker`:
- After token exchange, call `GET /pointt-api/api/v1/gateways/` (client method `list_gateways()`, no `/resource` suffix).
- **1 gateway** → auto-select, skip the picker entirely.
- **>1 gateways** → selector listing `deviceId` + `deviceType`.
- **0 gateways or listing error** → fall through to the existing manual serial-entry form (network/ACL failures must not strand the user).
- Reauth flow is untouched: it already has the device id and only refreshes tokens.

*Why OAuth-first?* The listing requires a token. The old order existed only because the device id was needed to build nothing in OAuth — the authorize URL is device-independent — so the reorder is safe.

### D4: Boost goes native-first with staged probes, falling back to the workaround
*Probe of 2026-06-05 (see `boost-probe-notes.md`): `boostShortcut` is a writeable `boostShortcutStruct` — `[{"mode", "temperature", "duration", "zones": [1], "allowedZones": [1]}]` — i.e. the complete boost command in one resource; `boostMode` is `writeable: 1` at the device level, so the historical 403 is a cloud-route ACL only. Zone ids in the struct are integers (`1`), not `"zn1"`.*

`async_turn_on` attempts, in order, stopping at the first success:
1. `PUT /heatingCircuits/hc1/boostShortcut` with `[{"mode": "on", "temperature": <boostTemperature>, "duration": <boostDuration>, "zones": [1]}]` — the app's likely native trigger (the `"on"` enum is the one unconfirmed detail; adjust on a 4xx)
2. `PUT /heatingCircuits/hc1/boostZones` (current struct) then `PUT /heatingCircuits/hc1/boostMode = "on"` — direct route retry
3. **Fallback:** the existing manual-mode + local-timer workaround, byte-for-byte today's behavior

*(A bulk-write rung was considered and dropped during implementation: no community project has ever observed the bulk WRITE wire format, and the consented write probe confirmed the direct route's ACL is open — guessing write formats against a live heating system is unjustified. Spec updated to match.)*

Success criterion for native boost: the *next* coordinator refresh shows `boostMode == "on"` or `boostRemainingTime > 0`. On native success, no local timer is scheduled and `coordinator.boost_session` stays `None`; the remaining-time sensor reads Bosch's real countdown (its existing fallback branch). The probe result (which route worked, or none) is cached on the coordinator for the config entry's lifetime so subsequent toggles don't re-probe, and is surfaced in diagnostics.

*Pre-implementation investigation:* ✅ done (task 1.1) — see `boost-probe-notes.md` for full struct shapes, writeable flags, and the comfort-control constraint confirmations. Remaining cloud-side unknowns (gateway listing, bulk-read on RRC2, cloud read/write ACLs per rung) are listed there and resolve during implementation's first-toggle probe.

*Why staged probes instead of picking one?* We have one live device and three hypotheses. The staged ladder costs at most 3 extra PUTs once per entry lifetime and self-documents in diagnostics what the API accepted.

### D5: New entities ride existing platform patterns
All new entities are table-driven descriptions in `pointtapi_entities.py`, following `pointtapi-binary-sensors`' established pattern:
- `/notifications` → sensor on Gateway device; state = active notification count, `extra_state_attributes` = the raw notification list (dcode/ccode/timestamps). Path added to coordinator roots (cheap inside bulk).
- `/system/awayMode/enabled` → switch on Gateway device (string `"true"`/`"false"` ↔ bool, matching dump).
- `/dhwCircuits/dhw1/extraDhw` → switch on Hot Water Tank (`"on"`/`"off"`).
- `/dhwCircuits/dhw1/extraDhwDuration` → number on Hot Water Tank (15–2880 min, step 15, from dump's min/max/stepSize).
- `/dhwCircuits/dhw1/thermalDisinfect/time` → number (minute-of-day 0–1439); `weekDay` → select (Mo…Su); `lastResult` → diagnostic sensor.
- Entity registration in the respective platform modules; names via `strings.json` + `translations/`.

### D6: Credits are a first-class deliverable
- **README**: new "Acknowledgements / Credits" section naming [serbanb11/bosch-homecom-hass](https://github.com/serbanb11/bosch-homecom-hass) + [homecom_alt](https://github.com/serbanb11/homecom_alt) (bulk format, RRC2 endpoint map, issue #78 contributors — esp. @joddye2's CT200 dumps), [BassXT/buderus](https://github.com/BassXT/buderus) (PointT API groundwork), and [bosch-thermostat/bosch-thermostat-client-python](https://github.com/bosch-thermostat/bosch-thermostat-client-python) (the XMPP path this integration builds on).
- **Code comments**: every endpoint/format adopted from observation carries a short provenance comment at the definition site (client `bulk()`, gateway listing, boost probe ladder, new entity tables).
- **Docs**: `docs/pointtapi-api.md` documents the endpoints *we* use (bulk envelope, gateway listing, resource paths with observed types/writeable flags) with links to upstream sources — so future work doesn't re-derive this.

### D7: Version 1.0.0
`manifest.json` 0.33.0 → **1.0.0** (user-confirmed). Release notes must flag: config-flow step reorder (existing entries unaffected — no re-setup needed), bulk polling (visible as faster updates / fewer cloud requests), and that all new behavior falls back to 0.33 semantics on API failure.

## Risks / Trade-offs

- **[Bulk endpoint changes or disappears]** → per-cycle fallback to the sequential GET walk (D1); behavior degrades to v0.33, warning logged hourly.
- **[Bulk responses differ per deviceType — envelope observed mostly on RAC/K40]** → parse defensively; any envelope surprise triggers the same wholesale fallback. Unit tests pin the envelope from homecom_alt's implementation.
- **[Boost probes do nothing or mis-fire (e.g. boostZones write changes config silently)]** → probes run once, log every request/response at debug, and the final state check (D4) gates "native" mode; on ambiguity we stay on the workaround. Probe writes restricted to boost-prefixed paths only.
- **[Gateway listing returns unexpected shapes (multi-tenant accounts, other device types)]** → picker shows raw `deviceId`/`deviceType`; unknown shapes → manual-entry fallback (D3).
- **[Config-flow reorder breaks existing YAML/automation assumptions]** → only the *setup* flow changes; existing config entries, unique ids, and reauth are untouched.
- **[Rate limits: bulk POSTs still count]** → steady-state request count drops ~10×; we keep homecom_alt's observed safe ceiling (≤3 concurrent) by issuing bulk chunks sequentially.
- **[Trade-off] First refresh still does the full GET walk** → acceptable: it's once per (re)load and is the price of installation-adaptive discovery.

## Migration Plan

1. Land client `bulk()` + coordinator integration behind the automatic fallback (no flag needed — fallback *is* the old code path).
2. Land config-flow reorder + discovery; manual entry remains reachable.
3. Land new entities (additive only — no renames, no unique-id changes).
4. Land boost probe ladder; default state before first probe = workaround (today's behavior).
5. Docs + credits + `manifest.json` → 1.0.0; tag release.
Rollback: revert tag; no stored-data migrations exist in this change (probe cache is in-memory, config entry schema unchanged).

## Open Questions

- ~~What are `boostShortcut`/`boostZones` types, enums, and `writeable` flags on the live CT200?~~ **Resolved 2026-06-05** (XMPP probe, `boost-probe-notes.md`): `boostShortcutStruct` / `boostZoneStruct`, both `writeable: 1`; integer zone ids; only the `mode` "on"-enum remains unconfirmed.
- ~~Do PUT writes pass the cloud ACL?~~ **Resolved 2026-06-05** (user-consented no-op write probe): direct cloud PUTs to `boostMode`, `boostShortcut`, and `boostZones` all return **204** — the historical 403 is gone; Bosch relaxed the ACL. The probe ladder stays for resilience, but rung 1 is expected to succeed. Only the `mode` "on" enum / activation semantics remain to confirm at the first real toggle. (Bulk-write support untested and likely unneeded.)
- ~~Does `GET /gateways/` include human-readable names?~~ **Resolved 2026-06-05**: returns `[{"deviceId", "deviceType"}]` only — picker shows id + type. Bulk read on RRC2 also confirmed working (envelope as documented), and cloud reads of all boost resources pass — they are in `coordinator.data` already.
- Cloud `/notifications` key: homecom_alt reads `values`, XMPP returns `value` — implementation must read both (spec updated accordingly).
