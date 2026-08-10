"""POINTTAPI coordinator-based entities: climate, water_heater, sensors.

All use CoordinatorEntity; device_info and unique_id follow 2-tuple and entry_id + path.
"""
from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfEnergy, UnitOfPressure, UnitOfTemperature, UnitOfTime
from homeassistant.util import dt as dt_util
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .pointtapi_coordinator import PoinTTAPIDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

VALUE_KEY = "value"

SOLAR_CIRCUIT_PATHS = (
    "/solarCircuits/sc1/collectorTemperature",
    "/solarCircuits/sc1/dhwTankBottomTemperature",
    "/solarCircuits/sc1/pumpModulation",
    "/solarCircuits/sc1/totalSolarGain",
)

# Water heater operation mode mapping: API value <-> user-friendly label
# API accepts: "ownprogram" (auto/schedule), "Off", "high" (always on at high temp)
_API_TO_OP = {"ownprogram": "Auto", "Off": "Off", "high": "On"}
_OP_TO_API = {v: k for k, v in _API_TO_OP.items()}


def _val(data: dict[str, Any], path: str, key: str = VALUE_KEY) -> Any:
    """Get key (default 'value') from data[path] if present."""
    obj = data.get(path) if data else None
    return obj.get(key) if isinstance(obj, dict) else None


def _decode_zone_name(value: Any) -> str | None:
    """Decode Bosch zone names, which are returned as base64 UTF-8 strings."""
    if not isinstance(value, str):
        return None
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return value
    return decoded


def _sync_device_name(hass: Any, identifiers: set[tuple[str, str]], new_name: str | None) -> None:
    """Rename an existing Home Assistant device entry when the zone name changes."""
    if not hass or not identifiers or not new_name:
        return
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers=identifiers)
    if device is None:
        return
    if device.name == new_name:
        return
    registry.async_update_device(device.id, new_name=new_name)


def _path_available(data: dict[str, Any], path: str) -> bool:
    """True unless the appliance reports this function as unavailable.

    Bosch payloads carry string flags, e.g. /dhwCircuits/dhw1/extraDhw on the
    CT200 returns {"writeable": 1, "used": "false", "available": "false"} —
    writeable, but the appliance rejects the PUT. Path presence alone is not
    enough to decide a control is operable.

    ponytail: gates on `available` only. `used: "false"` also appears on paths
    that do accept writes (e.g. hc1/buildingHeatup), so keying on it would
    disable more entities than intended. Absent flag = no opinion = available.
    """
    obj = data.get(path) if data else None
    if not isinstance(obj, dict):
        return False
    return obj.get("available") != "false"


def _solar_data_available(data: dict[str, Any]) -> bool:
    """Return whether the first poll contains at least one usable solar value."""
    for path in SOLAR_CIRCUIT_PATHS:
        resource = data.get(path) if data else None
        if (
            isinstance(resource, dict)
            and "value" in resource
            and resource["value"] is not None
            and resource.get("available") != "false"
        ):
            return True
    return False


# ── Device-info routing: single source of truth for all POINTTAPI entities ──
#
# Routes paths and entity "kinds" to one of five logical devices:
#   - EasyControl Gateway:  (DOMAIN, uuid)                  — gateway/wifi/firmware
#   - Boiler:               (DOMAIN, f"{uuid}_boiler")      — heatSources, errors, gas usage
#   - Hot Water Tank:       (DOMAIN, f"{uuid}_dhw")         — DHW circuit + water_heater
#   - Heating Zone {zid}:   (DOMAIN, f"{uuid}_zone_{zid}")  — zones, heatingCircuits, zone-context sensors
#   - Solar:                (DOMAIN, f"{uuid}_solar")       — solarCircuits (conditional, see solar setup)
#
# The `kind` parameter is for entities whose device is determined by something
# other than the path alone — e.g. a Switch identified by its translation_key.

_GATEWAY_KINDS = {
    "notification_light",
    "auto_firmware_update",
    "pre_release",
    "pir_sensitivity",
}
_DHW_KINDS = {
    "thermal_disinfect",
}
_BOILER_KINDS = {
    "annual_gas_goal",
}


def _zone_id_from_path(path: str) -> str:
    """Parse zone id from /zones/{zid}/... or /heatingCircuits/{cid}/... — returns "zn1" by default."""
    parts = (path or "").split("/")
    if len(parts) >= 3:
        if parts[1] == "zones":
            return parts[2]
        if parts[1] == "heatingCircuits":
            # Map heating-circuit id (hc1) to its zone counterpart (zn1) — same index.
            cid = parts[2]
            if cid.startswith("hc"):
                return "zn" + cid[2:]
            return cid
    return "zn1"


def pointtapi_zone_ids(data: dict[str, Any]) -> list[str]:
    """Zone ids with a heating setpoint in coordinator data; ["zn1"] fallback.

    Filtering on temperatureHeatingSetpoint skips unconfigured zone slots
    (allowedZones can list more zones than actually exist).
    """
    ids = {
        p.split("/")[2]
        for p in data
        if p.startswith("/zones/") and p.endswith("/temperatureHeatingSetpoint")
    }
    return sorted(ids, key=lambda z: (len(z), z)) or ["zn1"]


def _zone_room_suffix(data: dict[str, Any], zid: str) -> str | None:
    """Room-name display suffix for a zone device, or None when unknown.

    zn1 gets its room name only on multi-zone setups — single-zone installs
    keep the bare "Heating Zone" device name they have always had (issue #11:
    on a 10-zone install the un-suffixed zn1 read as "living room missing").
    """
    zname = _decode_zone_name(_val(data, f"/zones/{zid}/name"))
    if not (isinstance(zname, str) and zname.strip()):
        return None
    if zid == "zn1" and len(pointtapi_zone_ids(data)) < 2:
        return None
    return f" {zname}"


def _resolve_device_info(
    uuid: str,
    path: str | None = None,
    *,
    kind: str | None = None,
    zone_display_suffix: str | None = None,
    data: dict[str, Any] | None = None,
) -> DeviceInfo:
    """Return the DeviceInfo for this entity based on its path and/or kind.

    See module-level routing table comment above. Pass the coordinator data
    as `data` so zone devices can be named after their room — every entity
    attached to a zone device must do so, or the registry name flip-flops.
    """
    p = path or ""

    # Explicit kind overrides (entities whose device isn't path-derivable)
    if kind in _GATEWAY_KINDS:
        return DeviceInfo(identifiers={(DOMAIN, uuid)}, name="EasyControl Gateway")
    if kind in _DHW_KINDS:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{uuid}_dhw1")},
            name="Hot Water Tank",
            via_device=(DOMAIN, uuid),
        )
    if kind in _BOILER_KINDS:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{uuid}_boiler")},
            name="Boiler",
            via_device=(DOMAIN, uuid),
        )

    # Path-based routing — first match wins.
    if p.startswith("/solarCircuits"):
        return DeviceInfo(
            identifiers={(DOMAIN, f"{uuid}_solar")},
            name="Solar",
            via_device=(DOMAIN, uuid),
        )
    if p.startswith("/dhwCircuits"):
        return DeviceInfo(
            identifiers={(DOMAIN, f"{uuid}_dhw1")},
            name="Hot Water Tank",
            via_device=(DOMAIN, uuid),
        )
    if (
        p.startswith("/heatSources")
        or p.startswith("/system/appliance")
        or p.startswith("/energy")
    ):
        return DeviceInfo(
            identifiers={(DOMAIN, f"{uuid}_boiler")},
            name="Boiler",
            via_device=(DOMAIN, uuid),
        )
    if (
        p.startswith("/zones")
        or p.startswith("/heatingCircuits")
        or p.startswith("/system/sensors")
    ):
        zid = _zone_id_from_path(p)
        suffix = zone_display_suffix
        if suffix is None and data:
            suffix = _zone_room_suffix(data, zid)
        if suffix is None:
            suffix = "" if zid == "zn1" else f" {zid}"
        # NB: identifier is `{uuid}_{zid}` (no `_zone_` prefix) to match the
        # existing climate-entity device id, so we don't orphan it.
        return DeviceInfo(
            identifiers={(DOMAIN, f"{uuid}_{zid}")},
            name=f"Heating Zone{suffix}",
            via_device=(DOMAIN, uuid),
        )
    # Gateway-level fallback (gateway/wifi/firmware/etc.)
    return DeviceInfo(identifiers={(DOMAIN, uuid)}, name="EasyControl Gateway")


