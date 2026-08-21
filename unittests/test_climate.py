"""Unit tests for the legacy Bosch climate platform."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bosch_thermostat_client.const import HVAC_HEAT, HVAC_OFF, SETPOINT
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE

from custom_components.bosch.climate import BoschThermostat, async_setup_entry
from custom_components.bosch.const import (
    BOSCH_STATE,
    CONF_PROTOCOL,
    POINTTAPI,
    SIGNAL_BOSCH,
    SWITCHPOINT,
)


def _bosch_object(**overrides):
    values = {
        "attr_id": "/heatingCircuits/hc1",
        "id": "hc1",
        "name": "Living room",
        "parent_id": None,
        "ha_modes": [HVACMode.HEAT, HVACMode.OFF],
        "ha_mode": HVACMode.HEAT,
        "target_temperature": 21.0,
        "current_temp": 19.5,
        "min_temp": 5.0,
        "max_temp": 30.0,
        "temp_units": "C",
        "state": "idle",
        "hvac_action": HVAC_HEAT,
        "preset_modes": ["comfort"],
        "preset_mode": "comfort",
        "support_presets": True,
        "update_initialized": True,
        "setpoint": 21.0,
        "schedule": None,
        "extra_state_attributes": {"source": "test"},
    }
    values.update(overrides)
    obj = SimpleNamespace(**values)
    obj.set_ha_mode = AsyncMock(return_value=1)
    obj.set_temperature = AsyncMock()
    obj.set_preset_mode = AsyncMock()
    return obj


def _gateway():
    return SimpleNamespace(
        device_model="Condens 7000i",
        device_type="CT200",
        firmware="1.2.3",
        heating_circuits=[],
    )


def _entity(**overrides):
    entity = BoschThermostat(
        hass="hass",
        uuid="uuid1",
        bosch_object=_bosch_object(**overrides),
        gateway=_gateway(),
    )
    entity.schedule_update_ha_state = MagicMock()
    entity.async_schedule_update_ha_state = MagicMock()
    return entity


class TestBoschThermostatProperties:
    def test_exposes_modes_presets_and_supported_features(self):
        entity = _entity()

        assert entity.hvac_mode == HVACMode.HEAT
        assert entity.hvac_modes == [HVACMode.HEAT, HVACMode.OFF]
        assert entity.preset_modes == ["comfort"]
        assert entity.preset_mode == "comfort"
        assert entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
        assert entity.supported_features & ClimateEntityFeature.PRESET_MODE
        assert entity.supported_features & ClimateEntityFeature.TURN_ON
        assert entity.supported_features & ClimateEntityFeature.TURN_OFF

    def test_supported_features_without_presets_or_off(self):
        entity = _entity(
            ha_modes=[HVACMode.HEAT],
            support_presets=False,
        )

        assert entity.supported_features == ClimateEntityFeature.TARGET_TEMPERATURE

    @pytest.mark.parametrize(
        "bosch_action, expected",
        [(HVAC_HEAT, HVACAction.HEATING), (HVAC_OFF, HVACAction.IDLE), ("unknown", None)],
    )
    def test_hvac_action_maps_bosch_state(self, bosch_action, expected):
        assert _entity(hvac_action=bosch_action).hvac_action == expected

    def test_extra_attributes_include_setpoint_schedule_state_and_custom_data(self):
        schedule = SimpleNamespace(active_program="weekday")
        entity = _entity(schedule=schedule, state="heating")
        entity._state = "heating"

        assert entity.extra_state_attributes == {
            SETPOINT: 21.0,
            SWITCHPOINT: "weekday",
            BOSCH_STATE: "heating",
            "source": "test",
        }

    def test_extra_attributes_are_empty_when_object_does_not_implement_properties(self):
        class ObjectWithoutSetpoint:
            @property
            def setpoint(self):
                raise NotImplementedError

        entity = _entity()
        entity._bosch_object = ObjectWithoutSetpoint()

        assert entity.extra_state_attributes == {}


class TestBoschThermostatCommands:
    @pytest.mark.asyncio
    async def test_set_hvac_mode_success_updates_optimistically(self):
        entity = _entity()
        entity._optimistic_mode = True

        assert await entity.async_set_hvac_mode(HVACMode.OFF) is True

        assert entity.hvac_mode == HVACMode.OFF
        entity._bosch_object.set_ha_mode.assert_awaited_once_with(HVACMode.OFF)
        entity.schedule_update_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_failure_reverts_optimistic_state(self):
        entity = _entity()
        entity._optimistic_mode = True
        entity._bosch_object.set_ha_mode.return_value = 0

        assert await entity.async_set_hvac_mode(HVACMode.OFF) is False

        assert entity.hvac_mode == HVACMode.HEAT
        assert entity.schedule_update_ha_state.call_count == 2

    @pytest.mark.asyncio
    async def test_set_temperature_updates_optimistically(self):
        entity = _entity()
        entity._optimistic_mode = True

        await entity.async_set_temperature(**{ATTR_TEMPERATURE: 23.5})

        entity._bosch_object.set_temperature.assert_awaited_once_with(23.5)
        assert entity.target_temperature == 23.5
        entity.schedule_update_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_preset_mode_delegates_to_bosch_object(self):
        entity = _entity()

        await entity.async_set_preset_mode("away")

        entity._bosch_object.set_preset_mode.assert_awaited_once_with("away")


class TestBoschThermostatUpdate:
    @pytest.mark.asyncio
    async def test_update_ignores_uninitialized_object(self):
        entity = _entity(update_initialized=False)

        await entity.async_update()

        entity.async_schedule_update_ha_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_refreshes_changed_values(self):
        entity = _entity()
        entity._bosch_object.state = "heating"
        entity._bosch_object.target_temperature = 22.0
        entity._bosch_object.current_temp = 20.0
        entity._bosch_object.ha_modes = [HVACMode.HEAT]
        entity._bosch_object.ha_mode = HVACMode.HEAT

        await entity.async_update()

        assert entity._state == "heating"
        assert entity.target_temperature == 22.0
        assert entity.current_temperature == 20.0
        assert entity.hvac_modes == [HVACMode.HEAT]
        entity.async_schedule_update_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_does_not_schedule_when_values_are_unchanged(self):
        entity = _entity()
        entity._state = entity._bosch_object.state
        entity._target_temperature = entity._bosch_object.target_temperature
        entity._current_temperature = entity._bosch_object.current_temp
        entity._hvac_modes = entity._bosch_object.ha_modes
        entity._hvac_mode = entity._bosch_object.ha_mode

        await entity.async_update()

        entity.async_schedule_update_ha_state.assert_not_called()


class TestClimateSetup:
    @pytest.mark.asyncio
    async def test_setup_legacy_creates_entities_and_dispatches(self):
        hass = MagicMock()
        gateway = _gateway()
        gateway.heating_circuits = [_bosch_object(), _bosch_object(id="hc2", name="Bedroom")]
        runtime_data = SimpleNamespace(gateway=gateway)
        config_entry = SimpleNamespace(
            data={"uuid": "uuid1"},
            options={},
            runtime_data=runtime_data,
        )
        add_entities = MagicMock()

        with patch("custom_components.bosch.climate.async_dispatcher_send") as dispatch:
            assert await async_setup_entry(hass, config_entry, add_entities) is True

        assert len(runtime_data.climate) == 2
        add_entities.assert_called_once_with(runtime_data.climate)
        dispatch.assert_called_once_with(hass, SIGNAL_BOSCH)

    @pytest.mark.asyncio
    async def test_setup_pointtapi_without_coordinator_adds_no_entities(self):
        hass = MagicMock()
        config_entry = SimpleNamespace(
            data={CONF_PROTOCOL: POINTTAPI, "uuid": "uuid1"},
            options={},
            runtime_data=SimpleNamespace(coordinator=None, gateway=None),
        )
        add_entities = MagicMock()

        assert await async_setup_entry(hass, config_entry, add_entities) is True

        add_entities.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_setup_pointtapi_creates_one_entity_per_zone(self):
        hass = MagicMock()
        coordinator = MagicMock(data={})
        config_entry = SimpleNamespace(
            data={CONF_PROTOCOL: POINTTAPI, "uuid": "uuid1"},
            options={},
            entry_id="entry1",
            runtime_data=SimpleNamespace(coordinator=coordinator, gateway=None),
        )
        add_entities = MagicMock()

        with patch(
            "custom_components.bosch.climate._pointtapi_zone_ids",
            return_value=["zn1", "zn2"],
        ):
            assert await async_setup_entry(hass, config_entry, add_entities) is True

        entities = list(add_entities.call_args.args[0])
        assert len(entities) == 2
        assert [entity._zone_id for entity in entities] == ["zn1", "zn2"]


def test_legacy_climate_does_not_poll():
    assert _entity().should_poll is False
