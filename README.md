# Bosch Thermostat — Home Assistant Custom Component (Fork)

A fork of [@pszafer's bosch-thermostat integration](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component) with an added **POINTTAPI cloud path** for Bosch EasyControl devices (CT200, EasyControl 7).

## Why this fork exists

The original integration supports EasyControl devices over XMPP, which works well on the local network. But for many users — especially those with strict network setups or who want remote access — the XMPP path can be unreliable or hard to configure.

Bosch exposes a cloud REST API (POINTTAPI) at `pointt-api.bosch-thermotechnology.com` that the official EasyControl mobile app uses. This fork reverse-engineers that API and adds it as a second protocol path, giving EasyControl users a cloud-based alternative that "just works" with the same Bosch account they already use in the app.

The original XMPP/HTTP code is completely untouched — both paths coexist and you pick one during setup.

## What the POINTTAPI path adds

### Setup
The config flow walks you through:
1. Choose "EasyControl" device type
2. Pick "Cloud login" as connection type
3. Enter your device serial number
4. Sign in with your Bosch/SingleKey ID account (OAuth2 with PKCE)

Token refresh is automatic. If your session expires, HA triggers a re-authentication flow — no need to delete and re-add the integration.

### Entities

| Platform | Entity | What it does |
|---|---|---|
| Climate | Zone zn1 | Room temperature, heating setpoint, Heat/Off mode |
| Water heater | DHW1 | Hot water temp, target temp, operation mode (Auto/Off/On) |
| Switch | Boost | One-tap boost mode toggle |
| Number | Boost temperature | Target temperature during boost (5–30 °C) |
| Number | Boost duration | How long boost runs (0.5–24 hours) |
| Sensor | Outdoor temperature | Outside temp from the device |
| Sensor | Indoor humidity | Room humidity reading |
| Sensor | Valve position | Current valve opening (%) |
| Sensor | System pressure | Heating system pressure (bar) |
| Sensor | WiFi signal strength | Device WiFi RSSI (dBm) |
| Sensor | Firmware update state | Whether an update is available |
| Sensor | Boost remaining time | Minutes left on active boost |

### Under the hood
- **Coordinator-based polling** — all data fetched every 60 seconds through a `DataUpdateCoordinator`, not per-entity polling
- **OAuth2 with PKCE** — same auth flow the Bosch app uses, with automatic token refresh
- **Proper error handling** — 401/403 triggers HA's reauth flow, timeouts and network errors surface as `UpdateFailed`
- **Diagnostics** — full diagnostic dump available from the HA integrations page (credentials are redacted)
- **HA best practices** — `CoordinatorEntity` pattern, `has_entity_name`, `NumberEntityDescription` dataclasses, unique IDs to prevent duplicates

## Installation

Copy this folder to `custom_components/bosch` in your Home Assistant config directory (or install via HACS as a custom repository), then restart HA.

### Requirements
- Home Assistant 2024.1+
- A Bosch EasyControl device
- A Bosch account (the one you use in the EasyControl app)

## Development

```bash
# Lint
ruff check custom_components/bosch

# Run tests
python3 -m pytest --tb=short -q unittests

# Install dev dependencies
pip install bosch-thermostat-client==0.28.2 tzdata ruff
```

CI runs ruff + pytest on Python 3.12 and 3.13.

## Support this project

If this integration is useful to you, consider buying me a coffee:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=flat&logo=buy-me-a-coffee)](https://buymeacoffee.com/CaseyRo)

## Credits

- Original integration by [@pszafer](https://github.com/pszafer) and contributors
- POINTTAPI path and EasyControl cloud support by [@CaseyRo](https://github.com/CaseyRo)