# ── Custom sensor description with optional value_fn ─────────────────────────


@dataclass(frozen=True)
class BoschPoinTTAPISensorEntityDescription(SensorEntityDescription):
    """Sensor description with optional value_fn, last_reset_fn and attributes_fn."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None
    last_reset_fn: Callable[[], Any] | None = None
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    # Optional availability override (e.g. path-absent -> unavailable).
    # Opt-in only: sensors with synthetic keys (/energy/history_ch) must not
    # be subjected to a generic path-in-data check.
    available_fn: Callable[[dict[str, Any]], bool] | None = None


def _notification_entries(data: dict[str, Any]) -> list[Any] | None:
    """Extract the alert list from /notifications.

    The live CT200 returns the list under "value" (type errorList, verified
    2026-06-05); homecom_alt observed "values" on other device types — read
    both defensively. Returns None when the path is absent (sensor unavailable).
    """
    obj = data.get("/notifications") if data else None
    if not isinstance(obj, dict):
        return None
    entries = obj.get("values")
    if entries is None:
        entries = obj.get("value")
    return entries if isinstance(entries, list) else []


def _notifications_count(data: dict[str, Any]) -> int | None:
    """State for the notifications sensor: active alert count."""
    entries = _notification_entries(data)
    return None if entries is None else len(entries)


def _notifications_attributes(data: dict[str, Any]) -> dict[str, Any] | None:
    """Attributes for the notifications sensor: the raw alert entries."""
    entries = _notification_entries(data)
    return None if entries is None else {"notifications": entries}


# ── Gas usage helper functions ────────────────────────────────────────────────
#
# The Bosch /energy/history endpoint returns ~20 daily entries from a window
# that's typically 6+ weeks old (and rejects pagination params with 403), so
# it's useless for "today". Instead, /energy/historyHourly is paginated
# forward to today by the coordinator and the hourly entries are aggregated
# into both daily and hourly sensor values below.
#
# Date format quirk: API returns "DD-MM-YYYY" with a frozen / wrong year
# (commonly 2024 even now). We compare DD-MM only and trust the time-of-day
# context for "today". Hour `h` is a stringified 0-23.


def _today_dm() -> str:
    """Return today's DD-MM string in local time (matches API date prefix)."""
    return dt_util.now().strftime("%d-%m")


def _today_hourly_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all hourly entries whose date prefix matches today."""
    history = data.get("/energy/historyHourly") or {}
    val = history.get("value") if isinstance(history, dict) else None
    if not isinstance(val, list) or not val:
        return []
    if isinstance(val[0], dict) and "entries" in val[0]:
        entries = val[0].get("entries") or []
    else:
        entries = val
    today = _today_dm()
    return [e for e in entries if isinstance(e, dict) and str(e.get("d", ""))[:5] == today]


def _gas_ch_today(data: dict[str, Any]) -> float | None:
    entries = _today_hourly_entries(data)
    if not entries:
        return None
    return round(sum((e.get("gCh") or 0.0) for e in entries), 2)


def _gas_hw_today(data: dict[str, Any]) -> float | None:
    entries = _today_hourly_entries(data)
    if not entries:
        return None
    return round(sum((e.get("gHw") or 0.0) for e in entries), 2)


def _gas_total_today(data: dict[str, Any]) -> float | None:
    entries = _today_hourly_entries(data)
    if not entries:
        return None
    return round(sum((e.get("gCh") or 0.0) + (e.get("gHw") or 0.0) for e in entries), 2)


def _start_of_today() -> Any:
    """Return start of today in local timezone for last_reset."""
    return dt_util.start_of_local_day()


# ── Hourly gas usage helper functions ────────────────────────────────────────


def _current_hour_entry(data: dict[str, Any]) -> dict[str, Any] | None:
    """Find the entry matching today's date AND the current local hour."""
    entries = _today_hourly_entries(data)
    if not entries:
        return None
    now_h = dt_util.now().hour
    for entry in reversed(entries):
        try:
            if int(entry.get("h")) == now_h:
                return entry
        except (TypeError, ValueError):
            continue
    # No match for current hour yet — fall back to the latest available
    return entries[-1]


def _gas_ch_hourly(data: dict[str, Any]) -> float | None:
    e = _current_hour_entry(data)
    return None if e is None else (e.get("gCh") or 0.0)


def _gas_hw_hourly(data: dict[str, Any]) -> float | None:
    e = _current_hour_entry(data)
    return None if e is None else (e.get("gHw") or 0.0)


def _gas_total_hourly(data: dict[str, Any]) -> float | None:
    e = _current_hour_entry(data)
    if e is None:
        return None
    return round((e.get("gCh") or 0.0) + (e.get("gHw") or 0.0), 2)


