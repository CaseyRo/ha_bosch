"""Additional behavior coverage for the remaining integration classes."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.components.climate import HVACMode

integration_module = import_module("custom_components.bosch.__init__")
from custom_components.bosch.pointtapi_coordinator import PoinTTAPIDataUpdateCoordinator
from custom_components.bosch.pointtapi_coordinator import (
    _get_discovery_path,
    _discover_roots,
    _fetch_reference_tree,
)
from custom_components.bosch.pointtapi_entities import (
    BoschPoinTTAPIBinarySensorEntity,
    BoschPoinTTAPINumberEntity,
    BoschPoinTTAPIUpdateEntity,
    BoschPoinTTAPIClimateEntity,
    BoschPoinTTAPIWaterHeaterEntity,
    BoschPoinTTAPIGenericSwitchEntity,
    BoschPoinTTAPISelectEntity,
    POINTTAPI_BINARY_SENSOR_DESCRIPTIONS,
    POINTTAPI_NUMBER_DESCRIPTIONS,
    POINTTAPI_UPDATE_DESCRIPTIONS,
    POINTTAPI_SWITCH_DESCRIPTIONS,
    POINTTAPI_SELECT_DESCRIPTIONS,
    _appliance_status_attributes,
    _appliance_status_state,
    _burner_flame_state,
    _dhw_burner_available,
    _dhw_burner_state,
    _gateway_latest_version,
    _parse_update_timestamp,
    _resolve_on_off,
    _thermostat_valve_child_lock_path,
    _thermostat_valve_warning_state,
    _pointtapi_number_descriptions,
    _number_description_with_api_constraints,
    _thermostat_valve_device_path_from_data,
    _thermostat_valve_device_info_for_path,
    _zone_id_from_path,
    _heating_installation_circuit_id,
    _zone_ids_with_reference,
    pointtapi_zone_ids,
    _zone_room_suffix,
    _thermostat_valve_name,
    _thermostat_valve_id_from_path,
    _thermostat_valve_battery,
    _thermostat_valve_zone_name,
    _thermostat_valve_protocol_name,
    _coerce_int_like,
    _gas_ch_today,
    _gas_hw_today,
    _gas_total_today,
    _gas_ch_hourly,
    _gas_hw_hourly,
    _gas_total_hourly,
    _current_hour_entry,
    _float_value,
    ROUTE_DIRECT,
    ROUTE_SHORTCUT,
)
from custom_components.bosch.sensor.energy import EnergySensor, EnergySensors
from custom_components.bosch.sensor.recording import RecordingSensor
sensor_module = import_module("custom_components.bosch.sensor")


def _coordinator(data=None):
    coordinator = MagicMock()
    coordinator.data = data or {}
    coordinator.client = MagicMock()
    coordinator.client.put = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh_boost_state = AsyncMock()
    coordinator.language = None
    return coordinator


def _energy():
    obj = SimpleNamespace(
        parent_id=None, id="energy", name="Energy", entity_category=None,
        unit_of_measurement="kWh", device_class="energy", state_class="total",
        get_property=MagicMock(return_value={"value": {"CH": 2}}),
        fetch_range=AsyncMock(return_value={}), fetch_all=AsyncMock(return_value={}),
    )
    sensor = EnergySensor(
        EnergySensors[1], "uuid", hass=MagicMock(), bosch_object=obj,
        gateway=MagicMock(), attr_uri="energy", new_stats_api=True,
    )
    sensor._attr_entity_id = "sensor.energy"
    sensor._short_id = "energy"
    sensor.async_schedule_update_ha_state = MagicMock()
    return sensor


def test_pointtapi_status_and_boolean_helpers_cover_unknown_inputs():
    assert _resolve_on_off(True) is True
    assert _resolve_on_off(0) is False
    assert _resolve_on_off("yes") is True
    assert _resolve_on_off("unknown") is None
    assert _burner_flame_state({"/heatSources/actualModulation": {"value": "bad"}}) is None
    assert _dhw_burner_state({"/heatSources/actualModulation": {"value": 10}}) is False
    assert _dhw_burner_available({}) is False

    data = {
        "/system/appliance/displayCode": {"value": "0H"},
        "/system/appliance/causeCode": {"value": "203"},
        "/system/appliance/blockingError": {"value": "false"},
    }
    assert _appliance_status_state(data) is not None
    assert _appliance_status_attributes(data)["cause_code"] == 203
    assert _appliance_status_state({"/system/appliance/causeCode": {"value": 250}}) == "internal_error_service_required"
    assert _appliance_status_state({}) is None


def test_pointtapi_update_and_timestamp_helpers():
    data = {
        "/gateway/versionFirmware": {"value": "1.0"},
        "/gateway/update/state": {"value": "available"},
    }
    assert _gateway_latest_version(data) == "1.0 (update available)"
    assert _gateway_latest_version({}) is None
    assert _parse_update_timestamp("2026-05-11T01:02:00+02:00 Mo") is not None
    assert _parse_update_timestamp("bad") is None
    assert _float_value(" 2.5 ") == 2.5
    assert _float_value(3) == 3.0
    assert _float_value(True) is None
    assert _float_value("bad") is None


def test_thermostat_valve_child_lock_parent_reference_and_warning():
    enabled = "/devices/device2/etrv/childLock/enabled"
    data = {
        "/devices/device2/etrv/childLock": {"references": [{"id": enabled}]},
        enabled: {"value": "false"},
    }
    assert _thermostat_valve_child_lock_path(data, 2) == enabled
    rows = {"/devices/list": {"value": [{"id": 2, "type": "thermostat_valve", "warning": "bad"}]}}
    assert _thermostat_valve_warning_state(rows, 2) is True
    assert _thermostat_valve_warning_state(rows, 3) is None


def test_pointtapi_zone_and_valve_routing_helpers():
    assert _zone_id_from_path("/zones/zn3/name") == "zn3"
    assert _zone_id_from_path("/heatingCircuits/hc2/status") == "zn2"
    assert _zone_id_from_path("/other") == "zn1"
    assert _heating_installation_circuit_id("/heatingCircuits/hc1/nightThreshold") == "hc1"
    assert _heating_installation_circuit_id("/heatingCircuits/hc1/unknown") is None
    data = {
        "/zones/zn1/temperatureHeatingSetpoint": {"value": 20},
        "/zones/zn2/temperatureHeatingSetpoint": {"value": 21},
        "/zones/zn1": {"references": [{"id": "/zones/zn1/status"}]},
    }
    assert pointtapi_zone_ids(data) == ["zn1", "zn2"]
    assert _zone_ids_with_reference(data, "status") == ["zn1"]
    assert _zone_room_suffix({**data, "/zones/zn1/name": {"value": "TGl2aW5n"}}, "zn1") == " Living"
    assert _zone_room_suffix({}, "zn1") is None
    assert _thermostat_valve_name({"id": 2, "name": ""}) == "#2"
    assert _thermostat_valve_id_from_path("/devices/device12/etrv/offset") == 12
    assert _thermostat_valve_id_from_path("/unknown") is None
    assert _coerce_int_like("2.5") == 2
    assert _coerce_int_like(True) is None


def test_pointtapi_valve_metadata_and_gas_helpers():
    data = {
        "/devices/list": {"value": [{"id": 2, "type": "thermostat_valve", "battery": "ok", "zone": 1, "protocol": "homematicip"}]},
        "/zones/zn1/name": {"value": "TGl2aW5n"},
        "/energy/historyHourly": {"value": [{"entries": [{"d": "09-09-2026", "h": 1, "gCh": 1.5, "gHw": 0.5}]}]},
    }
    assert _thermostat_valve_battery(data, 2) == "OK"
    assert _thermostat_valve_zone_name(data, 2) == "Living"
    assert _thermostat_valve_protocol_name(data, 2) == "Homematic-IP"
    assert _thermostat_valve_battery(data, 3) is None
    with patch("custom_components.bosch.pointtapi_entities._today_dm", return_value="09-09"):
        assert _gas_ch_today(data) == 1.5
        assert _gas_hw_today(data) == 0.5
        assert _gas_total_today(data) == 2.0
    with patch("custom_components.bosch.pointtapi_entities.dt_util.now", return_value=datetime(2026, 9, 9, 1, tzinfo=timezone.utc)):
        assert _current_hour_entry(data)["h"] == 1
        assert _gas_ch_hourly(data) == 1.5
        assert _gas_hw_hourly(data) == 0.5
        assert _gas_total_hourly(data) == 2.0


def test_pointtapi_number_constraints_and_valve_layouts():
    description = POINTTAPI_NUMBER_DESCRIPTIONS[0]
    constrained = _number_description_with_api_constraints(
        {description.key: {"minValue": 10, "maxValue": 2, "stepSize": 0}},
        description,
    )
    assert constrained.native_min_value == description.native_min_value
    assert constrained.native_step == description.native_step
    data = {
        "/devices/device2/etrv/offset": {"value": 1, "minValue": -2, "maxValue": 2, "stepSize": 0.5},
        "/devices/device3/thermostat/offset": {"value": 1},
    }
    assert _thermostat_valve_device_path_from_data(data, 2, "etrv/offset").endswith("etrv/offset")
    assert _thermostat_valve_device_path_from_data(data, 3, "thermostat/offset").endswith("thermostat/offset")
    assert len(_pointtapi_number_descriptions(data)) >= len(POINTTAPI_NUMBER_DESCRIPTIONS)
    info = _thermostat_valve_device_info_for_path("uuid", data, "/devices/device2/etrv/offset")
    assert info["identifiers"]


@pytest.mark.asyncio
async def test_pointtapi_number_entity_write_error_and_auth_paths():
    path = "/dhwCircuits/dhw1/extraDhwDuration"
    data = {path: {"value": 20, "available": "true", "used": 1, "writeable": 1}}
    coordinator = _coordinator(data)
    entity = BoschPoinTTAPINumberEntity(coordinator, "entry", "uuid", next(d for d in POINTTAPI_NUMBER_DESCRIPTIONS if d.key == path))
    entity.async_write_ha_state = MagicMock()
    coordinator.client.put.side_effect = RuntimeError("failed")
    with pytest.raises(HomeAssistantError):
        await entity.async_set_native_value(30)
    coordinator.client.put.side_effect = ConfigEntryAuthFailed("401")
    with pytest.raises(ConfigEntryAuthFailed):
        await entity.async_set_native_value(30)


@pytest.mark.asyncio
async def test_pointtapi_binary_and_update_entities_refresh_state():
    binary_desc = next(d for d in POINTTAPI_BINARY_SENSOR_DESCRIPTIONS if d.key == "/heatSources/flameIndication")
    coordinator = _coordinator({"/heatSources/actualModulation": {"value": 5}})
    binary = BoschPoinTTAPIBinarySensorEntity(coordinator, "entry", "uuid", binary_desc)
    binary.async_write_ha_state = MagicMock()
    binary._handle_coordinator_update()
    assert binary.is_on is True

    update = BoschPoinTTAPIUpdateEntity(coordinator, "entry", "uuid", POINTTAPI_UPDATE_DESCRIPTIONS[0])
    assert update.installed_version is None
    assert update.latest_version is None


@pytest.mark.asyncio
async def test_pointtapi_generic_switch_and_select_error_paths():
    switch_desc = POINTTAPI_SWITCH_DESCRIPTIONS[1]
    path = switch_desc.key
    coordinator = _coordinator({path: {"value": "false", "available": "true"}})
    switch = BoschPoinTTAPIGenericSwitchEntity(coordinator, "entry", "uuid", switch_desc)
    switch.async_write_ha_state = MagicMock()
    switch._handle_coordinator_update()
    assert switch.is_on is False
    coordinator.client.put.side_effect = RuntimeError("failed")
    with pytest.raises(HomeAssistantError):
        await switch.async_turn_on()
    coordinator.client.put.side_effect = ConfigEntryAuthFailed("401")
    with pytest.raises(ConfigEntryAuthFailed):
        await switch.async_turn_off()

    select_desc = POINTTAPI_SELECT_DESCRIPTIONS[0]
    select_path = select_desc.key
    coordinator = _coordinator({select_path: {"value": "high", "available": "true"}})
    select = BoschPoinTTAPISelectEntity(coordinator, "entry", "uuid", select_desc)
    select.async_write_ha_state = MagicMock()
    select._handle_coordinator_update()
    assert select.current_option == "high"
    with pytest.raises(HomeAssistantError):
        await select.async_select_option("invalid")
    coordinator.client.put.side_effect = RuntimeError("failed")
    with pytest.raises(HomeAssistantError):
        await select.async_select_option("low")


@pytest.mark.asyncio
async def test_pointtapi_climate_entity_modes_and_errors():
    data = {
        "/zones/zn1/temperatureActual": {"value": 20},
        "/zones/zn1/temperatureHeatingSetpoint": {"value": 21},
        "/zones/zn1/userMode": {"value": "clock"},
        "/zones/zn1/status": {"value": "heat request"},
    }
    coordinator = _coordinator(data)
    coordinator.reconcile_pending_boost_intent = MagicMock()
    coordinator.pending_boost_intent.return_value = None
    climate = BoschPoinTTAPIClimateEntity(coordinator, "entry", "uuid", "zn1")
    climate.async_write_ha_state = MagicMock()
    climate._handle_coordinator_update()
    assert climate.hvac_mode == HVACMode.AUTO
    assert climate.current_temperature == 20
    await climate.async_set_temperature(temperature=22)
    coordinator.client.put.side_effect = RuntimeError("failed")
    with pytest.raises(HomeAssistantError):
        await climate.async_set_hvac_mode(HVACMode.HEAT)
    coordinator.client.put.side_effect = ConfigEntryAuthFailed("401")
    with pytest.raises(ConfigEntryAuthFailed):
        await climate.async_set_temperature(temperature=23)
    coordinator.client.put.side_effect = None
    await climate.async_set_hvac_mode(HVACMode.OFF)
    await climate.async_set_hvac_mode(HVACMode.AUTO)
    with pytest.raises(HomeAssistantError):
        await climate.async_set_preset_mode("invalid")
    climate._hvac_mode = HVACMode.OFF
    coordinator.async_set_zone_boost = AsyncMock()
    await climate.async_set_preset_mode("none")
    coordinator.async_set_zone_boost.assert_awaited_once_with(1, False)
    coordinator.client.put.side_effect = RuntimeError("off failed")
    with pytest.raises(HomeAssistantError):
        await climate.async_set_hvac_mode(HVACMode.OFF)
    coordinator.client.put.side_effect = ConfigEntryAuthFailed("401")
    with pytest.raises(ConfigEntryAuthFailed):
        await climate.async_set_hvac_mode(HVACMode.OFF)


@pytest.mark.asyncio
async def test_pointtapi_water_heater_entity_write_errors():
    data = {
        "/dhwCircuits/dhw1/actualTemp": {"value": 42},
        "/dhwCircuits/dhw1/temperatureLevels/high": {"value": 50},
        "/dhwCircuits/dhw1/operationMode": {"value": "auto"},
    }
    coordinator = _coordinator(data)
    heater = BoschPoinTTAPIWaterHeaterEntity(coordinator, "entry", "uuid")
    heater.async_write_ha_state = MagicMock()
    assert heater.current_temperature == 42
    coordinator.client.put.side_effect = RuntimeError("failed")
    with pytest.raises(HomeAssistantError):
        await heater.async_set_temperature(temperature=55)
    coordinator.client.put.side_effect = ConfigEntryAuthFailed("401")
    with pytest.raises(ConfigEntryAuthFailed):
        await heater.async_set_operation_mode("On")
    coordinator.client.put.side_effect = None
    await heater.async_set_temperature(temperature=55)
    await heater.async_set_operation_mode("On")


@pytest.mark.asyncio
async def test_pointtapi_generic_switch_and_select_success_paths():
    switch_desc = POINTTAPI_SWITCH_DESCRIPTIONS[1]
    path = switch_desc.key
    coordinator = _coordinator({path: {"value": "false", "available": "true"}})
    switch = BoschPoinTTAPIGenericSwitchEntity(coordinator, "entry", "uuid", switch_desc)
    switch.async_write_ha_state = MagicMock()
    await switch.async_turn_on()
    await switch.async_turn_off()
    assert coordinator.client.put.await_count == 2

    select_desc = POINTTAPI_SELECT_DESCRIPTIONS[0]
    coordinator = _coordinator({select_desc.key: {"value": "high", "available": "true"}})
    select = BoschPoinTTAPISelectEntity(coordinator, "entry", "uuid", select_desc)
    select.async_write_ha_state = MagicMock()
    await select.async_select_option("low")
    assert select.current_option == "low"


@pytest.mark.asyncio
async def test_energy_sensor_statistics_error_and_missing_values():
    sensor = _energy()
    sensor._bosch_object.get_property.return_value = {}
    await sensor.async_update()
    assert sensor.native_value is None

    sensor.get_last_stat = AsyncMock(return_value={})
    sensor._bosch_object.fetch_all = AsyncMock(return_value={})
    await sensor._insert_statistics()
    sensor.fetch_past_data = AsyncMock(return_value={})
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    with patch("custom_components.bosch.sensor.energy.dt_util.now", return_value=now):
        await sensor._upsert_past_statistics(now, now + timedelta(hours=1))

    sensor._attr_read_key = "CH"
    sensor.fetch_past_data = AsyncMock(return_value={})
    with patch("custom_components.bosch.sensor.energy.dt_util.now", return_value=now):
        await sensor._upsert_past_statistics(now - timedelta(days=2), now - timedelta(days=2) + timedelta(hours=1))

    sensor._bosch_object.get_property.return_value = {"value": {"OTHER": 1}}
    sensor._new_stats_api = False
    await sensor.async_update()


@pytest.mark.asyncio
async def test_recording_sensor_empty_and_old_database_paths():
    obj = SimpleNamespace(
        parent_id=None, id="recording", name="Recording", entity_category=None,
        unit_of_measurement="kWh", device_class="energy", state_class="total",
        state=[],
    )
    sensor = RecordingSensor(hass=MagicMock(), uuid="uuid", bosch_object=obj, gateway=MagicMock(), name="Recording", attr_uri="recording", new_stats_api=True)
    sensor._attr_entity_id = "sensor.recording"
    sensor._short_id = "recording"
    sensor.async_schedule_update_ha_state = MagicMock()
    sensor.get_last_stat = AsyncMock(return_value={})
    sensor.fetch_past_data = AsyncMock(side_effect=[{}, {}])
    await sensor._insert_statistics()
    sensor.fetch_past_data = AsyncMock(return_value={})
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
        await sensor._upsert_past_statistics(now, now + timedelta(hours=1))

    sensor.fetch_past_data = AsyncMock(return_value={})
    sensor.get_last_stat = AsyncMock(return_value={"recording:recordingexternal": [{"start": float(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()), "state": 1, "sum": 1}]})
    with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
        await sensor._insert_statistics()

    sensor.fetch_past_data = AsyncMock(return_value={
        "one": {"d": datetime(2026, 1, 2, tzinfo=timezone.utc), "value": 2.0},
    })
    sensor.get_stats_from_ha_db = AsyncMock(return_value={
        sensor.statistic_id: [{"start": datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp() + 7200, "state": 1.0, "sum": 2.0}]
    })
    sensor.add_external_stats = MagicMock()
    with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
        await sensor._upsert_past_statistics(
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
        )
    sensor.add_external_stats.assert_called()


@pytest.mark.asyncio
async def test_coordinator_boost_refresh_error_and_auth_paths():
    coordinator = PoinTTAPIDataUpdateCoordinator.__new__(PoinTTAPIDataUpdateCoordinator)
    coordinator._client = MagicMock()
    coordinator.data = {"/gateway": {"value": "ok"}}
    coordinator.async_set_updated_data = MagicMock()
    coordinator._BOOST_REFRESH_PATHS = tuple(coordinator._BOOST_REFRESH_PATHS)
    coordinator._client.bulk = AsyncMock(return_value={})
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await coordinator.async_refresh_boost_state()
    coordinator._client.bulk = AsyncMock(side_effect=RuntimeError("temporary"))
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await coordinator.async_refresh_boost_state()
    coordinator._client.bulk = AsyncMock(side_effect=ConfigEntryAuthFailed("401"))
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator.async_refresh_boost_state()


@pytest.mark.asyncio
async def test_coordinator_native_probe_direct_and_shortcut_routes():
    coordinator = PoinTTAPIDataUpdateCoordinator.__new__(PoinTTAPIDataUpdateCoordinator)
    coordinator._client = MagicMock()
    coordinator._client.put = AsyncMock()
    coordinator.data = {"/heatingCircuits/hc1/boostMode": {"value": "off"}}
    coordinator.boost_probe_result = None
    coordinator._confirm_native_active = AsyncMock(return_value=True)
    assert await coordinator._probe_native_boost(22, 2, [1]) == ROUTE_SHORTCUT

    coordinator.data = {"/heatingCircuits/hc1/boostMode": {"value": "off"}}
    coordinator._confirm_native_active = AsyncMock(side_effect=[False, True])
    coordinator._client.put.reset_mock()
    assert await coordinator._probe_native_boost(22, 2, [1]) == ROUTE_DIRECT


@pytest.mark.asyncio
async def test_coordinator_native_probe_fallback_and_shortcut_auth_recovery():
    coordinator = PoinTTAPIDataUpdateCoordinator.__new__(PoinTTAPIDataUpdateCoordinator)
    coordinator._client = MagicMock()
    coordinator._client.put = AsyncMock(side_effect=RuntimeError("shortcut"))
    coordinator.data = {}
    coordinator._confirm_native_active = AsyncMock(return_value=False)
    assert (await coordinator._probe_native_boost(22, 2, [1])) == "fallback"

    coordinator._client.put = AsyncMock(
        side_effect=[ConfigEntryAuthFailed("shortcut"), None, None]
    )
    coordinator.boost_probe_result = {"route": ROUTE_SHORTCUT}
    assert await coordinator._native_boost_off(ROUTE_SHORTCUT, [1]) is True


@pytest.mark.asyncio
async def test_coordinator_refresh_boost_state_keeps_only_resources():
    coordinator = PoinTTAPIDataUpdateCoordinator.__new__(PoinTTAPIDataUpdateCoordinator)
    coordinator._client = MagicMock()
    coordinator._client.get = AsyncMock(side_effect=[{"value": "on"}, "bad"])
    result = await coordinator._refresh_boost_state({"/gateway": {"value": "ok"}})
    assert result["/heatingCircuits/hc1/boostMode"]["value"] == "on"
    assert "/heatingCircuits/hc1/boostZones" not in result


def test_coordinator_constructor_initializes_runtime_state():
    coordinator = PoinTTAPIDataUpdateCoordinator(MagicMock(), MagicMock(), MagicMock())
    assert coordinator.client is not None
    assert coordinator._bulk_paths == []
    assert coordinator._pending_boost_intents == {}
    assert coordinator.discovery_timings == []


@pytest.mark.asyncio
async def test_coordinator_discovery_deadline_and_root_auth_fallback():
    client = AsyncMock()
    timings = []
    assert await _get_discovery_path(client, "/optional", deadline=0, timings=timings) is None
    client.get.side_effect = ConfigEntryAuthFailed("403")
    assert await _discover_roots(client, "/zones", "/zones/zn1") == ["/zones/zn1"]
    client.get.side_effect = TimeoutError()
    assert await _get_discovery_path(client, "/optional", timeout=0.01, timings=timings) is None


@pytest.mark.asyncio
async def test_coordinator_discovery_deadline_raises_for_gateway():
    """A silent None on /gateway would hide a failed refresh; it must raise instead."""
    client = AsyncMock()
    with pytest.raises(TimeoutError):
        await _get_discovery_path(client, "/gateway", deadline=0, timings=[])


@pytest.mark.asyncio
async def test_coordinator_reference_tree_skips_invalid_and_nested_failures():
    client = AsyncMock()
    client.get.side_effect = ["not a dict", ConfigEntryAuthFailed("403")]
    data = {}
    await _fetch_reference_tree(
        client,
        {"references": [{"id": "/gateway/DateTime"}, {"id": "/gateway/other"}]},
        data,
        set(),
        asyncio.Semaphore(2),
        deadline=asyncio.get_running_loop().time() + 10,
    )
    assert data == {}


@pytest.mark.asyncio
async def test_coordinator_reference_tree_stops_at_depth_limit():
    client = SimpleNamespace(
        get=AsyncMock(return_value={"references": [{"id": "/system/sensors/temperatures/outdoor_t1"}]})
    )
    data = {}
    await _fetch_reference_tree(
        client,
        {"references": [{"id": "/system/sensors/temperatures/outdoor_t1"}]},
        data,
        set(),
        asyncio.Semaphore(1),
        deadline=asyncio.get_running_loop().time() + 10,
    )
    assert "/system/sensors/temperatures/outdoor_t1" in data


def test_sensor_registry_cleanup_removes_entities_and_device():
    solar_device = SimpleNamespace(id="solar-device")
    registry = MagicMock()
    registry.entities.values.return_value = [
        SimpleNamespace(device_id="solar-device", entity_id="sensor.solar")
    ]
    device_registry = MagicMock()
    device_registry.async_get_device.return_value = solar_device
    with (
        patch.object(sensor_module.dr, "async_get", return_value=device_registry),
        patch.object(sensor_module.er, "async_get", return_value=registry),
    ):
        sensor_module._remove_solar_registry_entries(MagicMock(), "uuid")
    registry.async_remove.assert_called_once_with("sensor.solar")
    device_registry.async_remove_device.assert_called_once_with("solar-device")


@pytest.mark.asyncio
async def test_sensor_backfill_callback_handles_empty_data_and_failure():
    coordinator = SimpleNamespace(
        data={}, last_update_success=True, async_request_refresh=AsyncMock()
    )
    entry = SimpleNamespace(
        entry_id="entry-empty", data={"http_xmpp": "pointtapi", "uuid": "uuid"},
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    hass = MagicMock(data={})
    callback = None

    def schedule(*args):
        nonlocal callback
        callback = args[-1]

    with (
        patch.object(sensor_module, "_pointtapi_sensor_descriptions", return_value=[]),
        patch.object(sensor_module, "_solar_data_available", return_value=True),
        patch("homeassistant.helpers.event.async_call_later", side_effect=schedule),
    ):
        await sensor_module.async_setup_entry(hass, entry, MagicMock())
        await callback()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_coordinator_auth_and_timeout_mappings():
    coordinator = PoinTTAPIDataUpdateCoordinator.__new__(PoinTTAPIDataUpdateCoordinator)
    coordinator._fetch = AsyncMock(side_effect=ConfigEntryAuthFailed("401"))
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    coordinator._fetch = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(Exception, match="timed out"):
        await coordinator._async_update_data()
    coordinator._fetch = AsyncMock(side_effect=RuntimeError("broken"))
    with pytest.raises(Exception, match="update failed"):
        await coordinator._async_update_data()


def test_integration_notification_and_device_removal_edges():
    hass = MagicMock()
    integration_module.create_notification_firmware(hass, "bad firmware")
    device = SimpleNamespace(identifiers={("bosch", "uuid_trv_1")})
    entry = SimpleNamespace(data={"http_xmpp": "pointtapi", "uuid": "uuid"}, runtime_data=None)
    assert integration_module._pointtapi_valve_ids({}) == set()
    assert device.identifiers
