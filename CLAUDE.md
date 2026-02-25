# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Lint:**
```bash
ruff check custom_components/bosch
```

**Run tests:**
```bash
python3 -m pytest --tb=short -q unittests
```

**Run a single test:**
```bash
python3 -m pytest --tb=short unittests/test_<name>.py
```

**Test EasyControl XMPP connectivity (standalone script):**
```bash
uv run --with bosch-thermostat-client==0.28.2 python test_easycontrol_connection.py
```

**Install dependencies:**
```bash
pip install bosch-thermostat-client==0.28.2 tzdata ruff
```

CI runs ruff + pytest on Python 3.12 and 3.13 via `.github/workflows/ci.yaml`.

## Architecture Overview

This is a Home Assistant custom component (`domain: bosch`) that integrates Bosch thermostats. It supports **two fully separate protocol paths** that share only the config flow entry point and some constants.

### Dual Protocol Paths

**Path 1 — XMPP/HTTP (traditional, local):**
- Uses the `bosch-thermostat-client` library (pinned at `0.28.2` in `manifest.json`)
- Entities pull state from a `bosch_object` and receive updates via HA dispatcher signals (e.g. `SIGNAL_CLIMATE_UPDATE_BOSCH`)
- Update loop: `thermostat_refresh()` in `__init__.py` → `component_update()` per platform → `async_dispatcher_send(signal)` → entities re-read from `bosch_object`
- Base entity class: `BoschEntity` in `bosch_entity.py`
- Supported device types: `NEFIT`, `IVT`, `IVT_MBLAN`, `EASYCONTROL`

**Path 2 — POINTTAPI (cloud JSON API, EasyControl only):**
- Custom HTTP client (`pointtapi_client.py`) hitting `https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways/{device_id}/resource/`
- OAuth with PKCE (`pointtapi_oauth.py`) — access + refresh tokens stored in config entry data; `ensure_valid_token()` auto-refreshes before every request
- `PoinTTAPIDataUpdateCoordinator` (`pointtapi_coordinator.py`) polls ~6 root paths + one level of references every 60s, caching results as a `{path: response}` dict in `coordinator.data`
- Entities are `CoordinatorEntity` subclasses (`pointtapi_entities.py`) that read from `coordinator.data` in `_handle_coordinator_update()`
- 401/403 raises `ConfigEntryAuthFailed` → triggers the reauth flow in `config_flow.py` without deleting the entry

### Entry Point (`__init__.py`)

`async_setup_entry()` creates a `BoschGatewayEntry` which detects `CONF_PROTOCOL` from `entry.data`:
- If `POINTTAPI`: creates client + coordinator, calls `async_config_entry_first_refresh()`, forwards platforms
- If XMPP/HTTP: creates `bosch_thermostat_client` gateway in an executor (SSL is blocking), registers signals, sets up `async_track_time_interval` update loops

### Config Flow (`config_flow.py`)

Steps for POINTTAPI: `choose_type` → `easycontrol_protocol` → `pointtapi_device_id` (serial without dashes) → `pointtapi_oauth_open` (show login URL) → `pointtapi_oauth` (paste callback URL) → exchange code for tokens → `create_entry`.

Steps for XMPP/HTTP: `choose_type` → protocol → credentials form → `configure_gateway()` in executor (validates connection, extracts UUID) → `create_entry`.

Tokens and all credentials are stored in `entry.data`, not `entry.options`.

### Sensor Platform (`sensor/`)

`sensor/__init__.py` routes each sensor to a class based on its `.kind`:
- `RECORDING` → `RecordingSensor` (1-hour averaging)
- `ENERGY` / `ECUS_RECORDING` → `EnergySensor` (with HA statistics API)
- `REGULAR` → `BoschSensor`
- `"notification"` → `NotificationSensor`
- Circuit sensors (DHW, HC, SC, ZN, DV) → `CircuitSensor`
- POINTTAPI → `BoschPoinTTAPISensorEntity` (6 curated paths: outdoor temp, humidity, valve position, pressure, RSSI, update state)

### Constants (`const.py`)

All platform signals, circuit names (`DHW`, `HC`, `SC`, `ZN`, `DV`), protocol identifiers (`POINTTAPI = "pointtapi"`), and config entry keys (`UUID`, `ACCESS_TOKEN`, etc.) live here. Import from here rather than defining inline.

### Key Patterns to Follow

- **Blocking operations** (SSL, gateway init): always wrap in `hass.async_add_executor_job()`
- **New XMPP/HTTP entities**: subscribe to dispatcher signal in `async_added_to_hass()` via `self.async_on_remove(async_dispatcher_connect(...))`
- **New POINTTAPI entities**: extend `CoordinatorEntity`, implement `_handle_coordinator_update()`, read paths from `self.coordinator.data`
- **Device identifiers**: use 2-tuples `(DOMAIN, f"{uuid}_{sub_id}")` with `via_device=(DOMAIN, uuid)` for child devices
- **Entity naming**: use `_attr_has_entity_name = True` and `_attr_name = None` (modern HA pattern, already used by POINTTAPI entities)
- **Auth failures (POINTTAPI)**: raise `ConfigEntryAuthFailed` — do not catch and swallow 401/403

## Version & Dependency Notes

- Current integration version: `0.28.6` (in `manifest.json` — bump this on releases)
- `bosch-thermostat-client` is not used by and does not support POINTTAPI; the POINTTAPI path is entirely custom
- `iot_class` is `cloud_polling` (covers both paths; XMPP is technically local but the manifest reflects the primary EasyControl cloud use case)
