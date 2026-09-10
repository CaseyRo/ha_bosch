"""Robustness tests for POINTTAPI coordinator entities.

Two design guarantees pinned here that the existing entity tests don't cover:

  1. Absent path -> unavailable / None, never a stale default. An entity whose
     backing resource path is missing from coordinator.data must report None
     (or available=False), not a leftover value.
  2. Optimistic write-then-refresh. Writeable entities PUT to the correct path
     with the correct payload, update local state optimistically, then request
     a coordinator refresh.

Also: a present-but-malformed value (non-dict container, missing "value",
wrong type) must not raise out of the @callback _handle_coordinator_update.

Representative entities: one sensor (plain + available_fn), one number, one
select, the climate entity, the water_heater entity. Assertions already made
in test_pointtapi_new_entities / _routing / _boost are not repeated.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.components.climate.const import HVACAction
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.bosch.pointtapi_entities import (
    POINTTAPI_NUMBER_DESCRIPTIONS,
    POINTTAPI_SWITCH_DESCRIPTIONS,
    BoschPoinTTAPIClimateEntity,
    BoschPoinTTAPIBoostSwitchEntity,
    BoschPoinTTAPIGenericSwitchEntity,
    BoschPoinTTAPINumberEntity,
    BoschPoinTTAPISelectEntity,
    BoschPoinTTAPISensorEntity,
    BoschPoinTTAPIWaterHeaterEntity,
    _path_available,
    _pointtapi_select_descriptions,
    _pointtapi_sensor_descriptions,
    _solar_data_available,
)


def _coord(data):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = True
    coord.boost_session = None  # so sensor handler skips boost injection
    coord.client = MagicMock()
    coord.client.put = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    coord.async_refresh_boost_state = AsyncMock()
    coord.async_set_zone_boost = AsyncMock()
    return coord


def _sensor(coord, key):
    desc = next(d for d in _pointtapi_sensor_descriptions() if d.key == key)
    ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
    ent.async_write_ha_state = MagicMock()
    return ent


def _number(coord, key):
    desc = next(d for d in POINTTAPI_NUMBER_DESCRIPTIONS if d.key == key)
    ent = BoschPoinTTAPINumberEntity(coord, "entry1", "uuid1", desc)
    ent.async_write_ha_state = MagicMock()
    return ent


def _select(coord, key):
    desc = next(d for d in _pointtapi_select_descriptions(coord.data) if d.key == key)
    ent = BoschPoinTTAPISelectEntity(coord, "entry1", "uuid1", desc)
    ent.async_write_ha_state = MagicMock()
    return ent


def _climate(coord):
    ent = BoschPoinTTAPIClimateEntity(coord, "entry1", "uuid1", "zn1")
    ent.async_write_ha_state = MagicMock()
    return ent


def _water_heater(coord):
    ent = BoschPoinTTAPIWaterHeaterEntity(coord, "entry1", "uuid1")
    ent.async_write_ha_state = MagicMock()
    return ent


OUTDOOR = "/system/sensors/temperatures/outdoor_t1"


class TestSolarAvailability:
    def test_unavailable_solar_resources_are_not_usable(self):
        data = {
            "/solarCircuits/sc1": {
                "references": [
                    {"id": "/solarCircuits/sc1/collectorTemperature"},
                ],
            },
            "/solarCircuits/sc1/collectorTemperature": {
                "value": 0.0,
                "used": "false",
                "available": "false",
            },
            "/solarCircuits/sc1/dhwTankBottomTemperature": {
                "value": 0.0,
                "used": "false",
                "available": "false",
            },
            "/solarCircuits/sc1/pumpModulation": {
                "value": 0.0,
                "used": "false",
                "available": "false",
            },
            "/solarCircuits/sc1/totalSolarGain": {
                "value": 0.0,
                "used": "false",
                "available": "false",
            },
        }

        assert _solar_data_available(data) is False

    def test_zero_is_valid_when_solar_resource_is_available(self):
        data = {
            "/solarCircuits/sc1/collectorTemperature": {
                "value": 0.0,
                "available": "true",
            }
        }

        assert _solar_data_available(data) is True


# ── Sensor ──────────────────────────────────────────────────────────────────


class TestSensorRobustness:
    def test_present_path_reads_value(self):
        coord = _coord({OUTDOOR: {"value": 7.5}})
        ent = _sensor(coord, OUTDOOR)
        ent._handle_coordinator_update()
        assert ent.native_value == 7.5

    def test_absent_path_reports_none_not_stale(self):
        """Value was 7.5; a poll without the path must drop to None, not keep it."""
        coord = _coord({OUTDOOR: {"value": 7.5}})
        ent = _sensor(coord, OUTDOOR)
        ent._handle_coordinator_update()
        assert ent.native_value == 7.5
        coord.data = {}  # path disappeared this cycle
        ent._handle_coordinator_update()
        assert ent.native_value is None

    @pytest.mark.parametrize(
        "payload",
        [
            {OUTDOOR: "garbage"},          # not a dict
            {OUTDOOR: {"no_value_key": 1}},  # dict without "value"
            {OUTDOOR: None},                # None container
            {OUTDOOR: [1, 2, 3]},           # wrong type
        ],
    )
    def test_malformed_value_does_not_raise(self, payload):
        coord = _coord(payload)
        ent = _sensor(coord, OUTDOOR)
        ent._handle_coordinator_update()  # must not raise
        assert ent.native_value is None

    def test_available_fn_sensor_unavailable_when_path_absent(self):
        """The notifications sensor has available_fn -> entity goes unavailable."""
        ent = _sensor(_coord({}), "/notifications")
        assert ent.available is False
        ent_present = _sensor(_coord({"/notifications": {"value": []}}), "/notifications")
        assert ent_present.available is True


# ── Number (read + malformed + write) ──────────────────────────────────────────


class TestNumberRobustness:
    KEY = "/heatingCircuits/hc1/boostTemperature"

    def test_present_path_reads_float(self):
        ent = _number(_coord({self.KEY: {"value": 21.0}}), self.KEY)
        ent._handle_coordinator_update()
        assert ent.native_value == 21.0

    def test_malformed_value_does_not_raise(self):
        """A non-numeric value must not crash the coordinator callback."""
        ent = _number(_coord({self.KEY: {"value": "not-a-number"}}), self.KEY)
        ent._handle_coordinator_update()  # float("not-a-number") would raise
        assert ent.native_value is None

    @pytest.mark.asyncio
    async def test_set_native_value_writes_optimistically_and_refreshes(self):
        coord = _coord({self.KEY: {"value": 21.0, "used": "true", "available": "true", "writeable": 1}})
        ent = _number(coord, self.KEY)
        ent._handle_coordinator_update()

        await ent.async_set_native_value(23.5)

        coord.client.put.assert_awaited_once_with(self.KEY, 23.5)
        assert ent.native_value == 23.5  # optimistic
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.parametrize(
        "resource",
        [
            {"value": 21.0, "used": "false", "available": "true", "writeable": 1},
            {"value": 21.0, "used": "true", "available": "false", "writeable": 1},
            {"value": 21.0, "used": "true", "available": "true", "writeable": 0},
        ],
    )
    def test_non_operable_number_is_unavailable(self, resource):
        assert _number(_coord({self.KEY: resource}), self.KEY).available is False

    @pytest.mark.asyncio
    async def test_non_writable_number_does_not_send_put(self):
        coord = _coord({
            self.KEY: {"value": 21.0, "used": "true", "available": "true", "writeable": 0}
        })

        with pytest.raises(HomeAssistantError, match="is unavailable"):
            await _number(coord, self.KEY).async_set_native_value(23.5)

        coord.client.put.assert_not_awaited()


class TestCoordinatorEntityInitialSync:
    @pytest.mark.asyncio
    async def test_entity_reads_loaded_data_when_added_after_first_refresh(self):
        key = "/zones/zn1/temperatureActual"
        coord = _coord({key: {"value": 21.5}})
        desc = next(d for d in _pointtapi_sensor_descriptions(coord.data) if d.key == key)
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        with patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()):
            await ent.async_added_to_hass()

        assert ent.native_value == 21.5
        ent.async_write_ha_state.assert_called_once()

# ── Select (write + malformed) ─────────────────────────────────────────────────


class TestSelectRobustness:
    KEY = "/zones/zn1/userMode"

    def test_malformed_value_does_not_raise(self):
        ent = _select(_coord({self.KEY: "garbage"}), self.KEY)
        ent._handle_coordinator_update()
        assert ent.current_option is None

    @pytest.mark.asyncio
    async def test_select_option_writes_optimistically_and_refreshes(self):
        coord = _coord({self.KEY: {"value": "clock"}})
        ent = _select(coord, self.KEY)
        ent._handle_coordinator_update()

        await ent.async_select_option("manual")

        coord.client.put.assert_awaited_once_with(self.KEY, "manual")
        assert ent.current_option == "manual"  # optimistic
        coord.async_request_refresh.assert_awaited_once()
        coord.async_refresh_boost_state.assert_awaited_once()


# ── Climate (read + absent + malformed + write) ────────────────────────────────


class TestClimateRobustness:
    def test_present_path_reads_temps(self):
        coord = _coord({
            "/zones/zn1/temperatureActual": {"value": 20.5},
            "/zones/zn1/temperatureHeatingSetpoint": {"value": 22.0},
            "/zones/zn1/userMode": {"value": "clock"},
            "/zones/zn1/status": {"value": "idle"},
        })
        ent = _climate(coord)
        ent._handle_coordinator_update()
        assert ent.current_temperature == 20.5
        assert ent.target_temperature == 22.0
        assert ent.hvac_mode == HVACMode.AUTO
        assert ent.hvac_action == HVACAction.IDLE

    def test_absent_path_reports_none_not_stale(self):
        coord = _coord({
            "/zones/zn1/temperatureActual": {"value": 20.5},
            "/zones/zn1/temperatureHeatingSetpoint": {"value": 22.0},
        })
        ent = _climate(coord)
        ent._handle_coordinator_update()
        assert ent.current_temperature == 20.5
        coord.data = {}  # zone paths gone
        ent._handle_coordinator_update()
        assert ent.current_temperature is None
        assert ent.target_temperature is None

    def test_malformed_manual_temp_does_not_raise(self):
        """OFF-detection does float(manual_temp); a bad value must not crash."""
        coord = _coord({
            "/zones/zn1/userMode": {"value": "manual"},
            "/zones/zn1/manualTemperatureHeating": {"value": "bad"},
        })
        ent = _climate(coord)
        ent._handle_coordinator_update()  # float("bad") would raise
        assert ent.hvac_mode == HVACMode.HEAT

    def test_target_falls_back_to_manual_temperature(self):
        coord = _coord({
            "/zones/zn1/temperatureActual": {"value": 20.5},
            "/zones/zn1/userMode": {"value": "manual"},
            "/zones/zn1/manualTemperatureHeating": {"value": 19.5},
        })
        ent = _climate(coord)
        ent._handle_coordinator_update()
        assert ent.target_temperature == 19.5

    def test_hvac_action_heat_request_maps_to_heating(self):
        coord = _coord({
            "/zones/zn1/userMode": {"value": "clock"},
            "/zones/zn1/status": {"value": "heat request"},
        })
        ent = _climate(coord)
        ent._handle_coordinator_update()
        assert ent.hvac_action == HVACAction.HEATING

    def test_hvac_action_unknown_status_is_unknown(self):
        # Heating-only appliance: an unrecognised status must not be reported as
        # COOLING, which HA renders as "Cooling" in the UI.
        coord = _coord({
            "/zones/zn1/userMode": {"value": "clock"},
            "/zones/zn1/status": {"value": "circulation"},
        })
        ent = _climate(coord)
        ent._handle_coordinator_update()
        assert ent.hvac_action is None

    def test_hvac_action_off_when_mode_is_off(self):
        coord = _coord({
            "/zones/zn1/userMode": {"value": "manual"},
            "/zones/zn1/manualTemperatureHeating": {"value": 5.0},
            "/zones/zn1/status": {"value": "heat request"},
        })
        ent = _climate(coord)
        ent._handle_coordinator_update()
        assert ent.hvac_mode == HVACMode.OFF
        assert ent.hvac_action == HVACAction.OFF

    def test_boost_preset_reflects_selected_and_allowed_zone(self):
        coord = _coord({
            "/heatingCircuits/hc1/boostMode": {"value": "on"},
            "/heatingCircuits/hc1/boostZones": {
                "value": [{"zones": [1], "allowedZones": [1, 2]}]
            },
            "/heatingCircuits/hc1/boostShortcut": {
                "used": "true", "available": "true", "writeable": 1
            },
        })

        assert _climate(coord).preset_modes == ["none", "boost"]
        assert _climate(coord).preset_mode == "boost"
        assert _climate(coord).supported_features & ClimateEntityFeature.PRESET_MODE

    @pytest.mark.asyncio
    async def test_set_boost_preset_delegates_to_coordinator(self):
        coord = _coord({
            "/heatingCircuits/hc1/boostZones": {
                "value": [{"zones": [], "allowedZones": [1]}]
            },
            "/heatingCircuits/hc1/boostShortcut": {
                "used": "true", "available": "true", "writeable": 1
            },
        })
        ent = _climate(coord)
        await ent.async_set_preset_mode("boost")
        coord.async_set_zone_boost.assert_awaited_once_with(1, True)

    @pytest.mark.asyncio
    async def test_boost_preset_is_immediately_optimistic(self):
        coord = _coord({
            "/heatingCircuits/hc1/boostZones": {
                "value": [{"zones": [], "allowedZones": [1]}]
            },
            "/heatingCircuits/hc1/boostShortcut": {
                "used": "true", "available": "true", "writeable": 1
            },
        })
        pending: dict[int, bool] = {}
        coord.set_pending_boost_intent.side_effect = pending.__setitem__
        coord.pending_boost_intent.side_effect = pending.get
        ent = _climate(coord)

        await ent.async_set_preset_mode("boost")

        assert ent.preset_mode == "boost"
        assert pending == {1: True}

    def test_failed_boost_poll_does_not_clear_pending_intent(self):
        coord = _coord({})
        pending = {1: True}
        coord.pending_boost_intent.side_effect = pending.get
        coord.reconcile_pending_boost_intent.side_effect = (
            lambda zone_id, observed: pending.pop(zone_id, None)
            if observed is not None
            else None
        )
        ent = _climate(coord)

        ent._handle_coordinator_update()

        assert pending == {1: True}
        assert ent.preset_mode == "boost"

    def test_successful_boost_poll_reconciles_pending_intent(self):
        coord = _coord({
            "/heatingCircuits/hc1/boostMode": {"value": "on"},
            "/heatingCircuits/hc1/boostZones": {
                "value": [{"zones": [1], "allowedZones": [1]}]
            },
        })
        pending = {1: True}
        coord.pending_boost_intent.side_effect = pending.get
        coord.reconcile_pending_boost_intent.side_effect = (
            lambda zone_id, observed: pending.pop(zone_id, None)
        )
        ent = _climate(coord)

        ent._handle_coordinator_update()

        assert pending == {}
        assert ent.preset_mode == "boost"

    @pytest.mark.asyncio
    async def test_set_boost_preset_rejects_when_not_allowed(self):
        ent = _climate(_coord({}))

        with pytest.raises(HomeAssistantError, match="Boost is unavailable for this zone"):
            await ent.async_set_preset_mode("boost")

    @pytest.mark.asyncio
    async def test_set_boost_preset_rejects_unavailable_zone(self):
        coord = _coord({
            "/heatingCircuits/hc1/boostZones": {
                "value": [{"zones": [], "allowedZones": [2]}]
            },
            "/heatingCircuits/hc1/boostShortcut": {
                "used": "true", "available": "true", "writeable": 1
            },
        })
        ent = _climate(coord)
        BoschPoinTTAPIBoostSwitchEntity(coord, "entry1", "uuid1", 1)

        with pytest.raises(HomeAssistantError, match="Boost is unavailable"):
            await ent.async_set_preset_mode("boost")

    @pytest.mark.asyncio
    async def test_set_temperature_switches_manual_then_writes_and_refreshes(self):
        coord = _coord({
            "/zones/zn1/temperatureActual": {"value": 20.0},
            "/zones/zn1/temperatureHeatingSetpoint": {"value": 21.0},
            "/zones/zn1/userMode": {"value": "clock"},
        })
        ent = _climate(coord)

        await ent.async_set_temperature(temperature=21.5)

        calls = [(c.args[0], c.args[1]) for c in coord.client.put.await_args_list]
        assert calls == [
            ("/zones/zn1/userMode", "manual"),
            ("/zones/zn1/manualTemperatureHeating", 21.5),
        ]
        assert ent.target_temperature == 21.5  # optimistic
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_auto_sets_clock_mode(self):
        coord = _coord({"/zones/zn1/userMode": {"value": "manual"}})
        ent = _climate(coord)

        await ent.async_set_hvac_mode(HVACMode.AUTO)

        coord.client.put.assert_awaited_once_with("/zones/zn1/userMode", "clock")
        assert ent.hvac_mode == HVACMode.AUTO
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_heat_sets_manual_mode(self):
        coord = _coord({"/zones/zn1/userMode": {"value": "clock"}})
        ent = _climate(coord)

        await ent.async_set_hvac_mode(HVACMode.HEAT)

        coord.client.put.assert_awaited_once_with("/zones/zn1/userMode", "manual")
        assert ent.hvac_mode == HVACMode.HEAT
        coord.async_request_refresh.assert_awaited_once()


# ── Water heater (read/mapping + absent + write + op-mode mapping) ──────────────


class TestWaterHeaterRobustness:
    def test_present_path_reads_and_maps_operation(self):
        coord = _coord({
            "/dhwCircuits/dhw1/actualTemp": {"value": 48.0},
            "/dhwCircuits/dhw1/temperatureLevels/high": {"value": 60.0},
            "/dhwCircuits/dhw1/operationMode": {"value": "high"},
        })
        ent = _water_heater(coord)  # _sync_from_data runs in __init__
        assert ent.current_temperature == 48.0
        assert ent.target_temperature == 60.0
        assert ent.current_operation == "On"  # "high" -> "On"

    def test_absent_path_reports_none_not_stale(self):
        ent = _water_heater(_coord({}))
        assert ent.current_temperature is None
        assert ent.target_temperature is None
        assert ent.current_operation is None

    def test_malformed_value_does_not_raise(self):
        ent = _water_heater(_coord({"/dhwCircuits/dhw1/actualTemp": "garbage"}))
        assert ent.current_temperature is None

    @pytest.mark.asyncio
    async def test_set_temperature_writes_optimistically_and_refreshes(self):
        coord = _coord({"/dhwCircuits/dhw1/temperatureLevels/high": {"value": 55.0}})
        ent = _water_heater(coord)

        await ent.async_set_temperature(temperature=58.0)

        coord.client.put.assert_awaited_once_with(
            "/dhwCircuits/dhw1/temperatureLevels/high", 58.0
        )
        assert ent.target_temperature == 58.0  # optimistic
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_operation_mode_maps_label_to_api_and_refreshes(self):
        """'On' label must be written to the API as 'high'; local state keeps the label."""
        coord = _coord({"/dhwCircuits/dhw1/operationMode": {"value": "Off"}})
        ent = _water_heater(coord)

        await ent.async_set_operation_mode("On")

        coord.client.put.assert_awaited_once_with(
            "/dhwCircuits/dhw1/operationMode", "high"
        )
        assert ent.current_operation == "On"  # optimistic, label form
        coord.async_request_refresh.assert_awaited_once()


class TestDeviceReportedAvailability:
    """A path can be present and writeable yet rejected by the appliance.

    Real CT200 payload (probe 2026-06-05): /dhwCircuits/dhw1/extraDhw returns
    writeable:1 but available:"false" — HA used to render an operable switch
    the boiler would refuse. Presence alone is not operability.
    """

    KEY = "/dhwCircuits/dhw1/extraDhw"

    def _switch(self, coord):
        desc = next(d for d in POINTTAPI_SWITCH_DESCRIPTIONS if d.key == self.KEY)
        ent = BoschPoinTTAPIGenericSwitchEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()
        return ent

    def test_helper_gates_on_available_flag_only(self):
        assert _path_available({"/p": {"value": "off"}}, "/p") is True
        assert _path_available({"/p": {"available": "true"}}, "/p") is True
        assert _path_available({"/p": {"available": "false"}}, "/p") is False
        # `used` is false on paths that still accept writes -> must not gate
        assert _path_available({"/p": {"used": "false"}}, "/p") is True
        # absent path / non-dict payload
        assert _path_available({}, "/p") is False
        assert _path_available({"/p": "scalar"}, "/p") is False

    def test_switch_unavailable_when_appliance_says_so(self):
        """The exact extraDhw payload that silently failed in the field."""
        coord = _coord(
            {self.KEY: {"writeable": 1, "used": "false", "available": "false", "value": "off"}}
        )
        assert self._switch(coord).available is False

    def test_switch_available_when_appliance_permits(self):
        coord = _coord(
            {self.KEY: {"writeable": 1, "used": "true", "available": "true", "value": "off"}}
        )
        assert self._switch(coord).available is True


class TestWriteFailuresSurface:
    """A rejected PUT must reach the user, not vanish into a log warning.

    Previously every write swallowed its exception, so HA reported the service
    call as successful and the entity just bounced back on the next refresh.
    """

    @pytest.mark.asyncio
    async def test_switch_turn_on_raises_on_put_failure(self):
        key = "/dhwCircuits/dhw1/extraDhw"
        coord = _coord({key: {"value": "off"}})
        coord.client.put = AsyncMock(side_effect=RuntimeError("PUT failed: 400"))
        desc = next(d for d in POINTTAPI_SWITCH_DESCRIPTIONS if d.key == key)
        ent = BoschPoinTTAPIGenericSwitchEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        with pytest.raises(HomeAssistantError, match="400"):
            await ent.async_turn_on()
        coord.async_request_refresh.assert_awaited_once()  # state still re-synced

    @pytest.mark.asyncio
    async def test_water_heater_set_operation_mode_raises_on_put_failure(self):
        coord = _coord({"/dhwCircuits/dhw1/operationMode": {"value": "Off"}})
        coord.client.put = AsyncMock(side_effect=RuntimeError("PUT failed: 400"))
        ent = _water_heater(coord)

        with pytest.raises(HomeAssistantError, match="400"):
            await ent.async_set_operation_mode("On")
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auth_failure_still_propagates_for_reauth(self):
        """ConfigEntryAuthFailed must pass through untouched to trigger reauth."""
        coord = _coord({"/dhwCircuits/dhw1/operationMode": {"value": "Off"}})
        coord.client.put = AsyncMock(side_effect=ConfigEntryAuthFailed("401"))
        ent = _water_heater(coord)

        with pytest.raises(ConfigEntryAuthFailed):
            await ent.async_set_operation_mode("On")


class TestClimateOffToHeatRestoresSetpoint:
    """OFF is stored as manual + min_temp, so leaving OFF has to restore the
    setpoint too. Writing only userMode leaves the zone at min_temp, and the
    next poll re-detects OFF and flips the UI back within the poll interval.
    """

    @pytest.mark.asyncio
    async def test_off_then_heat_restores_previous_setpoint(self):
        coord = _coord({
            "/zones/zn1/userMode": {"value": "clock"},
            "/zones/zn1/temperatureHeatingSetpoint": {"value": 21.0},
        })
        ent = _climate(coord)
        ent._handle_coordinator_update()

        await ent.async_set_hvac_mode(HVACMode.OFF)
        await ent.async_set_hvac_mode(HVACMode.HEAT)

        writes = [c.args for c in coord.client.put.call_args_list]
        assert ("/zones/zn1/manualTemperatureHeating", 21.0) in writes
        assert ent.hvac_mode == HVACMode.HEAT

    @pytest.mark.asyncio
    async def test_off_then_heat_without_known_setpoint_clears_min_temp(self):
        # No setpoint was ever observed, so we cannot restore the real one —
        # but we must still leave min_temp, or the zone reads as OFF again.
        coord = _coord({"/zones/zn1/userMode": {"value": "manual"}})
        ent = _climate(coord)
        ent._hvac_mode = HVACMode.OFF

        await ent.async_set_hvac_mode(HVACMode.HEAT)

        writes = dict(c.args for c in coord.client.put.call_args_list)
        assert writes["/zones/zn1/manualTemperatureHeating"] > ent.min_temp

    @pytest.mark.asyncio
    async def test_mode_change_while_already_on_leaves_setpoint_alone(self):
        coord = _coord({
            "/zones/zn1/userMode": {"value": "manual"},
            "/zones/zn1/temperatureHeatingSetpoint": {"value": 21.0},
        })
        ent = _climate(coord)
        ent._handle_coordinator_update()

        await ent.async_set_hvac_mode(HVACMode.AUTO)

        written = [c.args[0] for c in coord.client.put.call_args_list]
        assert "/zones/zn1/manualTemperatureHeating" not in written


class TestDhwBurnerDerivation:
    """The protocol has no burner-for-DHW signal, so it is derived: something
    is firing AND what it is firing for is dhw. /dhwCircuits/dhw1/state is an
    enabled flag and deliberately plays no part (#33).
    """

    @staticmethod
    def _data(modulation, flame, tank="on"):
        return {
            "/heatSources/actualModulation": {"value": modulation},
            "/heatSources/flameIndication": {"value": flame},
            "/dhwCircuits/dhw1/state": {"value": tank},
        }

    def test_firing_for_dhw_is_on(self):
        from custom_components.bosch.pointtapi_entities import _dhw_burner_state
        assert _dhw_burner_state(self._data(60.0, "dhw")) is True

    def test_firing_for_central_heating_is_off(self):
        from custom_components.bosch.pointtapi_entities import _dhw_burner_state
        assert _dhw_burner_state(self._data(60.0, "ch")) is False

    def test_idle_burner_is_off_even_with_the_tank_flag_on(self):
        # The exact case that made dhw_heating misleading: DHW permitted,
        # nothing burning.
        from custom_components.bosch.pointtapi_entities import _dhw_burner_state
        assert _dhw_burner_state(self._data(0.0, "off", tank="on")) is False

    def test_unknown_modulation_is_unknown_not_false(self):
        from custom_components.bosch.pointtapi_entities import _dhw_burner_state
        assert _dhw_burner_state({"/heatSources/flameIndication": {"value": "dhw"}}) is None

    def test_unavailable_without_heat_sources(self):
        from custom_components.bosch.pointtapi_entities import _dhw_burner_available
        assert _dhw_burner_available(self._data(60.0, "dhw")) is True
        assert _dhw_burner_available({"/dhwCircuits/dhw1/state": {"value": "on"}}) is False
