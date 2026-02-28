# Bosch Thermostat — Home Assistant Custom Component (Fork)

A fork of [@pszafer's bosch-thermostat integration](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component) with an added **POINTTAPI cloud path** for Bosch EasyControl devices (CT200, EasyControl 7).

---

> **A note on attribution**
>
> This is a personal fork built for my own use and shared in case it helps others.
> It is **not** affiliated with Bosch, nor is it meant to replace or compete with the
> excellent work by the original maintainers.
>
> The foundation of this integration — the XMPP/HTTP path, device handling, and the
> `bosch-thermostat-client` Python library — was built by [@pszafer](https://github.com/pszafer)
> and the contributors to:
> - **[home-assistant-bosch-custom-component](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component)** — the HA integration this fork is based on
> - **[bosch-thermostat-client-python](https://github.com/bosch-thermostat/bosch-thermostat-client-python)** — the Python client library that inspired the protocol understanding behind the POINTTAPI cloud path
>
> All credit for the original integration goes to them. If you don't need the POINTTAPI cloud
> path, please use the original — it is actively maintained and has a broader community.

---

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

| Platform | Entity | Notes |
|---|---|---|
| Climate | Zone zn1 | Room temp, heating setpoint, Heat/Off mode |
| Water heater | DHW1 | Hot water temp, target temp, operation mode (Auto/Off/On) |
| **Switch** | Boost | One-tap boost mode toggle |
| Switch | Auto firmware update | Enable/disable automatic firmware updates |
| Switch | Notification light | Gateway LED on/off |
| Switch | Thermal disinfect | DHW legionella protection cycle |
| **Number** | Boost temperature | Target temp during boost (5–30 °C) |
| Number | Boost duration | How long boost runs (0.5–24 h) |
| Number | Max supply temperature | Upper heating circuit limit (25–90 °C) |
| Number | Min supply temperature | Lower heating circuit limit (10–90 °C) |
| Number | Night setback threshold | Outdoor temp below which night setback activates (5–30 °C) |
| Number | Summer/winter threshold | Outdoor temp for summer/winter switchover (10–30 °C) |
| Number | Room influence | How much room sensor affects supply temp (0–3) |
| Number | Temperature calibration offset | Room sensor offset correction (-5–5 °C) |
| Number | Annual gas goal | Energy target for the year (kWh) |
| **Select** | Zone mode | `clock` (scheduled) / `manual` |
| Select | PIR sensitivity | Motion sensor sensitivity: `high` / `medium` / `low` |
| Select | Summer/winter mode | `automatic` (by threshold) / `manual` |
| Select | Night switch mode | `automatic` / `reduced` |
| **Sensor** | Outdoor temperature | Outside temp from device |
| Sensor | Indoor humidity | Room humidity (%) |
| Sensor | Valve position | Current valve opening (%) |
| Sensor | System pressure | Heating system pressure (bar) |
| Sensor | Gas heating today | CH gas usage today (kWh) |
| Sensor | Gas hot water today | DHW gas usage today (kWh) |
| Sensor | Gas total today | Total gas usage today (kWh) |
| Sensor | WiFi signal strength | Device WiFi RSSI (dBm) — disabled by default |
| Sensor | Firmware update state | Whether an update is available |
| Sensor | Boost remaining time | Minutes left on active boost |
| Sensor | Blocking error | Active blocking fault code |
| Sensor | Locking error | Active locking fault code |
| Sensor | Maintenance request | Maintenance due flag |
| Sensor | Display code | Current display code |
| Sensor | Cause code | Current cause code |
| Sensor | Firmware version | Installed firmware version string |
| Sensor | Supply temp setpoint | Current calculated supply temp target (°C) |
| Sensor | Boiler power | Current boiler power output (%) |

### Under the hood
- **Coordinator-based polling** — all data fetched every 60 seconds through a `DataUpdateCoordinator`, not per-entity polling
- **OAuth2 with PKCE** — same auth flow the Bosch app uses, with automatic token refresh
- **Proper error handling** — 401/403 triggers HA's reauth flow, timeouts and network errors surface as `UpdateFailed`
- **Diagnostics** — full diagnostic dump available from the HA integrations page (credentials are redacted)
- **HA best practices** — `CoordinatorEntity` pattern, `has_entity_name`, `NumberEntityDescription` dataclasses, unique IDs to prevent duplicates

## Installation

### Requirements
- Home Assistant 2024.1+
- A Bosch EasyControl device (CT200, EasyControl 7)
- A Bosch/SingleKey ID account (the one you use in the EasyControl app)

### Fresh install

In your HA config directory, clone the repo and symlink the integration:

```bash
cd config
git clone https://github.com/CaseyRo/ha_bosch.git ha_bosch
ln -s ../ha_bosch/custom_components/bosch custom_components/bosch
```

Then restart Home Assistant and go to **Settings → Devices & Services → Add Integration** → search for **Bosch**.

**Via HACS:** add `https://github.com/CaseyRo/ha_bosch` as a custom repository (category: Integration), install it, then restart.

### Upgrading from the original integration

This is a drop-in replacement for `bosch-thermostat/home-assistant-bosch-custom-component`. Your existing config entry and XMPP/HTTP setups are fully preserved — new entities only appear for POINTTAPI entries.

1. Back up your existing `config/custom_components/bosch/` folder
2. Delete it, then clone this repo and symlink (see above)
3. Restart Home Assistant — existing entities carry over, new ones appear automatically

### Keeping up to date

```bash
cd config/ha_bosch && git pull
```

Then restart HA.

### Removing the integration

1. In HA, go to **Settings → Devices & Services**, find **Bosch**, click the three-dot menu → **Delete**
2. Restart Home Assistant
3. Delete the `config/custom_components/bosch` folder (or the cloned repo if installed manually)

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

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=flat&logo=buy-me-a-coffee)](https://buymeacoffee.com/caseyberlin)

## Credits

All credit for the original integration goes to [@pszafer](https://github.com/pszafer) and the contributors to the upstream projects — see the attribution note at the top of this README. This fork adds only the POINTTAPI cloud path; everything else is their work.

- POINTTAPI path and EasyControl cloud support by [@CaseyRo](https://github.com/CaseyRo)