class BoschPoinTTAPIClimateEntity(CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], ClimateEntity):
    """Climate entity for one POINTTAPI zone: current/setpoint from coordinator.data."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )

    def __init__(
        self,
        coordinator: PoinTTAPIDataUpdateCoordinator,
        entry_id: str,
        uuid: str,
        zone_id: str = "zn1",
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._uuid = uuid
        self._zone_id = zone_id
        self._attr_unique_id = f"{entry_id}_pointtapi_{zone_id}"
        # Name devices after their room ("/zones/znX/name") when known.
        suffix = f" {zname}" if isinstance(zname, str) and zname.strip() else None
        self._attr_device_info = _resolve_device_info(
            uuid, f"/zones/{zone_id}", data=coordinator.data or {}
        )
        self._current: float | None = None
        self._target: float | None = None
        self._hvac_mode = HVACMode.HEAT

    async def async_added_to_hass(self) -> None:
        """Sync the device name once the entity is attached to Home Assistant."""
        await super().async_added_to_hass()
        if self._attr_device_info is None:
            return
        identifiers = self._attr_device_info.get("identifiers", set()) if isinstance(self._attr_device_info, dict) else getattr(self._attr_device_info, "identifiers", set())
        device_name = self._attr_device_info.get("name") if isinstance(self._attr_device_info, dict) else getattr(self._attr_device_info, "name", None)
        _sync_device_name(self.hass, set(identifiers), device_name)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Read from coordinator.data and set state.

        OFF detection: the API doesn't support hc1/control="off", so we
        implement OFF as manual mode + min temp. Detect this state to keep
        the OFF indicator stable across coordinator polls.
        """
        data = self.coordinator.data or {}
        self._current = _val(data, f"/zones/{self._zone_id}/temperatureActual")
        self._target = _val(data, f"/zones/{self._zone_id}/temperatureHeatingSetpoint")
        user_mode = _val(data, f"/zones/{self._zone_id}/userMode")
        manual_temp = _val(data, f"/zones/{self._zone_id}/manualTemperatureHeating")
        # OFF = manual mode with temp at or below minimum
        try:
            is_off = (
                user_mode == "manual"
                and manual_temp is not None
                and float(manual_temp) <= self.min_temp
            )
        except (TypeError, ValueError):
            # Malformed manual-temp value -> don't crash the callback.
            is_off = False
        if is_off:
            self._hvac_mode = HVACMode.OFF
        else:
            self._hvac_mode = HVACMode.HEAT
        self._sync_device_name_from_state()
        self.async_write_ha_state()

    def _sync_device_name_from_state(self) -> None:
        """Rename the linked device if the room-based zone name is available."""
        if self._attr_device_info is None:
            return
        identifiers = self._attr_device_info.get("identifiers", set()) if isinstance(self._attr_device_info, dict) else getattr(self._attr_device_info, "identifiers", set())
        device_name = self._attr_device_info.get("name") if isinstance(self._attr_device_info, dict) else getattr(self._attr_device_info, "name", None)
        _sync_device_name(self.hass, set(identifiers), device_name)

    @property
    def current_temperature(self) -> float | None:
        return self._current

    @property
    def target_temperature(self) -> float | None:
        return self._target

    @property
    def hvac_mode(self) -> str:
        return self._hvac_mode

    @property
    def min_temp(self) -> float:
        return 5.0

    @property
    def max_temp(self) -> float:
        return 30.0

    async def async_set_temperature(self, **kwargs) -> None:
        """Set target temperature via POINTTAPI PUT.

        Automatically switches zone to manual mode first, since writing to
        manualTemperatureHeating has no effect when zone is in clock mode.
        """
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        try:
            # Switch to manual mode so the setpoint takes effect
            await self.coordinator.client.put(f"/zones/{self._zone_id}/userMode", "manual")
            path = f"/zones/{self._zone_id}/manualTemperatureHeating"
            await self.coordinator.client.put(path, float(temperature))
            self._target = float(temperature)
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                f"POINTTAPI set temperature failed: {err}"
            ) from err

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set HVAC mode via POINTTAPI PUT (task 6.2).

        API accepts: "weather" (auto/weather-compensated), "room" (room-based), not "off"/"auto".
        OFF is not directly supported by the hc1/control endpoint; we set zone userMode to manual
        with a low setpoint instead.
        """
        if hvac_mode == HVACMode.OFF:
            # No direct "off" for hc1/control; set zone to manual with min temp
            try:
                await self.coordinator.client.put(f"/zones/{self._zone_id}/userMode", "manual")
                await self.coordinator.client.put(f"/zones/{self._zone_id}/manualTemperatureHeating", self.min_temp)
                self._hvac_mode = hvac_mode
                self.async_write_ha_state()
                await self.coordinator.async_request_refresh()
            except ConfigEntryAuthFailed:
                raise
            except Exception as err:
                await self.coordinator.async_request_refresh()
                raise HomeAssistantError(
                    f"POINTTAPI set hvac_mode OFF failed: {err}"
                ) from err
            return
        value = "weather"
        path = "/heatingCircuits/hc1/control"
        try:
            await self.coordinator.client.put(path, value)
            self._hvac_mode = hvac_mode
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                f"POINTTAPI set hvac_mode failed: {err}"
            ) from err


class BoschPoinTTAPIWaterHeaterEntity(
    CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], WaterHeaterEntity
):
    """Water heater entity for POINTTAPI dhw1: state and temps from coordinator.data."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

    def __init__(
        self,
        coordinator: PoinTTAPIDataUpdateCoordinator,
        entry_id: str,
        uuid: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._uuid = uuid
        self._attr_unique_id = f"{entry_id}_pointtapi_dhw1"
        self._attr_device_info = _resolve_device_info(uuid, "/dhwCircuits/dhw1")
        self._current_temp: float | None = None
        self._target_temp: float | None = None
        self._operation_mode: str | None = None
        # User-friendly labels; mapped to/from API values via _OP_TO_API / _API_TO_OP
        self._attr_operation_list = ["Auto", "Off", "On"]
        # Populate initial state from already-fetched coordinator data
        self._sync_from_data()

    def _sync_from_data(self) -> None:
        """Populate local state from coordinator.data (no HA state write)."""
        data = self.coordinator.data or {}
        self._current_temp = _val(data, "/dhwCircuits/dhw1/actualTemp")
        self._target_temp = _val(data, "/dhwCircuits/dhw1/temperatureLevels/high")
        raw_op = _val(data, "/dhwCircuits/dhw1/operationMode")
        _LOGGER.debug("Water heater operationMode raw response: %s", data.get("/dhwCircuits/dhw1/operationMode"))
        self._operation_mode = _API_TO_OP.get(raw_op, raw_op) if raw_op else None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Read from coordinator.data and update HA state."""
        self._sync_from_data()
        self.async_write_ha_state()

    @property
    def current_temperature(self) -> float | None:
        return self._current_temp

    @property
    def target_temperature(self) -> float | None:
        return self._target_temp

    @property
    def current_operation(self) -> str | None:
        return self._operation_mode

    @property
    def min_temp(self) -> float:
        return 30.0

    @property
    def max_temp(self) -> float:
        return 60.0

    async def async_set_temperature(self, **kwargs) -> None:
        """Set target temperature via POINTTAPI PUT (task 6.3)."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        path = "/dhwCircuits/dhw1/temperatureLevels/high"
        try:
            await self.coordinator.client.put(path, float(temperature))
            self._target_temp = float(temperature)
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                f"POINTTAPI water heater set temperature failed: {err}"
            ) from err

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode via POINTTAPI PUT."""
        if operation_mode not in self._attr_operation_list:
            return
        api_value = _OP_TO_API.get(operation_mode, operation_mode)
        path = "/dhwCircuits/dhw1/operationMode"
        _LOGGER.debug("Setting water heater mode: %s -> API value: %s", operation_mode, api_value)
        try:
            await self.coordinator.client.put(path, api_value)
            self._operation_mode = operation_mode
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                f"POINTTAPI water heater set operation_mode failed: {err}"
            ) from err


# Curated POINTTAPI sensors: path, name, device_class, entity_category
def _pointtapi_sensor_descriptions() -> tuple[BoschPoinTTAPISensorEntityDescription, ...]:
    """Return all curated POINTTAPI sensor descriptions."""
    return (
        # ── Existing sensors ─────────────────────────────────────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/system/sensors/temperatures/outdoor_t1",
            translation_key="outdoor_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/system/sensors/humidity/indoor_h1",
            translation_key="indoor_humidity",
            device_class=SensorDeviceClass.HUMIDITY,
            native_unit_of_measurement="%",
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/zones/zn1/actualValvePosition",
            translation_key="valve_position",
            native_unit_of_measurement="%",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/system/appliance/systemPressure",
            translation_key="system_pressure",
            device_class=SensorDeviceClass.PRESSURE,
            native_unit_of_measurement=UnitOfPressure.BAR,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/gateway/wifi/rssi",
            translation_key="wifi_rssi",
            device_class=SensorDeviceClass.SIGNAL_STRENGTH,
            native_unit_of_measurement="dBm",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/gateway/update/state",
            translation_key="update_state",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/heatingCircuits/hc1/boostRemainingTime",
            translation_key="boost_remaining_time",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            value_fn=_boost_remaining_minutes,
        ),
        # ── Gas usage sensors — daily totals for Energy Dashboard ────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/energy/history_ch",
            translation_key="gas_heating_today",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL,
            value_fn=_gas_ch_today,
            last_reset_fn=_start_of_today,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/energy/history_hw",
            translation_key="gas_hot_water_today",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL,
            value_fn=_gas_hw_today,
            last_reset_fn=_start_of_today,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/energy/history_total",
            translation_key="gas_total_today",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL,
            value_fn=_gas_total_today,
            last_reset_fn=_start_of_today,
        ),
        # ── Gas usage sensors — hourly breakdown ─────────────────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/energy/historyHourly_ch",
            translation_key="gas_heating_hourly",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_gas_ch_hourly,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/energy/historyHourly_hw",
            translation_key="gas_hot_water_hourly",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_gas_hw_hourly,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/energy/historyHourly_total",
            translation_key="gas_total_hourly",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_gas_total_hourly,
        ),
        # ── Error / maintenance diagnostics (1b) ──────────────────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/system/appliance/blockingError",
            translation_key="blocking_error",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/system/appliance/lockingError",
            translation_key="locking_error",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/system/appliance/maintenanceRequest",
            translation_key="maintenance_request",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/system/appliance/displayCode",
            translation_key="display_code",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/system/appliance/causeCode",
            translation_key="cause_code",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # ── Firmware & circuit info (1c) ──────────────────────────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/gateway/versionFirmware",
            translation_key="firmware_version",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/heatingCircuits/hc1/supplyTemperatureSetpoint",
            translation_key="supply_temp_setpoint",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/heatingCircuits/hc1/powerSetpoint",
            translation_key="boiler_power",
            native_unit_of_measurement="%",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/heatSources/actualSupplyTemperature",
            translation_key="actual_supply_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/heatSources/actualModulation",
            translation_key="actual_modulation",
            native_unit_of_measurement="%",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # ── Solar circuit sensors ─────────────────────────────────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/solarCircuits/sc1/collectorTemperature",
            translation_key="collector_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/solarCircuits/sc1/dhwTankBottomTemperature",
            translation_key="storage_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/solarCircuits/sc1/pumpModulation",
            translation_key="pump_modulation",
            native_unit_of_measurement="%",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/solarCircuits/sc1/totalSolarGain",
            translation_key="total_gain",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        # ── DHW detail sensors (v0.31.0) ──────────────────────────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/dhwCircuits/dhw1/actualTemp",
            translation_key="dhw_actual_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        # ── Heat-source / burner sensors (v0.31.0) ────────────────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/heatSources/numberOfStarts",
            translation_key="boiler_ignition_starts",
            state_class=SensorStateClass.TOTAL_INCREASING,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # ── Firmware update diagnostic timestamps (v0.32.0) ──────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/gateway/update/lastCheck",
            translation_key="last_update_check",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda d: _parse_update_timestamp(_val(d, "/gateway/update/lastCheck")),
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/gateway/update/lastUpdate",
            translation_key="last_update_applied",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda d: _parse_update_timestamp(_val(d, "/gateway/update/lastUpdate")),
        ),
        # ── Notifications (v1.0.0) — POINTTAPI parity with XMPP NotificationSensor ──
        BoschPoinTTAPISensorEntityDescription(
            key="/notifications",
            translation_key="notifications",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_notifications_count,
            attributes_fn=_notifications_attributes,
            available_fn=lambda d: "/notifications" in (d or {}),
        ),
        # ── DHW thermal disinfect result (v1.0.0) ────────────────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/dhwCircuits/dhw1/thermalDisinfect/lastResult",
            translation_key="thermal_disinfect_last_result",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
    )


class BoschPoinTTAPISensorEntity(
    CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], SensorEntity
):
    """Sensor entity for POINTTAPI: one path from coordinator.data; has_entity_name=True."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoinTTAPIDataUpdateCoordinator,
        entry_id: str,
        uuid: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._uuid = uuid
        path = description.key
        slug = path.strip("/").replace("/", "_")
        self._attr_unique_id = f"{entry_id}_pointtapi_sensor_{slug}"
        self._attr_device_info = _resolve_device_info(
            uuid, path, data=coordinator.data or {}
        )
        self._path = path
        self._native_value: Any = None
        self._last_reset: Any = None
        # RSSI was previously disabled by default (task 8.3) — now enabled for monitoring

    @callback
    def _handle_coordinator_update(self) -> None:
        """Read value from coordinator.data for this path."""
        data = self.coordinator.data or {}
        desc = self.entity_description
        # Inject runtime state for value_fns that need cross-entity context
        # (currently: BoostSession for the boost_remaining_time sensor).
        session = getattr(self.coordinator, "boost_session", None)
        if session is not None:
            data = {**data, "__boost_session__": session}
        if isinstance(desc, BoschPoinTTAPISensorEntityDescription) and desc.value_fn is not None:
            self._native_value = desc.value_fn(data)
            if desc.last_reset_fn is not None:
                self._last_reset = desc.last_reset_fn()
        else:
            self._native_value = _val(data, self._path)
        if isinstance(desc, BoschPoinTTAPISensorEntityDescription) and desc.attributes_fn is not None:
            self._attr_extra_state_attributes = desc.attributes_fn(data) or {}
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        desc = self.entity_description
        if (
            isinstance(desc, BoschPoinTTAPISensorEntityDescription)
            and desc.available_fn is not None
        ):
            return super().available and desc.available_fn(self.coordinator.data or {})
        return super().available

    @property
    def native_value(self) -> Any:
        return self._native_value

    @property
    def last_reset(self) -> Any:
        return self._last_reset


