"""POINTTAPI coordinator-based entities: climate, water_heater, sensors.

All use CoordinatorEntity; device_info and unique_id follow 2-tuple and entry_id + path.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
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
from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfEnergy, UnitOfPressure, UnitOfTemperature, UnitOfTime
from homeassistant.util import dt as dt_util
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .pointtapi_coordinator import PoinTTAPIDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

VALUE_KEY = "value"

# Water heater operation mode mapping: API value <-> user-friendly label
# API accepts: "ownprogram" (auto/schedule), "Off", "high" (always on at high temp)
_API_TO_OP = {"ownprogram": "Auto", "Off": "Off", "high": "On"}
_OP_TO_API = {v: k for k, v in _API_TO_OP.items()}


def _val(data: dict[str, Any], path: str, key: str = VALUE_KEY) -> Any:
    """Get key (default 'value') from data[path] if present."""
    obj = data.get(path) if data else None
    return obj.get(key) if isinstance(obj, dict) else None


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


def _resolve_device_info(
    uuid: str,
    path: str | None = None,
    *,
    kind: str | None = None,
    zone_display_suffix: str | None = None,
) -> DeviceInfo:
    """Return the DeviceInfo for this entity based on its path and/or kind.

    See module-level routing table comment above.
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
        suffix = zone_display_suffix if zone_display_suffix is not None else (
            "" if zid == "zn1" else f" {zid}"
        )
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
    """Sensor description with optional value_fn and last_reset_fn."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None
    last_reset_fn: Callable[[], Any] | None = None


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
    """Climate entity for POINTTAPI zone (zn1): current/setpoint from coordinator.data."""

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
        self._attr_device_info = _resolve_device_info(uuid, f"/zones/{zone_id}")
        self._current: float | None = None
        self._target: float | None = None
        self._hvac_mode = HVACMode.HEAT

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
        if user_mode == "manual" and manual_temp is not None and float(manual_temp) <= self.min_temp:
            self._hvac_mode = HVACMode.OFF
        else:
            self._hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()

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
            _LOGGER.warning("POINTTAPI set temperature failed: %s", err)
            await self.coordinator.async_request_refresh()

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
                _LOGGER.warning("POINTTAPI set hvac_mode OFF failed: %s", err)
                await self.coordinator.async_request_refresh()
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
            _LOGGER.warning("POINTTAPI set hvac_mode failed: %s", err)
            await self.coordinator.async_request_refresh()


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
            _LOGGER.warning("POINTTAPI water heater set temperature failed: %s", err)
            await self.coordinator.async_request_refresh()

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
            _LOGGER.warning("POINTTAPI water heater set operation_mode failed: %s", err)
            await self.coordinator.async_request_refresh()


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
        self._attr_device_info = _resolve_device_info(uuid, path)
        self._path = path
        self._native_value: Any = None
        self._last_reset: Any = None
        # RSSI was previously disabled by default (task 8.3) — now enabled for monitoring

    @callback
    def _handle_coordinator_update(self) -> None:
        """Read value from coordinator.data for this path."""
        data = self.coordinator.data or {}
        desc = self.entity_description
        if isinstance(desc, BoschPoinTTAPISensorEntityDescription) and desc.value_fn is not None:
            self._native_value = desc.value_fn(data)
            if desc.last_reset_fn is not None:
                self._last_reset = desc.last_reset_fn()
        else:
            self._native_value = _val(data, self._path)
        self.async_write_ha_state()

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
        name="Boost temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=5.0,
        native_max_value=30.0,
        native_step=0.5,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/boostDuration",
        name="Boost duration",
        native_unit_of_measurement=UnitOfTime.HOURS,
        native_min_value=0.5,
        native_max_value=24.0,
        native_step=0.5,
    ),
    # ── Heating circuit configuration (2b) ───────────────────────────────────
    NumberEntityDescription(
        key="/heatingCircuits/hc1/maxSupply",
        name="Max supply temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=25.0,
        native_max_value=90.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/minSupply",
        name="Min supply temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=10.0,
        native_max_value=90.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/nightThreshold",
        name="Night setback threshold",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=5.0,
        native_max_value=30.0,
        native_step=0.5,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/suWiThreshold",
        name="Summer/winter threshold",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=10.0,
        native_max_value=30.0,
        native_step=0.5,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/heatingCircuits/hc1/roomInfluence",
        name="Room influence",
        native_min_value=0.0,
        native_max_value=3.0,
        native_step=1.0,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/system/sensors/temperatures/offset",
        name="Temperature calibration offset",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=-5.0,
        native_max_value=5.0,
        native_step=0.5,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="/energy/gas/annualGoal",
        name="Annual gas goal",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        native_min_value=0.0,
        native_max_value=1000000.0,
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
        self._attr_device_info = _resolve_device_info(uuid, description.key)
        self._native_value: float | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        raw = _val(data, self._path)
        self._native_value = float(raw) if raw is not None else None
        self.async_write_ha_state()

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
            _LOGGER.warning("POINTTAPI set %s failed: %s", self._path, err)
            await self.coordinator.async_request_refresh()


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
    _attr_name = "Boost"

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
        self._attr_device_info = _resolve_device_info(uuid, "/zones/zn1")
        self._is_on: bool = False
        self._pre_boost_mode: str | None = None
        # Track boost state explicitly rather than deriving from zone state,
        # because the zone state lags behind PUT calls and causes flicker.
        self._boost_set_by_us: bool = False

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
        """Turn boost on: switch zone to manual + set boost temperature."""
        try:
            data = self.coordinator.data or {}
            boost_temp = _val(data, "/heatingCircuits/hc1/boostTemperature") or 26.0
            # Remember current mode so we can restore it
            self._pre_boost_mode = _val(data, "/zones/zn1/userMode") or "clock"
            await self.coordinator.client.put("/zones/zn1/userMode", "manual")
            await self.coordinator.client.put(
                "/zones/zn1/manualTemperatureHeating", float(boost_temp)
            )
            self._boost_set_by_us = True
            self._is_on = True
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("POINTTAPI boost turn_on failed: %s", err)
            self._boost_set_by_us = False
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn boost off: restore zone to clock mode."""
        try:
            restore_mode = self._pre_boost_mode or "clock"
            await self.coordinator.client.put("/zones/zn1/userMode", restore_mode)
            self._boost_set_by_us = True
            self._is_on = False
            self._pre_boost_mode = None
            self.async_write_ha_state()
            # After one successful refresh with the restored state, stop overriding
            self.coordinator.async_add_listener(self._clear_boost_flag)
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("POINTTAPI boost turn_off failed: %s", err)
            self._boost_set_by_us = False
            await self.coordinator.async_request_refresh()

    @callback
    def _clear_boost_flag(self) -> None:
        """Clear the boost override flag after one coordinator cycle."""
        self._boost_set_by_us = False
        # Remove ourselves — one-shot listener
        self.coordinator.async_remove_listener(self._clear_boost_flag)


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
        name="Auto firmware update",
        entity_category=EntityCategory.CONFIG,
    ),
    BoschPoinTTAPISwitchEntityDescription(
        key="/gateway/notificationLight/enabled",
        name="Notification light",
        entity_category=EntityCategory.CONFIG,
    ),
    BoschPoinTTAPISwitchEntityDescription(
        key="/dhwCircuits/dhw1/thermalDisinfect/state",
        name="Thermal disinfect",
        device_id_suffix="dhw1",
        device_name_override="Water heater",
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
            _LOGGER.warning("POINTTAPI switch %s turn_on failed: %s", self._path, err)
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.put(self._path, self.entity_description.off_value)
            self._is_on = False
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("POINTTAPI switch %s turn_off failed: %s", self._path, err)
            await self.coordinator.async_request_refresh()


# ── Select entity ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BoschPoinTTAPISelectEntityDescription(SelectEntityDescription):
    """Select description for POINTTAPI option paths."""

    options: tuple[str, ...] = ()


POINTTAPI_SELECT_DESCRIPTIONS: tuple[BoschPoinTTAPISelectEntityDescription, ...] = (
    BoschPoinTTAPISelectEntityDescription(
        key="/zones/zn1/userMode",
        name="Zone mode",
        options=("clock", "manual"),
    ),
    BoschPoinTTAPISelectEntityDescription(
        key="/gateway/pirSensitivity",
        name="PIR sensitivity",
        options=("high", "medium", "low"),
        entity_category=EntityCategory.CONFIG,
    ),
    BoschPoinTTAPISelectEntityDescription(
        key="/heatingCircuits/hc1/suWiSwitchMode",
        name="Summer/winter mode",
        options=("off", "automatic", "manual"),
        entity_category=EntityCategory.CONFIG,
    ),
    BoschPoinTTAPISelectEntityDescription(
        key="/heatingCircuits/hc1/nightSwitchMode",
        name="Night switch mode",
        options=("off", "automatic", "reduced"),
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
        self._attr_options = list(description.options)
        self._attr_device_info = _resolve_device_info(uuid, description.key)
        self._current_option: str | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        self._current_option = _val(data, self._path)
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.client.put(self._path, option)
            self._current_option = option
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("POINTTAPI select %s failed: %s", self._path, err)
            await self.coordinator.async_request_refresh()


# ── Binary-sensor surface for POINTTAPI ─────────────────────────────────────


@dataclass(frozen=True)
class BoschPoinTTAPIBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary-sensor description with optional value_fn override.

    When `value_fn` is None, the entity falls back to the default on/off-string
    resolver on `coordinator.data[key]["value"]`.
    """

    value_fn: Callable[[dict[str, Any]], bool | None] | None = None


def _resolve_on_off(raw: Any) -> bool | None:
    """Map an API value to True/False/None (case-insensitive trim of 'on'/'off')."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v == "on":
            return True
        if v == "off":
            return False
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
)
