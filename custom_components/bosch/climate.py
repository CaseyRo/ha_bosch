"""Support for Bosch Thermostat Climate."""
from __future__ import annotations
import logging
from typing import Any

from bosch_thermostat_client.const import HVAC_HEAT, HVAC_OFF, SETPOINT
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACAction,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .bosch_entity import BoschClimateWaterEntity
from .const import (
    BOSCH_STATE,
    CLIMATE,
    CONF_PROTOCOL,
    DOMAIN,
    GATEWAY,
    POINTTAPI,
    SIGNAL_BOSCH,
    SIGNAL_CLIMATE_UPDATE_BOSCH,
    SWITCHPOINT,
    UNITS_CONVERTER,
    UUID,
)
from .pointtapi_entities import BoschPoinTTAPIClimateEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Bosch thermostat from a config entry."""
    if config_entry.data.get(CONF_PROTOCOL) == POINTTAPI:
        uuid = config_entry.data.get(UUID)
        data = hass.data.get(DOMAIN, {}).get(uuid) if uuid else {}
        coordinator = data.get("coordinator")
        if coordinator:
            async_add_entities([
                BoschPoinTTAPIClimateEntity(
                    coordinator, config_entry.entry_id, uuid, zone_id="zn1"
                )
            ])
        else:
            async_add_entities([])
        return True
    uuid = config_entry.data[UUID]
    data = hass.data[DOMAIN][uuid]
    optimistic_mode = config_entry.options.get("optimistic_mode", False)
    data[CLIMATE] = [
        BoschThermostat(
            hass=hass,
            uuid=uuid,
            bosch_object=hc,
            gateway=data[GATEWAY],
            optimistic_mode=optimistic_mode,
        )
        for hc in data[GATEWAY].heating_circuits
    ]
    async_add_entities(data[CLIMATE])
    async_dispatcher_send(hass, SIGNAL_BOSCH)
    return True


class BoschThermostat(BoschClimateWaterEntity, ClimateEntity):
    """Representation of a Bosch thermostat."""

    signal = SIGNAL_CLIMATE_UPDATE_BOSCH

    def __init__(
        self, hass, uuid, bosch_object, gateway, optimistic_mode: bool = False
    ) -> None:
        """Initialize the thermostat."""
        self._name_prefix = (
            "Zone circuit " if "/zones" in bosch_object.attr_id else "Heating circuit "
        )
        self._mode = {}
        self._hvac_modes = []
        self._hvac_mode = None
        self._optimistic_mode = optimistic_mode
        self._is_enabled = True

        super().__init__(
            hass=hass, uuid=uuid, bosch_object=bosch_object, gateway=gateway
        )
        self._hvac_modes = bosch_object.ha_modes
        self._hvac_mode = bosch_object.ha_mode
        self._target_temperature = bosch_object.target_temperature
        self._current_temperature = bosch_object.current_temp

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra attributes of entity."""
        data = {}
        try:
            data[SETPOINT] = self._bosch_object.setpoint
            if self._bosch_object.schedule:
                data[SWITCHPOINT] = self._bosch_object.schedule.active_program
            data[BOSCH_STATE] = self._state
            if self._bosch_object.extra_state_attributes:
                data.update(self._bosch_object.extra_state_attributes)
        except NotImplementedError:
            pass
        return data

    @property
    def supported_features(self):
        """Return the list of supported features."""
        features = ClimateEntityFeature.TARGET_TEMPERATURE | (
            ClimateEntityFeature.PRESET_MODE
            if self._bosch_object.support_presets
            else 0
        )
        if HVACMode.OFF in self.hvac_modes:
            features |= ClimateEntityFeature.TURN_OFF
            features |= ClimateEntityFeature.TURN_ON
        return features

    async def async_set_hvac_mode(self, hvac_mode):
        """Set operation mode."""
        _LOGGER.debug(f"Setting operation mode {hvac_mode}.")

        if self._optimistic_mode:
            _old_hvac_mode = self._bosch_object.ha_mode
            self._hvac_mode = hvac_mode
            self.schedule_update_ha_state()
        status = await self._bosch_object.set_ha_mode(hvac_mode)
        if status > 0:
            return True
        if self._optimistic_mode:
            """If fail revert back to mode it was back then."""
            self._hvac_mode = _old_hvac_mode
            self.schedule_update_ha_state()
        return False

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        _LOGGER.debug(f"Setting target temperature {temperature}.")
        await self._bosch_object.set_temperature(temperature)
        if self._optimistic_mode:
            self._target_temperature = temperature
            self.schedule_update_ha_state()

    @property
    def hvac_mode(self):
        """Return current operation ie. heat, cool, idle."""
        return self._hvac_mode

    @property
    def hvac_action(self):
        """Hvac action."""
        hvac_action = self._bosch_object.hvac_action
        if hvac_action == HVAC_HEAT:
            return HVACAction.HEATING
        if hvac_action == HVAC_OFF:
            return HVACAction.IDLE

    @property
    def hvac_modes(self) -> list:
        """List of available operation modes."""
        return self._hvac_modes

    @property
    def preset_modes(self):
        """Return available preset modes."""
        return self._bosch_object.preset_modes

    @property
    def preset_mode(self):
        """Return current preset mode."""
        return self._bosch_object.preset_mode

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        await self._bosch_object.set_preset_mode(preset_mode)

    async def async_update(self):
        """Update state of device."""
        _LOGGER.debug(
            "Updating climate entity: name=%s, entity_id=%s, unique_id=%s",
            self._name,
            self.entity_id,
            self.unique_id,
        )
        if not self._bosch_object or not self._bosch_object.update_initialized:
            return
        self._temperature_unit = UNITS_CONVERTER.get(self._bosch_object.temp_units)
        if (
            self._state != self._bosch_object.state
            or self._target_temperature != self._bosch_object.target_temperature
            or self._current_temperature != self._bosch_object.current_temp
            or self._hvac_modes != self._bosch_object.ha_modes
            or self._hvac_mode != self._bosch_object.ha_mode
        ):
            self._state = self._bosch_object.state
            self._target_temperature = self._bosch_object.target_temperature
            self._current_temperature = self._bosch_object.current_temp
            self._hvac_modes = self._bosch_object.ha_modes
            self._hvac_mode = self._bosch_object.ha_mode
            self.async_schedule_update_ha_state()

    @property
    def should_poll(self):
        """Don't poll."""
        return False