# ── Number entities (boost settings) ─────────────────────────────────────────


POINTTAPI_NUMBER_DESCRIPTIONS: tuple[NumberEntityDescription, ...] = (
    NumberEntityDescription(
        key="/heatingCircuits/hc1/boostTemperature",
        translation_key="boost_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=5.0,
        native_max_value=30.0,
        native_step=0.5,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/boostDuration",
        translation_key="boost_duration",
        native_unit_of_measurement=UnitOfTime.HOURS,
        native_min_value=0.5,
        native_max_value=24.0,
        native_step=0.5,
    ),
    # ── Heating circuit configuration (2b) ───────────────────────────────────
    NumberEntityDescription(
        key="/heatingCircuits/hc1/maxSupply",
        translation_key="max_supply_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=25.0,
        native_max_value=90.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/minSupply",
        translation_key="min_supply_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=10.0,
        native_max_value=90.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/nightThreshold",
        translation_key="night_setback_threshold",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=5.0,
        native_max_value=30.0,
        native_step=0.5,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/suWiThreshold",
        translation_key="summer_winter_threshold",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=10.0,
        native_max_value=30.0,
        native_step=0.5,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/roomInfluence",
        translation_key="room_influence",
        native_min_value=0.0,
        native_max_value=3.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/system/sensors/temperatures/offset",
        translation_key="temperature_calibration_offset",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=-5.0,
        native_max_value=5.0,
        native_step=0.5,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/energy/gas/annualGoal",
        translation_key="annual_gas_goal",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        native_min_value=0.0,
        native_max_value=1000000.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
    ),
    # ── v1.0.0 comfort controls (constraints from boost-probe-notes.md) ───────
    NumberEntityDescription(
        key="/dhwCircuits/dhw1/extraDhwDuration",
        translation_key="extra_hot_water_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=15.0,
        native_max_value=2880.0,
        native_step=15.0,
    ),
    NumberEntityDescription(
        key="/dhwCircuits/dhw1/thermalDisinfect/time",
        translation_key="thermal_disinfect_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=0.0,
        native_max_value=1439.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
    ),
)


