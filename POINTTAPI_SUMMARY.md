# POINTTAPI cloud path for EasyControl — summary of additions

Full fork with all changes: **https://github.com/CaseyRo/ha_bosch**

I've been working on a full cloud-API integration path for EasyControl devices using the POINTTAPI (`pointt-api.bosch-thermotechnology.com`) endpoint. This runs alongside the existing XMPP/HTTP paths without touching them. Here's what's in place:

## New files

- **`pointtapi_client.py`** — HTTP client for the POINTTAPI REST API (GET/PUT with auto token refresh)
- **`pointtapi_oauth.py`** — OAuth2 with PKCE flow against Bosch SingleKey ID; token exchange + refresh
- **`pointtapi_coordinator.py`** — `DataUpdateCoordinator` that polls ~6 root paths + references every 60s, with `asyncio.timeout(120)` and proper error handling
- **`pointtapi_entities.py`** — All POINTTAPI entities (see below)
- **`diagnostics.py`** — `async_get_config_entry_diagnostics` with credential redaction

## Config flow

New steps for POINTTAPI: `choose_type` → `easycontrol_protocol` → `pointtapi_device_id` (serial) → `pointtapi_oauth_open` (show login link) → `pointtapi_oauth` (paste callback URL) → token exchange → `create_entry`.

Reauth flow works end-to-end: 401/403 raises `ConfigEntryAuthFailed` → HA triggers reauth → user re-authenticates → `async_update_reload_and_abort` with `data_updates=` updates tokens in place.

Entries get `async_set_unique_id` (device serial) + `_abort_if_unique_id_configured` to prevent duplicates.

## Entities

| Platform | Entity | Details |
|---|---|---|
| `climate` | Zone zn1 | Current/target temp, HEAT/OFF mode via `/zones/zn1/` and `/heatingCircuits/hc1/control` |
| `water_heater` | DHW1 | Current/target temp, operation mode (Auto/Off/On) mapped from API values (`ownprogram`→Auto) |
| `switch` | Boost | One-tap toggle for `/heatingCircuits/hc1/boostMode` |
| `number` | Boost temperature | 5–30 °C, 0.5° step |
| `number` | Boost duration | 0.5–24 h, 0.5 h step |
| `sensor` | Outdoor temperature, indoor humidity, valve position, system pressure, WiFi RSSI, firmware update state, boost remaining time | Standard `SensorEntityDescription` with translation keys, device classes, proper units |

All POINTTAPI entities use `CoordinatorEntity` with `_handle_coordinator_update()`, `has_entity_name = True`, and 2-tuple device identifiers with `via_device`.

## Tests & CI

- 58 unit tests across 4 files (OAuth helpers, HTTP client, coordinator, diagnostics)
- CI runs ruff + pytest on Python 3.12/3.13

## What's not touched

The existing XMPP/HTTP path, `bosch-thermostat-client` library usage, and all non-POINTTAPI entities are completely unchanged.

---

If this is useful, feel free to [buy me a coffee](https://buymeacoffee.com/caseyberlin).
