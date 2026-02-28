"""POINTTAPI coordinator-based entities: climate, water_heater, sensors.

All use CoordinatorEntity; device_info and unique_id follow 2-tuple and entry_id + path.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
    STATE_OFF,
    STATE_ON,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfEnergy, UnitOfPressure, UnitOfTemperature, UnitOfTime, UnitOfVolume
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .pointtapi_coordinator import PoinTTAPIDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

VALUE_KEY = "value"

# Water heater operation mode mapping: API value <-> user-friendly label
_API_TO_OP = {"ownprogram": "Auto", "off": "Off", "on": "On"}
_OP_TO_API = {v: k for k, v in _API_TO_OP.items()}


def _val(data: dict[str, Any], path: str, key: str = VALUE_KEY) -> Any:
    """Get key (default 'value') from data[path] if present."""
    obj = data.get(path) if data else None
    return obj.get(key) if isinstance(obj, dict) else None


# ── Custom sensor description with optional value_fn ─────────────────────────


@dataclass(frozen=True)
class BoschPoinTTAPISensorEntityDescription(SensorEntityDescription):
    """Sensor description with optional value_fn for computed/derived values."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None


# ── Gas usage helper functions ────────────────────────────────────────────────


def _gas_history_entries(data: dict[str, Any]) -> list | None:
    history = data.get("/energy/history") or {}
    entries = history.get("value") if isinstance(history, dict) else None
    return entries if isinstance(entries, list) and entries else None


def _gas_ch_today(data: dict[str, Any]) -> float | None:
    entries = _gas_history_entries(data)
    return entries[-1].get("gCh") if entries is not None else None


def _gas_hw_today(data: dict[str, Any]) -> float | None:
    entries = _gas_history_entries(data)
    return entries[-1].get("gHw") if entries is not None else None


def _gas_total_today(data: dict[str, Any]) -> float | None:
    entries = _gas_history_entries(data)
    if entries is None:
        return None
    last = entries[-1]
    return (last.get("gCh") or 0.0) + (last.get("gHw") or 0.0)


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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{uuid}_{zone_id}")},
            via_device=(DOMAIN, uuid),
            name=f"Zone {zone_id}",
        )
        self._current: float | None = None
        self._target: float | None = None
        self._hvac_mode = HVACMode.HEAT

    @callback
    def _handle_coordinator_update(self) -> None:
        """Read from coordinator.data and set state."""
        data = self.coordinator.data or {}
        self._current = _val(data, f"/zones/{self._zone_id}/temperatureActual")
        self._target = _val(data, f"/zones/{self._zone_id}/temperatureHeatingSetpoint")
        control = _val(data, "/heatingCircuits/hc1/control")
        if control == "off":
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
        """Set target temperature via POINTTAPI PUT."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        path = f"/zones/{self._zone_id}/manualTemperatureHeating"
        try:
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
        """Set HVAC mode via POINTTAPI PUT (task 6.2)."""
        value = "off" if hvac_mode == HVACMode.OFF else "auto"
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{uuid}_dhw1")},
            via_device=(DOMAIN, uuid),
            name="Water heater",
        )
        self._current_temp: float | None = None
        self._target_temp: float | None = None
        self._state: str | None = None
        self._operation_mode: str | None = None
        # User-friendly labels; mapped to/from API values via _OP_TO_API / _API_TO_OP
        self._attr_operation_list = ["Auto", "Off", "On"]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Read from coordinator.data and set state."""
        data = self.coordinator.data or {}
        self._current_temp = _val(data, "/dhwCircuits/dhw1/actualTemp")
        self._target_temp = _val(data, "/dhwCircuits/dhw1/temperatureLevels/high")
        self._state = _val(data, "/dhwCircuits/dhw1/state")
        raw_op = _val(data, "/dhwCircuits/dhw1/operationMode")
        self._operation_mode = _API_TO_OP.get(raw_op, raw_op)
        self.async_write_ha_state()

    @property
    def current_temperature(self) -> float | None:
        return self._current_temp

    @property
    def target_temperature(self) -> float | None:
        return self._target_temp

    @property
    def state(self) -> str | None:
        if self._state == "on":
            return STATE_ON
        if self._state == "off":
            return STATE_OFF
        return self._state

    @property
    def operation_mode(self) -> str | None:
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
        # ── Gas usage sensors (1a) ────────────────────────────────────────────
        BoschPoinTTAPISensorEntityDescription(
            key="/energy/history_ch",
            translation_key="gas_heating_yesterday",
            device_class=SensorDeviceClass.GAS,
            native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_gas_ch_today,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/energy/history_hw",
            translation_key="gas_hot_water_yesterday",
            device_class=SensorDeviceClass.GAS,
            native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_gas_hw_today,
        ),
        BoschPoinTTAPISensorEntityDescription(
            key="/energy/history_total",
            translation_key="gas_total_yesterday",
            device_class=SensorDeviceClass.GAS,
            native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_gas_total_today,
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
        if path.startswith("/zones"):
            device_id = f"{uuid}_zn1"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, device_id)},
                via_device=(DOMAIN, uuid),
                name="Zone zn1",
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, uuid)},
                name="POINTTAPI",
            )
        self._path = path
        self._native_value: Any = None
        # Disable by default for high-churn diagnostic (e.g. RSSI) - task 8.3
        if path == "/gateway/wifi/rssi":
            self._attr_entity_registry_enabled_default = False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Read value from coordinator.data for this path."""
        data = self.coordinator.data or {}
        desc = self.entity_description
        if isinstance(desc, BoschPoinTTAPISensorEntityDescription) and desc.value_fn is not None:
            self._native_value = desc.value_fn(data)
        else:
            self._native_value = _val(data, self._path)
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        return self._native_value


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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uuid)},
        )
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
    """Switch entity for POINTTAPI: one-tap boost on/off."""

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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uuid)},
        )
        self._is_on: bool = False

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        boost = _val(data, "/heatingCircuits/hc1/boostMode")
        self._is_on = boost == "on"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn boost on."""
        try:
            await self.coordinator.client.put("/heatingCircuits/hc1/boostMode", "on")
            self._is_on = True
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("POINTTAPI boost turn_on failed: %s", err)
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn boost off."""
        try:
            await self.coordinator.client.put("/heatingCircuits/hc1/boostMode", "off")
            self._is_on = False
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("POINTTAPI boost turn_off failed: %s", err)
            await self.coordinator.async_request_refresh()


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
        if description.device_id_suffix:
            device_id = f"{uuid}_{description.device_id_suffix}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, device_id)},
                via_device=(DOMAIN, uuid),
                name=description.device_name_override or description.device_id_suffix,
            )
        else:
            self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, uuid)})
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
        if description.key.startswith("/zones"):
            device_id = f"{uuid}_zn1"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, device_id)},
                via_device=(DOMAIN, uuid),
                name="Zone zn1",
            )
        else:
            self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, uuid)})
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
