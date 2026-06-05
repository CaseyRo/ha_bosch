## Why

Research into the HomeCom Easy ecosystem (June 2026) — which now supports our CT200/RRC2 hardware on the same pointt-api backend and OAuth client we use — surfaced documented API capabilities we don't exploit: a bulk read/write endpoint, account-level gateway listing, the `/notifications` resource, and several writable resources confirmed by a real CT200 dump (`serbanb11/bosch-homecom-hass` issue #78). Adopting them cuts our poll from ~40-50 sequential GETs to a handful of bulk POSTs (the community lib warns concurrency >3 hits internal rate limits), removes the manual serial-entry config step, adds alert visibility, and may let us replace the local-timer boost workaround with the device's native boost — the dump revealed `boostShortcut` and `boostZones` resources we've never probed.

## What Changes

- **Bulk polling**: `PoinTTAPIDataUpdateCoordinator` fetches its resource set via `POST /pointt-api/api/v1/bulk` (≤30 paths per call, paths without the `/resource` prefix) instead of ~40-50 sequential GETs per 60s poll. Per-path GET remains as fallback when bulk fails, and reference discovery (which paths exist) still uses the reference walk on first refresh.
- **Gateway auto-discovery**: config flow calls `GET /pointt-api/api/v1/gateways/` after OAuth (scope `pointt.gateway.list` is already granted) and presents a gateway picker — auto-selecting when the account has exactly one. Requires reordering the POINTTAPI flow steps: OAuth before device-id. Manual serial entry remains as fallback when the listing fails or is empty.
- **Notifications sensor**: new sensor reading `/notifications` — count as state, alert entries as attributes — giving the POINTTAPI path parity with the XMPP path's `NotificationSensor`.
- **Away mode switch**: `/system/awayMode/enabled` (confirmed `writeable: 1`) as a switch on the Gateway device.
- **Extra hot water controls**: `/dhwCircuits/dhw1/extraDhw` switch (`writeable: 1`) and `/dhwCircuits/dhw1/extraDhwDuration` number (`writeable: 1`, 15–2880 min, step 15) on the Hot Water Tank device.
- **Thermal disinfect config**: `/dhwCircuits/dhw1/thermalDisinfect/time` (number, minute-of-day 0–1439), `.../weekDay` (select, Mo–Su), `.../lastResult` (diagnostic sensor) — completing the existing thermal-disinfect switch.
- **Boost: native-first with fallback**: investigate the never-probed `/heatingCircuits/hc1/boostShortcut` and `/boostZones` resources (already fetched by our reference walk — values visible in diagnostics) plus bulk-write as an alternative PUT route for the 403-blocked `boostMode`. The boost switch attempts native boost activation first and falls back to the existing manual-mode + local-timer workaround on failure. If native boost works, `boostRemainingTime` becomes a real server-side countdown instead of the synthetic one.

## Capabilities

### New Capabilities
- `pointtapi-bulk-polling`: coordinator data acquisition via the bulk endpoint — request batching, `/resource`-prefix stripping, per-path status handling in the bulk response envelope, fallback to sequential GETs.
- `pointtapi-gateway-discovery`: account gateway listing in the config flow — OAuth-first step order, picker / auto-select / manual-entry fallback.
- `pointtapi-notifications`: the `/notifications` alert sensor.
- `pointtapi-comfort-controls`: away-mode switch, extra-DHW switch + duration number, thermal-disinfect time/weekday/lastResult entities.

### Modified Capabilities
- `pointtapi-boost-behavior`: turn-on SHALL attempt native boost activation (boostZones/boostShortcut/boostMode, direct PUT then bulk write) before falling back to the manual-mode workaround; the remaining-time sensor SHALL prefer the Bosch-reported countdown when a native boost session is active.

(`pointtapi-device-partition` was evaluated and needs no delta: its existing gateway catch-all and `/dhwCircuits/` prefix rules already route every new entity correctly.)

## Impact

- `pointtapi_coordinator.py` — bulk fetch path (largest change; touches every POINTTAPI entity's data source, though `coordinator.data` shape stays `{path: response}` so entities are unaffected)
- `pointtapi_client.py` — new `bulk()` method; `get()`/`put()` unchanged
- `config_flow.py` — POINTTAPI step reorder (OAuth → gateway pick), new listing call, reauth unaffected
- `pointtapi_entities.py` — new sensor/switch/number/select descriptions; boost switch turn-on path
- `sensor/__init__.py`, `switch.py`, `number.py`, `select.py` — entity registration
- `strings.json`, `translations/` — new entity names and config-flow strings
- `unittests/` — bulk envelope parsing, fallback behavior, config-flow reorder, boost native-first logic
- Risk note: bulk endpoint and write semantics are observed/unofficial; every adoption keeps the current behavior as fallback, so a Bosch-side regression degrades gracefully to today's behavior.
