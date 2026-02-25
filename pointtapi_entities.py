"""POINTTAPI coordinator-based entities: climate, water_heater, sensors.

All use CoordinatorEntity; device_info and unique_id follow 2-tuple and entry_id + path.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.components.water_heater import (
    STATE_OFF,
    STATE_ON,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfPressure, UnitOfTemperature
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
        """Set target temperature via POINTTAPI PUT (task 6.1)."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        path = f"/zones/{self._zone_id}/temperatureHeatingSetpoint"
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


# Curated POINTTAPI sensors: path, name, device_class, entity_category (5.3 + 5.4)
def _pointtapi_sensor_descriptions():
    from homeassistant.components.sensor import SensorDeviceClass
    return (
        SensorEntityDescription(
            key="/system/sensors/temperatures/outdoor_t1",
            translation_key="outdoor_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        ),
        SensorEntityDescription(
            key="/system/sensors/humidity/indoor_h1",
            translation_key="indoor_humidity",
            device_class=SensorDeviceClass.HUMIDITY,
            native_unit_of_measurement="%",
        ),
        SensorEntityDescription(
            key="/zones/zn1/actualValvePosition",
            translation_key="valve_position",
            native_unit_of_measurement="%",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="/system/appliance/systemPressure",
            translation_key="system_pressure",
            device_class=SensorDeviceClass.PRESSURE,
            native_unit_of_measurement=UnitOfPressure.BAR,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="/gateway/wifi/rssi",
            translation_key="wifi_rssi",
            device_class=SensorDeviceClass.SIGNAL_STRENGTH,
            native_unit_of_measurement="dBm",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="/gateway/update/state",
            translation_key="update_state",
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
        self._native_value = _val(data, self._path)
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        return self._native_value
