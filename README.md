# Bosch Thermostat — Home Assistant Custom Component (Fork)

A fork of [@pszafer's bosch-thermostat integration](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component) with an added **POINTTAPI cloud path** for Bosch EasyControl devices (CT200, EasyControl 7).

---

> ## 🧪 v1.0.0 is out — testers wanted!
>
> This release overhauls the cloud path: **bulk polling** (one poll = a few requests instead of ~190),
> **gateway auto-discovery** in setup, **native boost** (real device boost with server-side countdown —
> no more workaround), plus away mode, extra hot water, and thermal-disinfect controls.
>
> It's verified against my own CT200, but yours may differ (firmware, zones, solar, DHW type).
> If you run an EasyControl, **please try it and tell me what you find** — both successes and breakage:
>
> - 🐛 **Something broke?** → [Open a bug report](https://github.com/CaseyRo/ha_bosch/issues/new?template=bug_report.yml) — the form walks you through exactly what I need (diagnostics file, debug log, your setup)
> - ✅ **Works fine?** → [Say so in the v1.0.0 feedback thread (#9)](https://github.com/CaseyRo/ha_bosch/issues/9) — device model, firmware, and which features you used is enough
> - 📋 **How to capture the right info** → see [Testing & reporting](#testing--reporting) below
>
> Every report makes the next release better. Thank you! 🙏

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
3. Sign in with your Bosch/SingleKey ID account (OAuth2 with PKCE)
4. Your gateway is **discovered automatically** from your Bosch account — with one device it's selected for you; with several you pick from a list. Manual serial entry remains available as a fallback if the listing is unavailable.

Token refresh is automatic. If your session expires, HA triggers a re-authentication flow — no need to delete and re-add the integration.

### Entities

| Platform | Entity | Notes |
|---|---|---|
| Climate | Zone zn1 | Room temp, heating setpoint, Heat/Off mode |
| Water heater | DHW1 | Hot water temp, target temp, operation mode (Auto/Off/On) |
| **Switch** | Boost | One-tap boost — uses the device's **native boost** when the cloud allows it (server-side countdown, survives HA restarts), with an automatic manual-mode fallback |
| Switch | Auto firmware update | Enable/disable automatic firmware updates |
| Switch | Notification light | Gateway LED on/off |
| Switch | Thermal disinfect | DHW legionella protection cycle |
| Switch | Away mode | Account-wide away mode on/off |
| Switch | Extra hot water | One-shot DHW boost run |
| **Number** | Boost temperature | Target temp during boost (5–30 °C) |
| Number | Boost duration | How long boost runs (0.5–24 h) |
| Number | Max supply temperature | Upper heating circuit limit (25–90 °C) |
| Number | Min supply temperature | Lower heating circuit limit (10–90 °C) |
| Number | Night setback threshold | Outdoor temp below which night setback activates (5–30 °C) |
| Number | Summer/winter threshold | Outdoor temp for summer/winter switchover (10–30 °C) |
| Number | Room influence | How much room sensor affects supply temp (0–3) |
| Number | Temperature calibration offset | Room sensor offset correction (-5–5 °C) |
| Number | Annual gas goal | Energy target for the year (kWh) |
| Number | Extra hot water duration | Length of an extra-DHW run (15–2880 min) |
| Number | Thermal disinfect time | Minute-of-day the disinfect cycle starts (0–1439) |
| **Select** | Zone mode | `clock` (scheduled) / `manual` |
| Select | PIR sensitivity | Motion sensor sensitivity: `high` / `medium` / `low` |
| Select | Summer/winter mode | `automatic` (by threshold) / `manual` |
| Select | Night switch mode | `automatic` / `reduced` |
| Select | Thermal disinfect weekday | Day of week for the disinfect cycle |
| **Sensor** | Outdoor temperature | Outside temp from device |
| Sensor | Indoor humidity | Room humidity (%) |
| Sensor | Valve position | Current valve opening (%) |
| Sensor | System pressure | Heating system pressure (bar) |
| Sensor | Gas heating today | CH gas usage today (kWh) |
| Sensor | Gas hot water today | DHW gas usage today (kWh) |
| Sensor | Gas total today | Total gas usage today (kWh) |
| Sensor | WiFi signal strength | Device WiFi RSSI (dBm) |
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
| Sensor | Notifications | Active cloud alert count, raw entries as attributes |
| Sensor | Thermal disinfect last result | Outcome of the last disinfect cycle |

### Under the hood
- **Bulk polling** — steady-state polls batch all discovered resource reads (188 paths on a typical CT200) into a handful of bulk POSTs against `pointt-api`'s bulk endpoint instead of one GET per path, with automatic per-cycle fallback to sequential GETs if the bulk route ever misbehaves (endpoint format credit: [homecom_alt](https://github.com/serbanb11/homecom_alt), see `docs/pointtapi-api.md`)
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

### HACS — custom repository (recommended)

This integration is distributed as a **HACS custom repository** (it is not in the HACS default list):

1. Make sure [HACS](https://hacs.xyz) is installed.
2. In Home Assistant: **HACS** → top-right **⋮** → **Custom repositories**.
3. **Repository:** `https://github.com/CaseyRo/ha_bosch` — **Type:** `Integration` — click **Add**.
4. Search HACS for **Bosch thermostat ha-pro**, open it, and click **Download**.
5. **Restart Home Assistant.**
6. **Settings → Devices & Services → Add Integration →** search **Bosch**.

HACS then notifies you of updates like any other integration.

### Manual install

1. Download the latest release, or copy this repo.
2. Copy `custom_components/bosch/` into your Home Assistant `config/custom_components/`.
3. **Restart Home Assistant**, then add via **Settings → Devices & Services → Add Integration → Bosch**.

### Upgrading from the original integration

This is a drop-in replacement for `bosch-thermostat/home-assistant-bosch-custom-component`. Your existing config entry and XMPP/HTTP setups are fully preserved — new entities only appear for POINTTAPI entries.

1. Back up your existing `config/custom_components/bosch/` folder
2. Install this fork via HACS or manually (see above), replacing the existing `bosch` folder
3. Restart Home Assistant — existing entities carry over, new ones appear automatically

### Keeping up to date

If you installed via HACS, you'll be notified of new releases automatically — open the integration in HACS and click **Download**, then restart HA. For manual installs, copy the latest `custom_components/bosch/` over your existing folder and restart HA.

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

## Testing & reporting

Good reports get fixed fast. Here's how to capture exactly what's needed:

### 1. Grab the diagnostics file (always — it's the single most useful artifact)

**Settings → Devices & Services → Bosch → ⋮ (three-dot menu) → Download diagnostics**

Credentials are automatically redacted. The file contains every resource path your device serves
(`coordinator_data`) and — for boost issues — the `boost_probe_result` showing which native-boost
route your device accepted. Attach the `.json` to your issue.

### 2. Enable debug logging (for anything intermittent or polling-related)

**Settings → Devices & Services → Bosch → Enable debug logging**, reproduce the problem,
then disable it — HA offers the captured log for download. Or via `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.bosch: debug
```

In a healthy cloud setup you'll see one of these per 60s poll:

```
POINTTAPI bulk steady state: 188/188 paths returned     ← bulk polling working
POINTTAPI bulk fetch failed (...); falling back ...     ← bulk degraded (still works, please report!)
```

### 3. Tell me about your setup

- Integration version (Settings → Devices & Services → Bosch) and HA version
- Connection type: **Cloud (POINTTAPI)** or **Local (XMPP)** — most new features are cloud-path only
- Device: CT200 / EasyControl 7, firmware version (it's a sensor on the Gateway device)
- System quirks: number of zones, solar yes/no, instant vs tank hot water

### 4. Describe the problem

- What you did (e.g. "flipped the Boost switch")
- What you expected, and what actually happened
- When it started (after which version / change)

[Open a bug report](https://github.com/CaseyRo/ha_bosch/issues/new?template=bug_report.yml) — the
form has fields for all of the above. **Positive reports are just as valuable**: "v1.0.0 works on my
CT200 with 2 zones, native boost picked the boostShortcut route" tells me the probe ladder
generalizes beyond my own device.

> ⚠️ Never paste your access token, refresh token, or OAuth callback URL into an issue.
> The diagnostics download redacts these automatically — use it instead of hand-copied data.

## Support this project

If this integration is useful to you, consider buying me a coffee:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=flat&logo=buy-me-a-coffee)](https://buymeacoffee.com/caseyberlin)

## Credits

All credit for the original integration goes to [@pszafer](https://github.com/pszafer) and the contributors to the upstream projects — see the attribution note at the top of this README. This fork adds only the POINTTAPI cloud path; everything else is their work.

- POINTTAPI path and EasyControl cloud support by [@CaseyRo](https://github.com/CaseyRo)

## Acknowledgements

The POINTTAPI path stands on the shoulders of other open-source efforts that reverse-engineered the Bosch cloud APIs:

- **[serbanb11/bosch-homecom-hass](https://github.com/serbanb11/bosch-homecom-hass)** and its library **[homecom_alt](https://github.com/serbanb11/homecom_alt)** — documented the pointt-api surface across device types, including the bulk endpoint wire format, the account-level gateway listing, and the RRC2 (CT200) endpoint set. Special thanks to **@joddye2**, whose live CT200 resource dumps in [bosch-homecom-hass#78](https://github.com/serbanb11/bosch-homecom-hass/issues/78) revealed `boostShortcut`, `boostZones`, and the writeable flags that made native boost support possible.
- **[BassXT/buderus](https://github.com/BassXT/buderus)** — early groundwork on the PointT API for MX300/K30 gateways (heat-source endpoints, SingleKey PKCE flow notes).
- **[bosch-thermostat/bosch-thermostat-client-python](https://github.com/bosch-thermostat/bosch-thermostat-client-python)** — the XMPP client this entire integration builds on, whose EasyControl device database also enabled our local-protocol verification probes.

The endpoints this integration uses, with observed types and writeable flags, are documented in [`docs/pointtapi-api.md`](docs/pointtapi-api.md) so the knowledge stays shared.
