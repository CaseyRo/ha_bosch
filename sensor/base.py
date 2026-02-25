"""Base sensor component."""

import logging
from datetime import timedelta

from bosch_thermostat_client.const import NAME, UNITS, VALUE
from bosch_thermostat_client.const.ivt import INVALID
from bosch_thermostat_client.sensors.sensor import Sensor as BoschSensor
from homeassistant.const import EntityCategory
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.util import dt as dt_util

from ..bosch_entity import BoschEntity
from ..const import UNITS_CONVERTER

_LOGGER = logging.getLogger(__name__)

entity_categories = {"diagnostic": EntityCategory.DIAGNOSTIC}


class BoschBaseSensor(BoschEntity, SensorEntity):
    """Base class for all sensor entities."""

    def __init__(
        self,
        hass,
        uuid,
        bosch_object: BoschSensor,
        gateway,
        name,
        attr_uri,
        domain_name=None,
        circuit_type=None,
        is_enabled=False,
    ):
        """Initialize the sensor."""
        super().__init__(
            hass=hass,
            uuid=uuid,
            bosch_object=bosch_object,
            gateway=gateway,
            domain_name=domain_name,
        )
        if not circuit_type:
            self._name = (
                f"{domain_name} {name}"
                if domain_name != "Sensors" and domain_name
                else name
            )
        else:
            self._name = f"{self._bosch_object.parent_id} {name}"
        self._attr_uri = attr_uri
        self._attr_device_class = None
        self._attr_state_class = None
        if self._bosch_object.device_class:
            self._attr_device_class = self._bosch_object.device_class
        if self._bosch_object.state_class:
            self._attr_state_class = self._bosch_object.state_class
        if self._attr_state_class == "total" and (
            self._attr_device_class == "temperature"
            or getattr(self._bosch_object, "unit_of_measurement", None)
            in ("%", "C", "°C", "F", "°F")
        ):
            self._attr_state_class = "measurement"
        if attr_uri in ("startTime", "startDateTime"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_entity_category = entity_categories.get(
            self._bosch_object.entity_category, None
        )
        self._state = None
        self._update_init = True
        self._unit_of_measurement = None
        self._uuid = uuid
        if not hasattr(self, "_attr_unique_id") or not self._attr_unique_id:
            self._attr_unique_id = (
                f"{self._domain_name}{self._bosch_object.parent_id}{self._bosch_object.id}{self._uuid}"
                if self._bosch_object.parent_id
                else f"{self._domain_name}{self._bosch_object.id}{self._uuid}"
            )

        self._attrs = {}
        self._circuit_type = circuit_type
        self._attr_entity_registry_enabled_default = is_enabled

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self._state == "unavailable":
            return None
        return self._state

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement of the sensor."""
        return self._unit_of_measurement

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        return self._attrs

    async def async_update(self):
        """Update state of device."""
        _LOGGER.debug(
            "Updating sensor: unique_id=%s, name=%s, uri=%s",
            self.unique_id,
            self._name,
            self._attr_uri,
        )
        data = self._bosch_object.get_property(self._attr_uri)

        def get_units():
            if not isinstance(data, list):
                return UNITS_CONVERTER.get(data.get(UNITS))
            return None

        def check_name():
            if data.get(NAME, "") != self._name:
                self._name = data.get(NAME)

        units = get_units()

        if data.get(INVALID, False):
            self._state = None
        else:
            if (_state := data.get(VALUE, INVALID)) in (INVALID, "unavailable"):
                self._state = None
            else:
                self._state = _state
            if self._attr_uri == "energyConsumption":
                # Device reports in kJ, convert to kWh (1 kWh = 3600 kJ)
                self._state = round(float(self._state) / 3600, 2)
            if self._attr_uri in ("systemUptime", "totalSystem"):
                try:
                    self._state = str(timedelta(seconds=int(self._state)))
                    units = None
                except (ValueError, TypeError):
                    pass
            if self._attr_uri in ("startTime", "startDateTime"):
                units = None
                if isinstance(self._state, str):
                    dt_obj = dt_util.parse_datetime(self._state)
                    if dt_obj:
                        if dt_obj.tzinfo is None:
                            dt_obj = dt_obj.replace(tzinfo=dt_util.now().tzinfo)
                        self._state = dt_obj
                    else:
                        self._state = None
            check_name()

        self._attrs = {}
        if not data:
            if not self._bosch_object.update_initialized:
                self._state = (
                    None
                    if self._attr_state_class
                    and self._attr_state_class == "measurement"
                    else self._bosch_object.state
                )
                self._attrs["stateExtra"] = self._bosch_object.state_message
            return
        self.attrs_write(
            data={
                **data,
                "stateExtra": self._bosch_object.state,
                "path": self._bosch_object.path,
            },
            units=units,
        )

    def attrs_write(self, data, units):
        self._attrs = data
        if self._state != INVALID:
            self._unit_of_measurement = units
        if self._update_init:
            self._update_init = False
        self.async_schedule_update_ha_state()

    @property
    def should_poll(self):
        """Don't poll."""
        return False