class BoschPoinTTAPINumberEntity(
    CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], NumberEntity
):
    """Number entity for POINTTAPI: read/write a single path value."""

    _attr_has_entity_name = True

    entity_description: NumberEntityDescription

    def __init__(
        self,
        coordinator: PoinTTAPIDataUpdateCoordinator,
        entry_id: str,
        uuid: str,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._uuid = uuid
        self._path = description.key
        slug = description.key.strip("/").replace("/", "_")
        self._attr_unique_id = f"{entry_id}_pointtapi_number_{slug}"
        self._attr_device_info = _resolve_device_info(
            uuid, description.key, data=coordinator.data or {}
        )
        self._native_value: float | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        raw = _val(data, self._path)
        try:
            self._native_value = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            # Malformed API value for a numeric path -> unavailable, don't crash.
            self._native_value = None
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable when the path is absent, or the appliance reports it so."""
        return super().available and _path_available(
            self.coordinator.data or {}, self._path
        )

    @property
    def native_value(self) -> float | None:
        return self._native_value

    async def async_set_native_value(self, value: float) -> None:
        """Write value to POINTTAPI."""
        try:
            await self.coordinator.client.put(self._path, value)
            self._native_value = value
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                f"POINTTAPI set {self._path} failed: {err}"
            ) from err


# ── Switch entity (boost toggle) ─────────────────────────────────────────────


class BoschPoinTTAPIBoostSwitchEntity(
    CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], SwitchEntity
):
    """Switch entity for POINTTAPI: one-tap boost on/off.

    The native /heatingCircuits/hc1/boostMode endpoint is 403-blocked by the
    POINTTAPI cloud scope. Workaround: boost ON = switch zone to manual mode
    at the configured boost temperature; boost OFF = restore clock mode.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "boost"
    _attr_name = None

    def __init__(
        self,
        coordinator: PoinTTAPIDataUpdateCoordinator,
        entry_id: str,
        uuid: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._uuid = uuid
        self._attr_unique_id = f"{entry_id}_pointtapi_boost"
        # Boost operates on the zone, so live with the Heating Zone device
        self._attr_device_info = _resolve_device_info(
            uuid, "/zones/zn1", data=coordinator.data or {}
        )
        self._is_on: bool = False
        self._pre_boost_mode: str | None = None
        # Track boost state explicitly rather than deriving from zone state,
        # because the zone state lags behind PUT calls and causes flicker.
        self._boost_set_by_us: bool = False
        # Cancel handle for the auto-off async_call_later (None when no timer
        # is scheduled). Calling it cancels; calling it twice is a no-op.
        self._auto_off_cancel: Callable[[], None] | None = None
        # Unsub callable for the one-shot _clear_boost_flag coordinator
        # listener (None when no one-shot is pending). DataUpdateCoordinator
        # has no async_remove_listener; deregistration goes through this.
        self._clear_boost_unsub: Callable[[], None] | None = None

    # ── Native boost probe ladder (v1.0.0) ────────────────────────────────
    #
    # Probe of 2026-06-05 (boost-probe-notes.md): boostShortcut is a writeable
    # boostShortcutStruct [{mode, temperature, duration, zones:[int]}] — the
    # app's one-shot boost command — and the historical 403 on PUT boostMode
    # is gone. The ladder tries native routes first and caches the verdict on
    # the coordinator; the v0.33 manual-mode workaround stays as fallback.
    # Endpoint knowledge: serbanb11/homecom_alt issue dumps + our live probes.

    ROUTE_SHORTCUT = "boostShortcut"
    ROUTE_DIRECT = "boostMode"
    ROUTE_FALLBACK = "fallback"

    def _boost_zone_ids(self, data: dict[str, Any]) -> list[int]:
        """Integer zone ids for the boost structs (NOT "zn1" strings)."""
        obj = data.get("/heatingCircuits/hc1/boostZones") or {}
        val = obj.get("value")
        if isinstance(val, list) and val and isinstance(val[0], dict):
            zones = val[0].get("zones") or val[0].get("allowedZones")
            if isinstance(zones, list) and zones:
                return zones
        return [1]

    async def _confirm_native_active(self) -> bool:
        """A native write counts only if the device reports boost active."""
        await self.coordinator.async_refresh()
        data = self.coordinator.data or {}
        if _val(data, "/heatingCircuits/hc1/boostMode") == "on":
            return True
        rem = _val(data, "/heatingCircuits/hc1/boostRemainingTime")
        return isinstance(rem, (int, float)) and rem > 0

    async def _probe_native_boost(
        self, boost_temp: float, duration_h: float, zones: list[int]
    ) -> str:
        """Run the probe ladder once; cache and return the working route.

        Writes are restricted to /heatingCircuits/hc1/boost* paths. Each rung
        is confirmed against the next refresh — a 204 alone is acceptance,
        not activation.
        """
        rungs: list[dict[str, Any]] = []
        # Rung 1: boostShortcut struct — the app's native one-shot command.
        try:
            await self.coordinator.client.put(
                "/heatingCircuits/hc1/boostShortcut",
                [{
                    "mode": "on",
                    "temperature": float(boost_temp),
                    "duration": int(duration_h),
                    "zones": zones,
                }],
            )
            active = await self._confirm_native_active()
            rungs.append({"rung": self.ROUTE_SHORTCUT, "put": "accepted", "active": active})
            _LOGGER.debug("Boost probe rung boostShortcut: accepted, active=%s", active)
            if active:
                self.coordinator.boost_probe_result = {
                    "route": self.ROUTE_SHORTCUT, "rungs": rungs,
                }
                return self.ROUTE_SHORTCUT
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            rungs.append({"rung": self.ROUTE_SHORTCUT, "error": str(err)})
            _LOGGER.debug("Boost probe rung boostShortcut failed: %s", err)
        # Rung 2: boostZones + boostMode direct PUTs.
        try:
            await self.coordinator.client.put(
                "/heatingCircuits/hc1/boostZones", [{"zones": zones}]
            )
            await self.coordinator.client.put("/heatingCircuits/hc1/boostMode", "on")
            active = await self._confirm_native_active()
            rungs.append({"rung": self.ROUTE_DIRECT, "put": "accepted", "active": active})
            _LOGGER.debug("Boost probe rung boostMode: accepted, active=%s", active)
            if active:
                self.coordinator.boost_probe_result = {
                    "route": self.ROUTE_DIRECT, "rungs": rungs,
                }
                return self.ROUTE_DIRECT
            # Accepted but inactive — best-effort revert, boost paths only.
            await self.coordinator.client.put("/heatingCircuits/hc1/boostMode", "off")
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            rungs.append({"rung": self.ROUTE_DIRECT, "error": str(err)})
            _LOGGER.debug("Boost probe rung boostMode failed: %s", err)
        # NOTE: a bulk-write rung was considered (design D4) but no community
        # project has observed the bulk WRITE wire format, and the direct
        # route's ACL is confirmed open — guessing write formats against a
        # live heating system is not worth it. Falls back to the workaround.
        self.coordinator.boost_probe_result = {
            "route": self.ROUTE_FALLBACK, "rungs": rungs,
        }
        _LOGGER.info("Native boost unavailable, using manual-mode workaround")
        return self.ROUTE_FALLBACK

    async def _native_boost_on(
        self, route: str, boost_temp: float, duration_h: float, zones: list[int]
    ) -> bool:
        """Activate boost via the cached native route. True when confirmed."""
        try:
            if route == self.ROUTE_SHORTCUT:
                await self.coordinator.client.put(
                    "/heatingCircuits/hc1/boostShortcut",
                    [{
                        "mode": "on",
                        "temperature": float(boost_temp),
                        "duration": int(duration_h),
                        "zones": zones,
                    }],
                )
            else:
                await self.coordinator.client.put(
                    "/heatingCircuits/hc1/boostZones", [{"zones": zones}]
                )
                await self.coordinator.client.put(
                    "/heatingCircuits/hc1/boostMode", "on"
                )
            return await self._confirm_native_active()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("Native boost ON via %s failed: %s", route, err)
            return False

    async def _native_boost_off(self, route: str) -> bool:
        """Deactivate a native boost. Never touches /zones/zn1/userMode."""
        try:
            if route == self.ROUTE_SHORTCUT:
                data = self.coordinator.data or {}
                await self.coordinator.client.put(
                    "/heatingCircuits/hc1/boostShortcut",
                    [{
                        "mode": "off",
                        "temperature": float(
                            _val(data, "/heatingCircuits/hc1/boostTemperature") or 26.0
                        ),
                        "duration": int(
                            float(_val(data, "/heatingCircuits/hc1/boostDuration") or 2.0)
                        ),
                        "zones": self._boost_zone_ids(data),
                    }],
                )
            else:
                await self.coordinator.client.put(
                    "/heatingCircuits/hc1/boostMode", "off"
                )
            return True
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("Native boost OFF via %s failed: %s", route, err)
            return False

    @callback
    def _handle_coordinator_update(self) -> None:
        # Only update from coordinator data if we didn't explicitly set boost.
        # When we set boost, _is_on is already correct from turn_on/turn_off.
        if not self._boost_set_by_us:
            data = self.coordinator.data or {}
            boost_mode = _val(data, "/heatingCircuits/hc1/boostMode")
            self._is_on = boost_mode == "on"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn boost on: native route first, manual-mode workaround as fallback."""
        data = self.coordinator.data or {}
        boost_temp = _val(data, "/heatingCircuits/hc1/boostTemperature") or 26.0
        duration_h = float(
            _val(data, "/heatingCircuits/hc1/boostDuration") or 2.0
        )
        zones = self._boost_zone_ids(data)

        # Native-first: probe once, then reuse the cached route.
        probe = self.coordinator.boost_probe_result
        try:
            if probe is None:
                route = await self._probe_native_boost(boost_temp, duration_h, zones)
                native_ok = route != self.ROUTE_FALLBACK
            elif probe.get("route") != self.ROUTE_FALLBACK:
                route = probe["route"]
                native_ok = await self._native_boost_on(
                    route, boost_temp, duration_h, zones
                )
            else:
                native_ok = False
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("Native boost attempt errored: %s", err)
            native_ok = False
        if native_ok:
            # Server-side boost: no local timer, no synthetic session — the
            # device owns duration/countdown and survives HA restarts.
            self.coordinator.boost_session = None
            self._boost_set_by_us = True
            self._is_on = True
            self.async_write_ha_state()
            _LOGGER.info(
                "POINTTAPI native boost ON at %.1f°C for %.0f h (zones %s)",
                float(boost_temp), duration_h, zones,
            )
            return

        # Fallback: v0.33 manual-mode workaround (unchanged behavior).
        try:
            # Remember current mode so we can restore it
            self._pre_boost_mode = _val(data, "/zones/zn1/userMode") or "clock"
            await self.coordinator.client.put("/zones/zn1/userMode", "manual")
            await self.coordinator.client.put(
                "/zones/zn1/manualTemperatureHeating", float(boost_temp)
            )
            # Record the session on the coordinator so the boost_remaining_time
            # sensor can derive a synthetic countdown.
            self.coordinator.boost_session = BoostSession(
                started_at=dt_util.utcnow(),
                duration_hours=duration_h,
            )
            # Schedule auto-off. Cancel any prior pending callback first
            # (defensive — rapid toggle wouldn't leak otherwise, but safe).
            if self._auto_off_cancel is not None:
                self._auto_off_cancel()
            self._auto_off_cancel = async_call_later(
                self.hass,
                duration_h * 3600.0,
                self._auto_off_callback,
            )
            _LOGGER.info(
                "POINTTAPI boost ON: zone=manual at %.1f°C, auto-off in %.1f h",
                float(boost_temp),
                duration_h,
            )
            self._boost_set_by_us = True
            self._is_on = True
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            self._boost_set_by_us = False
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(f"POINTTAPI boost turn_on failed: {err}") from err

    async def _auto_off_callback(self, _now) -> None:
        """Auto-off timer fired — turn boost off after the configured duration."""
        session = self.coordinator.boost_session
        _LOGGER.info(
            "POINTTAPI boost auto-off after %.1f h",
            session.duration_hours if session else 0.0,
        )
        self._auto_off_cancel = None  # timer already fired
        await self.async_turn_off()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn boost off: native deactivation, or cancel timer + restore zone mode."""
        # Native-mode off: no local timer/session exists; deactivate via the
        # probed route and never touch /zones/zn1/userMode.
        probe = self.coordinator.boost_probe_result
        if (
            probe is not None
            and probe.get("route") != self.ROUTE_FALLBACK
            and self.coordinator.boost_session is None
            and self._auto_off_cancel is None
        ):
            if await self._native_boost_off(probe["route"]):
                self._boost_set_by_us = True
                self._is_on = False
                self.async_write_ha_state()
                if self._clear_boost_unsub is None:
                    self._clear_boost_unsub = self.coordinator.async_add_listener(
                        self._clear_boost_flag
                    )
                await self.coordinator.async_request_refresh()
                return
            # Native off failed — fall through to the workaround restore,
            # which at minimum returns the zone to a sane mode.

        # Fallback: cancel any pending auto-off — must happen before the
        # userMode PUT so a racing timer can't fire after manual off.
        if self._auto_off_cancel is not None:
            self._auto_off_cancel()
            self._auto_off_cancel = None
        self.coordinator.boost_session = None
        try:
            restore_mode = self._pre_boost_mode or "clock"
            await self.coordinator.client.put("/zones/zn1/userMode", restore_mode)
            self._boost_set_by_us = True
            self._is_on = False
            self._pre_boost_mode = None
            self.async_write_ha_state()
            # After one successful refresh with the restored state, stop overriding
            if self._clear_boost_unsub is None:
                self._clear_boost_unsub = self.coordinator.async_add_listener(
                    self._clear_boost_flag
                )
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            self._boost_set_by_us = False
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(f"POINTTAPI boost turn_off failed: {err}") from err

    @callback
    def _clear_boost_flag(self) -> None:
        """Clear the boost override flag after one coordinator cycle."""
        self._boost_set_by_us = False
        if self._clear_boost_unsub is not None:
            self._clear_boost_unsub()  # one-shot: unregister self
            self._clear_boost_unsub = None


# ── Generic switch entity (firmware update, notification light, etc.) ─────────


@dataclass(frozen=True)
class BoschPoinTTAPISwitchEntityDescription(SwitchEntityDescription):
    """Switch description for POINTTAPI generic boolean ("true"/"false") paths."""

    on_value: str = "true"
    off_value: str = "false"
    device_id_suffix: str | None = None
    device_name_override: str | None = None


POINTTAPI_SWITCH_DESCRIPTIONS: tuple[BoschPoinTTAPISwitchEntityDescription, ...] = (
    BoschPoinTTAPISwitchEntityDescription(
        key="/gateway/update/enabled",
        translation_key="auto_firmware_update",
        entity_category=EntityCategory.CONFIG,
    ),
    BoschPoinTTAPISwitchEntityDescription(
        key="/gateway/notificationLight/enabled",
        translation_key="notification_light",
        entity_category=EntityCategory.CONFIG,
    ),
    BoschPoinTTAPISwitchEntityDescription(
        key="/dhwCircuits/dhw1/thermalDisinfect/state",
        name="Thermal disinfect",
        device_id_suffix="dhw1",
        device_name_override="Water heater",
    ),
    # ── v1.0.0 comfort controls (writeable: 1 confirmed, boost-probe-notes.md) ──
    BoschPoinTTAPISwitchEntityDescription(
        key="/system/awayMode/enabled",
        translation_key="away_mode",
    ),
    BoschPoinTTAPISwitchEntityDescription(
        key="/dhwCircuits/dhw1/extraDhw",
        translation_key="extra_hot_water",
        on_value="on",
        off_value="off",
    ),
)


class BoschPoinTTAPIGenericSwitchEntity(
    CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], SwitchEntity
):
    """Generic switch entity for POINTTAPI boolean paths (true/false string values)."""

    _attr_has_entity_name = True
    entity_description: BoschPoinTTAPISwitchEntityDescription

    def __init__(
        self,
        coordinator: PoinTTAPIDataUpdateCoordinator,
        entry_id: str,
        uuid: str,
        description: BoschPoinTTAPISwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._uuid = uuid
        self._path = description.key
        slug = description.key.strip("/").replace("/", "_")
        self._attr_unique_id = f"{entry_id}_pointtapi_switch_{slug}"
        # Path-based routing via _resolve_device_info covers /gateway, /dhwCircuits, etc.
        # device_id_suffix is retained on the description for compatibility but no longer used.
        self._attr_device_info = _resolve_device_info(uuid, description.key)
        self._is_on: bool = False

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        val = _val(data, self._path)
        self._is_on = val == self.entity_description.on_value
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable when the path is absent, or the appliance reports it so."""
        return super().available and _path_available(
            self.coordinator.data or {}, self._path
        )

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.put(self._path, self.entity_description.on_value)
            self._is_on = True
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                f"POINTTAPI switch {self._path} turn_on failed: {err}"
            ) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.put(self._path, self.entity_description.off_value)
            self._is_on = False
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                f"POINTTAPI switch {self._path} turn_off failed: {err}"
            ) from err


# ── Select entity ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BoschPoinTTAPISelectEntityDescription(SelectEntityDescription):
    """Select description for POINTTAPI option paths."""

    options: tuple[str, ...] = ()


def _select_state_key(value: str) -> str:
    """Return the translation-safe Home Assistant representation of an option."""
    return value.strip().lower().replace(" ", "_")


def _normalize_select_option(raw_option: Any, supported_options: set[str]) -> str | None:
    """Map a Bosch API value to a supported select option key, or None if unknown."""
    if not isinstance(raw_option, str):
        return None
    normalized = _select_state_key(raw_option)
    return normalized if normalized in supported_options else None


POINTTAPI_SELECT_DESCRIPTIONS: tuple[BoschPoinTTAPISelectEntityDescription, ...] = (
    BoschPoinTTAPISelectEntityDescription(
        key="/zones/zn1/userMode",
        translation_key="zone_mode",
        options=("clock", "manual"),
    ),
    BoschPoinTTAPISelectEntityDescription(
        key="/gateway/pirSensitivity",
        translation_key="pir_sensitivity",
        options=("high", "medium", "low"),
        entity_category=EntityCategory.CONFIG,
    ),
    BoschPoinTTAPISelectEntityDescription(
        key="/heatingCircuits/hc1/suWiSwitchMode",
        translation_key="summer_winter_mode",
        options=("off", "automatic", "manual"),
        entity_category=EntityCategory.CONFIG,
    ),
    BoschPoinTTAPISelectEntityDescription(
        key="/heatingCircuits/hc1/nightSwitchMode",
        translation_key="night_switch_mode",
        options=("off", "automatic", "reduced"),
        entity_category=EntityCategory.CONFIG,
    ),
    # ── v1.0.0: DHW thermal disinfect weekday (API values, verified live) ────
    BoschPoinTTAPISelectEntityDescription(
        key="/dhwCircuits/dhw1/thermalDisinfect/weekDay",
        translation_key="thermal_disinfect_weekday",
        options=("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"),
        entity_category=EntityCategory.CONFIG,
    ),
)


class BoschPoinTTAPISelectEntity(
    CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], SelectEntity
):
    """Select entity for POINTTAPI option paths."""

    _attr_has_entity_name = True
    entity_description: BoschPoinTTAPISelectEntityDescription

    def __init__(
        self,
        coordinator: PoinTTAPIDataUpdateCoordinator,
        entry_id: str,
        uuid: str,
        description: BoschPoinTTAPISelectEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._uuid = uuid
        self._path = description.key
        slug = description.key.strip("/").replace("/", "_")
        self._attr_unique_id = f"{entry_id}_pointtapi_select_{slug}"
        self._attr_options = [_select_state_key(option) for option in description.options]
        self._attr_device_info = _resolve_device_info(
            uuid, description.key, data=coordinator.data or {}
        )
        self._current_option: str | None = None
        self._supported_option_keys = {
            _select_state_key(option) for option in description.options
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        raw_option = _val(data, self._path)
        self._current_option = _normalize_select_option(
            raw_option, self._supported_option_keys
        )
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable when the path is absent, the appliance reports it so, or the value is unsupported."""
        return (
            super().available
            and _path_available(self.coordinator.data or {}, self._path)
            and self._current_option is not None
        )

    @property
    def current_option(self) -> str | None:
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        if option not in self._supported_option_keys:
            raise HomeAssistantError(f"Unsupported select option: {option}")
        try:
            api_option = next(
                (
                    raw_option
                    for raw_option in self.entity_description.options
                    if _select_state_key(raw_option) == option
                ),
                option,
            )
            await self.coordinator.client.put(self._path, api_option)
            self._current_option = _select_state_key(option)
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                f"POINTTAPI select {self._path} failed: {err}"
            ) from err


# ── Binary-sensor surface for POINTTAPI ─────────────────────────────────────


@dataclass(frozen=True)
class BoschPoinTTAPIBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary-sensor description with optional value_fn override.

    When `value_fn` is None, the entity falls back to the default on/off-string
    resolver on `coordinator.data[key]["value"]`.
    """

    value_fn: Callable[[dict[str, Any]], bool | None] | None = None


def _resolve_on_off(raw: Any) -> bool | None:
    """Map an API value to True/False/None.

    Accepts either dialect Bosch returns:
    - "on"/"off"   — used by /dhwCircuits/dhw1/state, /heatSources/flameIndication
    - "true"/"false" — used by /heatSources/refillNeeded
    Comparison is case-insensitive after trim. Any other value returns None
    so HA renders the entity as "unknown".
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in ("on", "true"):
            return True
        if v in ("off", "false"):
            return False
    return None


# ── Boost session: in-memory tracking of HA-triggered boost (v0.33.0) ──────


@dataclass
class BoostSession:
    """In-memory record of an HA-triggered boost session.

    Set by BoschPoinTTAPIBoostSwitchEntity.async_turn_on on the coordinator,
    cleared on async_turn_off. Read by the boost_remaining_time sensor's
    value_fn to derive a synthetic countdown.
    """

    started_at: datetime
    duration_hours: float

    @property
    def remaining_minutes(self) -> float:
        end = self.started_at + timedelta(hours=self.duration_hours)
        return max(0.0, (end - dt_util.utcnow()).total_seconds() / 60.0)


def _boost_remaining_minutes(data: dict[str, Any]) -> float | None:
    """Synthetic boost-remaining-time resolver.

    When a fallback-mode boost session is active (BoschPoinTTAPISensorEntity
    injects it under "__boost_session__"), report the local countdown.
    Otherwise report Bosch's /heatingCircuits/hc1/boostRemainingTime — under
    native boost (v1.0.0 probe ladder) this is the device's real server-side
    countdown; with no boost active it's 0.0.
    """
    session = data.get("__boost_session__")
    if isinstance(session, BoostSession):
        return round(session.remaining_minutes, 1)
    raw = _val(data, "/heatingCircuits/hc1/boostRemainingTime")
    return raw if raw is not None else None


def _parse_update_timestamp(raw: Any) -> datetime | None:
    """Parse a Bosch update timestamp like '2026-05-11T01:02:00+02:00 Mo'.

    The API appends a 2-letter English weekday abbreviation after a space.
    Strip it before fromisoformat. Returns None on any parse failure.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    iso = raw.strip().rsplit(" ", 1)[0]
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


class BoschPoinTTAPIBinarySensorEntity(
    CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor entity for POINTTAPI; routes device via _resolve_device_info."""

    _attr_has_entity_name = True
    entity_description: BoschPoinTTAPIBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: PoinTTAPIDataUpdateCoordinator,
        entry_id: str,
        uuid: str,
        description: BoschPoinTTAPIBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._uuid = uuid
        self._path = description.key
        slug = description.key.strip("/").replace("/", "_")
        self._attr_unique_id = f"{entry_id}_pointtapi_binary_sensor_{slug}"
        self._attr_device_info = _resolve_device_info(uuid, description.key)
        self._is_on: bool | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        desc = self.entity_description
        if desc.value_fn is not None:
            self._is_on = desc.value_fn(data)
        else:
            self._is_on = _resolve_on_off(_val(data, self._path))
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._is_on


POINTTAPI_BINARY_SENSOR_DESCRIPTIONS: tuple[BoschPoinTTAPIBinarySensorEntityDescription, ...] = (
    BoschPoinTTAPIBinarySensorEntityDescription(
        key="/dhwCircuits/dhw1/state",
        translation_key="dhw_heating",
        device_class=BinarySensorDeviceClass.HEAT,
    ),
    BoschPoinTTAPIBinarySensorEntityDescription(
        key="/heatSources/flameIndication",
        translation_key="burner_flame",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    BoschPoinTTAPIBinarySensorEntityDescription(
        key="/heatSources/refillNeeded",
        translation_key="refill_needed",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)


# ── Update platform surface for POINTTAPI (v0.32.0) ─────────────────────────


@dataclass(frozen=True)
class BoschPoinTTAPIUpdateEntityDescription(UpdateEntityDescription):
    """Update-platform description with version-resolution callables.

    Both functions receive the coordinator.data dict and return a version
    string. installed_version_fn is required; latest_version_fn is required
    too — for read-only Update entities it typically returns either the
    same string (no update) or a distinct sentinel (e.g. installed + ' (update available)').
    """

    installed_version_fn: Callable[[dict[str, Any]], str | None] | None = None
    latest_version_fn: Callable[[dict[str, Any]], str | None] | None = None


def _gateway_installed_version(data: dict[str, Any]) -> str | None:
    return _val(data, "/gateway/versionFirmware")


def _gateway_latest_version(data: dict[str, Any]) -> str | None:
    """Derive latest_version from /gateway/update/state.

    Bosch doesn't expose the available version number (the dedicated fields
    return 403). Map the state string to either "no update" (=> installed)
    or "update available" by returning a distinct synthetic value.
    """
    installed = _val(data, "/gateway/versionFirmware")
    if installed is None:
        return None
    state = _val(data, "/gateway/update/state")
    if isinstance(state, str) and state.strip().lower() != "no update":
        return f"{installed} (update available)"
    return installed


class BoschPoinTTAPIUpdateEntity(
    CoordinatorEntity[PoinTTAPIDataUpdateCoordinator], UpdateEntity
):
    """Read-only Update entity for POINTTAPI gateways.

    No INSTALL or SKIP features — Bosch doesn't expose a programmatic install
    path we can safely call. Surfacing in HA's Updates panel is the goal.
    """

    _attr_has_entity_name = True
    _attr_supported_features = UpdateEntityFeature(0)
    entity_description: BoschPoinTTAPIUpdateEntityDescription

    def __init__(
        self,
        coordinator: PoinTTAPIDataUpdateCoordinator,
        entry_id: str,
        uuid: str,
        description: BoschPoinTTAPIUpdateEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._uuid = uuid
        slug = description.key.strip("/").replace("/", "_")
        self._attr_unique_id = f"{entry_id}_pointtapi_update_{slug}"
        self._attr_device_info = _resolve_device_info(uuid, description.key)

    @property
    def installed_version(self) -> str | None:
        fn = self.entity_description.installed_version_fn
        return fn(self.coordinator.data or {}) if fn else None

    @property
    def latest_version(self) -> str | None:
        fn = self.entity_description.latest_version_fn
        return fn(self.coordinator.data or {}) if fn else None


POINTTAPI_UPDATE_DESCRIPTIONS: tuple[BoschPoinTTAPIUpdateEntityDescription, ...] = (
    BoschPoinTTAPIUpdateEntityDescription(
        key="/gateway/versionFirmware",
        translation_key="firmware_update",
        entity_category=EntityCategory.DIAGNOSTIC,
        installed_version_fn=_gateway_installed_version,
        latest_version_fn=_gateway_latest_version,
    ),
)
