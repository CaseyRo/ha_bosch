# Bosch Thermostat — Home Assistant Custom Component (Fork)

A fork of [@pszafer's bosch-thermostat integration](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component) with an added **POINTTAPI cloud path** for Bosch EasyControl devices (CT200, EasyControl 7).

---

> ## v1.3.1 current status
>
> The integration has moved well beyond the initial v1.0.0 rollout.
> Current POINTTAPI behavior includes native boost support, bulk polling with fallback,
> gateway auto-discovery, richer diagnostics, and broader dynamic entity discovery
> (multi-zone schedule entities, thermostat-valve entities, optional open-window and
> energy surfaces when advertised by the appliance).
>
> If you find a regression or device-specific quirk, please report it with diagnostics:
>
> - 🐛 **Bug report** → [Open an issue](https://github.com/CaseyRo/ha_bosch/issues/new?template=bug_report.yml)
> - 📋 **Capture details first** → see [Testing & reporting](#testing--reporting) below

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

**Getting the login code (the "cannot open page" step).** After you sign in at step 3, your browser tries to redirect to `com.bosch.tt.dashtt.pointt://app/login?code=…` — the Bosch *app's* deep link, which a desktop browser can't open. You'll see a **"cannot open page" or blank screen, and that's expected**: the login worked, and the code you need is sitting in that address. Two ways to grab it:

- **[SingleKey-Code-Catcher](https://github.com/Tozzi89/SingleKey-Code-Catcher)** — a Firefox extension that reads the code out of the redirect and gives you one-click copy. Easiest path.
- **Browser DevTools** — open **F12 → Network** before you finish logging in, then find the `…/app/login?code=…` request and copy it. Firefox also shows the full address right on the error page.

Paste the whole callback URL **or** just the `code` value into the final step — either is accepted.

Token refresh is automatic. If your session expires, HA triggers a re-authentication flow — no need to delete and re-add the integration.

### Entities (POINTTAPI, v1.3.1)

Entity creation is partly dynamic. What you see depends on what your appliance advertises in its resource references.

#### Chaudiere

| Platform | Entity | Translation key | Resource path | Scope |
|---|---|---|---|---|
| Sensor | System pressure | system_pressure | /system/appliance/systemPressure | 1 per boiler |
| Sensor | Blocking error | blocking_error | /system/appliance/blockingError | 1 per boiler |
| Sensor | Locking error | locking_error | /system/appliance/lockingError | 1 per boiler |
| Sensor | Maintenance request | maintenance_request | /system/appliance/maintenanceRequest | 1 per boiler |
| Sensor | Display code | display_code | /system/appliance/displayCode | 1 per boiler |
| Sensor | Cause code | cause_code | /system/appliance/causeCode | 1 per boiler |
| Sensor | Appliance status | appliance_status | /system/appliance/status (computed from appliance codes) | 1 per boiler |
| Sensor | Actual supply temperature | actual_supply_temperature | /heatSources/actualSupplyTemperature | 1 per boiler |
| Sensor | Return temperature | return_temperature | /heatSources/returnTemperature | 1 per boiler |
| Sensor | Actual modulation | actual_modulation | /heatSources/actualModulation | 1 per boiler |
| Sensor | Heat demand type | heat_demand_type | /heatSources/flameIndication | 1 per boiler |
| Sensor | Boiler ignition starts | boiler_ignition_starts | /heatSources/numberOfStarts | 1 per boiler |
| Binary sensor | Burner flame | burner_flame | /heatSources/flameIndication (resolved via actualModulation) | 1 per boiler |
| Binary sensor | Refill needed | refill_needed | /heatSources/refillNeeded | 1 per boiler |

#### Thermostat (gateway EasyControl)

| Platform | Entity | Translation key | Resource path | Scope |
|---|---|---|---|---|
| Switch | Auto firmware update | auto_firmware_update | /gateway/update/enabled | 1 per gateway |
| Switch | Notification light | notification_light | /gateway/notificationLight/enabled | 1 per gateway |
| Switch | Away mode | away_mode | /system/awayMode/enabled | 1 per gateway |
| Select | PIR sensitivity | pir_sensitivity | /gateway/pirSensitivity | 1 per gateway |
| Sensor | WiFi RSSI | wifi_rssi | /gateway/wifi/rssi | 1 per gateway |
| Sensor | WiFi firmware version | wifi_firmware_version | /gateway/wifi/versionFirmware | 1 per gateway |
| Sensor | Gateway firmware version | firmware_version | /gateway/versionFirmware | 1 per gateway |
| Sensor | Last update check | last_update_check | /gateway/update/lastCheck | 1 per gateway |
| Sensor | Last update applied | last_update_applied | /gateway/update/lastUpdate | 1 per gateway |
| Sensor | Notifications count (+ raw notifications attribute) | notifications | /notifications | 1 per gateway, only if path exists |
| Sensor | Zigbee firmware version | zigbee_firmware_version | /gateway/zigbee/versionFirmware | 1 per gateway, optional |
| Update | Firmware update (read-only) | firmware_update | /gateway/versionFirmware (latest inferred from /gateway/update/state) | 1 per gateway |

#### Zone (heating zone zn1, zn2, ...)

| Platform | Entity | Translation key | Resource path | Scope |
|---|---|---|---|---|
| Climate | Zone climate (Auto/Heat/Off + hvac_action) | n/a (Climate entity) | /zones/{zid}/temperatureActual, /zones/{zid}/temperatureHeatingSetpoint, /zones/{zid}/manualTemperatureHeating, /zones/{zid}/userMode, /zones/{zid}/status | 1 per discovered zone |
| Switch | Boost | boost | /heatingCircuits/hc1/boostShortcut or /heatingCircuits/hc1/boostMode (fallback writes zone manual mode) | 1 entity |
| Switch | Open window detection enable | open_window_detection | /zones/{zid}/openWindowDetection/enabled | Dynamic, per zone when reference exists |
| Number | Boost temperature | boost_temperature | /heatingCircuits/hc1/boostTemperature | 1 entity |
| Number | Boost duration | boost_duration | /heatingCircuits/hc1/boostDuration | 1 entity |
| Number | Max supply temperature | max_supply_temperature | /heatingCircuits/hc1/maxSupply | 1 entity |
| Number | Min supply temperature | min_supply_temperature | /heatingCircuits/hc1/minSupply | 1 entity |
| Number | Night setback threshold | night_setback_threshold | /heatingCircuits/hc1/nightThreshold | 1 entity |
| Number | Summer/winter threshold | summer_winter_threshold | /heatingCircuits/hc1/suWiThreshold | 1 entity |
| Number | Room influence | room_influence | /heatingCircuits/hc1/roomInfluence | 1 entity |
| Number | Temperature calibration offset | temperature_calibration_offset | /system/sensors/temperatures/offset | 1 entity |
| Select | Zone mode | zone_mode | /zones/zn1/userMode | Static select for zn1 |
| Select | Summer/winter mode | summer_winter_mode | /heatingCircuits/hc1/suWiSwitchMode | 1 entity |
| Select | Night switch mode | night_switch_mode | /heatingCircuits/hc1/nightSwitchMode | 1 entity |
| Select | Assigned program select | assigned_program_select | /zones/{zid}/clockProgram | Dynamic, per discovered zone |
| Sensor | Outdoor temperature | outdoor_temperature | /system/sensors/temperatures/outdoor_t1 | 1 entity (attached to zone device) |
| Sensor | Indoor humidity | indoor_humidity | /system/sensors/humidity/indoor_h1 | 1 entity (attached to zone device) |
| Sensor | Boost remaining time | boost_remaining_time | /heatingCircuits/hc1/boostRemainingTime (or synthetic fallback session) | 1 entity |
| Sensor | Supply temperature setpoint | supply_temp_setpoint | /heatingCircuits/hc1/supplyTemperatureSetpoint | 1 entity |
| Sensor | Boiler power setpoint | boiler_power | /heatingCircuits/hc1/powerSetpoint | 1 entity |
| Sensor | Zone valve position | valve_position | /zones/{zid}/actualValvePosition | Dynamic, per zone when reference exists |
| Sensor | Assigned program name | assigned_program | /zones/{zid}/assignedProgramName (computed from /programs/pgN/name) | Dynamic, per discovered zone |
| Sensor | Optimum start state | optimum_start_state | /zones/{zid}/optimumStartState | Dynamic, per zone when reference exists |
| Binary sensor | Open window detected | open_window_detected | /zones/{zid}/openWindowDetection/status | Dynamic, per zone when reference exists |

#### Vanne thermostatique

| Platform | Entity | Translation key | Resource path | Scope |
|---|---|---|---|---|
| Switch | Child lock | thermostat_valve_child_lock | /devices/list/thermostat_valve/{id}/childLock... or /devices/device{id}/.../childLock... | Dynamic, per discovered valve |
| Number | Temperature offset | thermostat_valve_temperature_offset | /devices/.../etrv/offset | Dynamic, per discovered valve |
| Sensor | Signal strength | thermostat_valve_signal_strength | /devices/list/thermostat_valve/{id}/signal | Dynamic, per discovered valve |
| Sensor | Battery | thermostat_valve_battery | /devices/list/thermostat_valve/{id}/battery | Dynamic, per discovered valve |
| Sensor | Linked zone | thermostat_valve_zone | /devices/list/thermostat_valve/{id}/zone | Dynamic, per discovered valve |
| Sensor | Protocol | thermostat_valve_protocol | /devices/list/thermostat_valve/{id}/protocol | Dynamic, per discovered valve |
| Sensor | Valve position | thermostat_valve_valve_position | /devices/list/thermostat_valve/{id}/valvePosition or /devices/device{id}/.../etrv/valvePosition | Dynamic, per discovered valve |
| Sensor | Actual temperature | thermostat_valve_temperature_actual | /devices/list/thermostat_valve/{id}/temperatureActual or /devices/device{id}/.../etrv/temperatureActual | Dynamic, per discovered valve |
| Binary sensor | Warning state | thermostat_valve_warning | /devices/list/thermostat_valve/{id}/warning | Dynamic, per discovered valve |

#### Efficacite energetique

| Platform | Entity | Translation key | Resource path | Scope |
|---|---|---|---|---|
| Number | Annual gas goal | annual_gas_goal | /energy/gas/annualGoal | Dynamic, if path exists |
| Number | Annual electricity goal | annual_electricity_goal | /energy/electricity/annualGoal | Dynamic, if path exists |
| Sensor | Gas heating today | gas_heating_today | /energy/historyHourly (aggregated to daily) | 1 entity |
| Sensor | Gas hot-water today | gas_hot_water_today | /energy/historyHourly (aggregated to daily) | 1 entity |
| Sensor | Gas total today | gas_total_today | /energy/historyHourly (aggregated to daily) | 1 entity |
| Sensor | Gas heating hourly | gas_heating_hourly | /energy/historyHourly (current-hour entry) | 1 entity |
| Sensor | Gas hot-water hourly | gas_hot_water_hourly | /energy/historyHourly (current-hour entry) | 1 entity |
| Sensor | Gas total hourly | gas_total_hourly | /energy/historyHourly (current-hour entry) | 1 entity |
| Sensor | Electricity day average | electricity_day_average | /energy/electricity/dayAverage | Dynamic, only if path available |
| Sensor | Electricity month average | electricity_month_average | /energy/electricity/monthAverage | Dynamic, only if path available |
| Sensor | Energy efficiency score | energy_efficiency | /gateway/ui/eco | Dynamic, only if /gateway/ui references include /gateway/ui/eco |

#### Eau chaude sanitaire (DHW)

| Platform | Entity | Translation key | Resource path | Scope |
|---|---|---|---|---|
| Water heater | Hot water tank (temperature + operation mode) | n/a (WaterHeater entity) | /dhwCircuits/dhw1/actualTemp, /dhwCircuits/dhw1/temperatureLevels/high, /dhwCircuits/dhw1/operationMode | 1 per gateway |
| Switch | Thermal disinfect | thermal_disinfect | /dhwCircuits/dhw1/thermalDisinfect/state | 1 entity |
| Switch | Extra hot water | extra_hot_water | /dhwCircuits/dhw1/extraDhw | 1 entity |
| Number | Extra hot water duration | extra_hot_water_duration | /dhwCircuits/dhw1/extraDhwDuration | 1 entity |
| Number | Thermal disinfect time | thermal_disinfect_time | /dhwCircuits/dhw1/thermalDisinfect/time | 1 entity |
| Select | Thermal disinfect weekday | thermal_disinfect_weekday | /dhwCircuits/dhw1/thermalDisinfect/weekDay | 1 entity |
| Sensor | DHW actual temperature | dhw_actual_temperature | /dhwCircuits/dhw1/actualTemp | 1 entity |
| Sensor | Thermal disinfect last result | thermal_disinfect_last_result | /dhwCircuits/dhw1/thermalDisinfect/lastResult | 1 entity |
| Binary sensor | DHW heating | dhw_heating | /dhwCircuits/dhw1/state | 1 entity |

#### Solaire (optionnel)

| Platform | Entity | Translation key | Resource path | Scope |
|---|---|---|---|---|
| Sensor | Collector temperature | collector_temperature | /solarCircuits/sc1/collectorTemperature | Optional, 1 entity |
| Sensor | Storage temperature | storage_temperature | /solarCircuits/sc1/dhwTankBottomTemperature | Optional, 1 entity |
| Sensor | Pump modulation | pump_modulation | /solarCircuits/sc1/pumpModulation | Optional, 1 entity |
| Sensor | Total solar gain | total_gain | /solarCircuits/sc1/totalSolarGain | Optional, 1 entity |

Notes:
- Dynamic entities are created only when the corresponding API paths are present and, where enforced, marked as available.
- Zone-scoped dynamic entities rely on zone references (for example openWindowDetection, actualValvePosition, optimumStartState).
- Thermostat-valve entities are discovered from /devices/list thermostat_valve rows and compatible /devices/deviceN trees; count and labels vary by installation.
- Solar entities are conditionally suppressed when the first refresh has no usable /solarCircuits/sc1 data; stale solar registry entries are removed.

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
form has fields for all of the above. **Positive reports are just as valuable**: "v1.3.1 works on my
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
- Major recent POINTTAPI improvements (last 2 weeks) by [@jfhautenauven](https://github.com/jfhautenauven) ([@LaPoutreDeBamako](https://github.com/LaPoutreDeBamako)): thermostat-valve support (actual temperature, child lock, offset), writable per-zone assigned-program entities, reference-driven `/programs` and `/devices` discovery, multi-language localization polish, solar-presence robustness, and expanded unit tests.

## Acknowledgements

The POINTTAPI path stands on the shoulders of other open-source efforts that reverse-engineered the Bosch cloud APIs:

- **[serbanb11/bosch-homecom-hass](https://github.com/serbanb11/bosch-homecom-hass)** and its library **[homecom_alt](https://github.com/serbanb11/homecom_alt)** — documented the pointt-api surface across device types, including the bulk endpoint wire format, the account-level gateway listing, and the RRC2 (CT200) endpoint set. Special thanks to **@joddye2**, whose live CT200 resource dumps in [bosch-homecom-hass#78](https://github.com/serbanb11/bosch-homecom-hass/issues/78) revealed `boostShortcut`, `boostZones`, and the writeable flags that made native boost support possible.
- **[BassXT/buderus](https://github.com/BassXT/buderus)** — early groundwork on the PointT API for MX300/K30 gateways (heat-source endpoints, SingleKey PKCE flow notes).
- **[bosch-thermostat/bosch-thermostat-client-python](https://github.com/bosch-thermostat/bosch-thermostat-client-python)** — the XMPP client this entire integration builds on, whose EasyControl device database also enabled our local-protocol verification probes.

The endpoints this integration uses, with observed types and writeable flags, are documented in [`docs/pointtapi-api.md`](docs/pointtapi-api.md) so the knowledge stays shared.
