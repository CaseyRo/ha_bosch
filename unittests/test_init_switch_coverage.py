"""Additional behavioral coverage for integration setup and legacy switches."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from importlib import import_module

import pytest

from bosch_thermostat_client.const import HTTP, SENSOR, XMPP
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

integration = import_module("custom_components.bosch.__init__")
from custom_components.bosch.const import (
    BINARY_SENSOR,
    CLIMATE,
    CONF_PROTOCOL,
    POINTTAPI,
    SIGNAL_SENSOR_UPDATE_BOSCH,
    SWITCH,
    UUID,
)
from custom_components.bosch.switch import (
    BoschSwitch,
    CircuitSwitch,
    async_setup_entry as async_setup_switch_entry,
    async_setup_platform,
)
from custom_components.bosch.sensor.energy import EnergySensor, EnergySensors, EcusRecordingSensors
from custom_components.bosch.sensor.notifications import NotificationSensor
from custom_components.bosch.sensor.recording import RecordingSensor
from custom_components.bosch.sensor.bosch import BoschSensor
from custom_components.bosch.sensor.circuit import CircuitSensor
from custom_components.bosch.sensor import async_setup_entry as async_setup_sensor_entry
sensor_module = import_module("custom_components.bosch.sensor")
binary_module = import_module("custom_components.bosch.binary_sensor")
number_module = import_module("custom_components.bosch.number")
select_module = import_module("custom_components.bosch.select")
update_module = import_module("custom_components.bosch.update")
water_module = import_module("custom_components.bosch.water_heater")


def _entry(protocol=POINTTAPI):
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_PROTOCOL: protocol, UUID: "uuid-1", "address": "host", "device_type": "EASYCONTROL", "access_key": "key", "access_token": "token"},
        options={},
        runtime_data=None,
    )
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock(return_value=lambda: None)
    return entry


def _legacy_switch(name="Main", state=False):
    return SimpleNamespace(
        name=name,
        state=state,
        attr_id=f"{name.lower()}_state",
        parent_id=None,
        turn_on=AsyncMock(),
        turn_off=AsyncMock(),
        update=AsyncMock(),
    )


def _gateway_entry(protocol=XMPP):
    entry = _entry(protocol)
    entry.runtime_data = SimpleNamespace(
        gateway=None,
        coordinator=None,
        recording=[],
        recording_interval=None,
        interval=None,
        fw_interval=None,
    )
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda function: function())
    hass.bus.async_listen_once = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    return integration.BoschGatewayEntry(
        hass=hass,
        uuid="uuid-1",
        host="host",
        protocol=protocol,
        device_type="EASYCONTROL",
        access_key="key",
        access_token="token",
        entry=entry,
    )


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"/devices/list": {"value": [{"id": "3", "type": "thermostat_valve"}]}}, {3}),
        ({"/devices/device4/type": {"value": "thermostat_valve"}}, {4}),
        ({"/devices/device5/type": {"value": "thermostat"}}, set()),
        ({"/devices/list": {"value": [{"id": "bad", "type": "thermostat_valve"}, "bad"]}}, set()),
    ],
)
def test_pointtapi_valve_ids_handles_listing_and_device_paths(data, expected):
    assert integration._pointtapi_valve_ids(data) == expected


@pytest.mark.asyncio
async def test_remove_device_rejects_non_pointtapi_and_malformed_identifier():
    entry = SimpleNamespace(data={CONF_PROTOCOL: "xmpp"}, runtime_data=None)
    device = SimpleNamespace(identifiers={("bosch", "uuid")})
    assert await integration.async_remove_config_entry_device(MagicMock(), entry, device) is False

    entry.data = {CONF_PROTOCOL: POINTTAPI, UUID: "uuid"}
    device.identifiers = {("bosch", "uuid_trv_bad")}
    assert await integration.async_remove_config_entry_device(MagicMock(), entry, device) is False


@pytest.mark.asyncio
async def test_setup_entry_success_registers_services_and_runtime_data():
    hass = MagicMock()
    entry = _entry()
    gateway_entry = MagicMock()
    gateway_entry.async_init = AsyncMock(return_value=True)

    with (
        patch.object(integration, "BoschGatewayEntry", return_value=gateway_entry),
        patch.object(integration, "async_register_services") as register_services,
    ):
        assert await integration.async_setup_entry(hass, entry) is True

    assert entry.runtime_data.gateway_entry is gateway_entry
    register_services.assert_called_once_with(hass, entry)


@pytest.mark.asyncio
async def test_setup_entry_returns_false_when_gateway_init_fails():
    hass = MagicMock()
    entry = _entry()
    gateway_entry = MagicMock()
    gateway_entry.async_init = AsyncMock(return_value=False)

    with patch.object(integration, "BoschGatewayEntry", return_value=gateway_entry):
        assert await integration.async_setup_entry(hass, entry) is False


@pytest.mark.asyncio
async def test_unload_entry_cancels_intervals_and_removes_services():
    hass = MagicMock()
    entry = _entry("xmpp")
    gateway_entry = SimpleNamespace(async_reset=AsyncMock(return_value=True))
    callbacks = [MagicMock(), MagicMock(), MagicMock()]
    entry.runtime_data = SimpleNamespace(
        gateway_entry=gateway_entry,
        interval=callbacks[0],
        fw_interval=callbacks[1],
        recording_interval=callbacks[2],
    )

    with patch.object(integration, "async_remove_services") as remove_services:
        assert await integration.async_unload_entry(hass, entry) is True

    for callback in callbacks:
        callback.assert_called_once_with()
    assert entry.runtime_data.interval is None
    remove_services.assert_called_once_with(hass, entry)


@pytest.mark.asyncio
async def test_update_options_skips_same_snapshot_and_reloads_changes():
    hass = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    entry = SimpleNamespace(entry_id="entry-1", options={"x": 1}, runtime_data=SimpleNamespace(options_snapshot={"x": 1}))

    await integration.async_update_options(hass, entry)
    hass.config_entries.async_reload.assert_not_awaited()

    entry.options = {"x": 2}
    await integration.async_update_options(hass, entry)
    hass.config_entries.async_reload.assert_awaited_once_with("entry-1")
    assert entry.runtime_data.options_snapshot == {"x": 2}


@pytest.mark.asyncio
async def test_switch_setup_pointtapi_without_coordinator_adds_no_entities():
    entry = SimpleNamespace(data={CONF_PROTOCOL: POINTTAPI}, runtime_data=SimpleNamespace(coordinator=None))
    add_entities = MagicMock()

    assert await async_setup_switch_entry(MagicMock(), entry, add_entities) is True
    add_entities.assert_called_once_with([])


@pytest.mark.asyncio
async def test_switch_setup_legacy_builds_regular_and_circuit_entities():
    regular = _legacy_switch()
    circuit_switch = _legacy_switch("Circuit", True)
    circuit = SimpleNamespace(name="Heating", regular_switches=[circuit_switch])
    gateway = SimpleNamespace(
        regular_switches=[regular],
        get_circuits=MagicMock(side_effect=lambda kind: [circuit] if kind == "hc" else []),
    )
    entry = SimpleNamespace(
        data={CONF_PROTOCOL: "xmpp", UUID: "uuid-1"},
        runtime_data=SimpleNamespace(gateway=gateway),
    )
    entities = []

    with patch("custom_components.bosch.switch.async_dispatcher_send") as send:
        assert await async_setup_switch_entry(MagicMock(), entry, entities.extend) is True

    assert len(entities) == 2
    assert isinstance(entities[0], BoschSwitch)
    assert isinstance(entities[1], CircuitSwitch)
    assert entry.runtime_data.switch == entities
    send.assert_called_once()


@pytest.mark.asyncio
async def test_switch_entity_updates_and_toggles_state():
    bosch_object = _legacy_switch("Main", False)
    gateway = SimpleNamespace(device_model="CT200", device_type="EASYCONTROL", firmware="1")
    entity = BoschSwitch(
        hass=MagicMock(), uuid="uuid-1", bosch_object=bosch_object, gateway=gateway,
        name="Main", attr_uri="main", domain_name="Switches", is_enabled=True,
    )
    entity.schedule_update_ha_state = MagicMock()

    assert entity.is_on is False
    await entity.async_turn_on()
    assert entity.is_on is True
    await entity.async_turn_off()
    assert entity.is_on is False
    bosch_object.state = True
    await entity.async_update()
    assert entity.is_on is True
    assert entity.should_poll is False
    assert entity.device_name == "Bosch switches"


@pytest.mark.asyncio
async def test_circuit_switch_name_and_empty_platform_setup():
    bosch_object = _legacy_switch("Circuit")
    entity = CircuitSwitch(
        hass=MagicMock(), uuid="uuid-1", bosch_object=bosch_object,
        gateway=SimpleNamespace(device_model="CT200", device_type="EASYCONTROL", firmware="1"),
        name="Circuit", attr_uri="circuit", domain_name="Heating", circuit_type="hc", is_enabled=True,
    )
    assert entity.device_name == "Heating circuit Heating"
    assert await async_setup_platform(MagicMock(), {}, MagicMock()) is None


@pytest.mark.asyncio
async def test_gateway_init_xmpp_creates_gateway_and_forwards_platforms():
    gateway_entry = _gateway_entry(XMPP)
    gateway = SimpleNamespace(
        device_model="CT200", device_type="EASYCONTROL", device_name="Home",
        firmware="1.0", uuid="uuid-1", check_connection=AsyncMock(), close=AsyncMock(),
    )
    gateway_entry._data.gateway = gateway
    gateway_entry.async_init_bosch = AsyncMock(return_value=True)

    with (
        patch("bosch_thermostat_client.gateway_chooser", return_value=lambda **kwargs: gateway),
        patch.object(integration, "async_dispatcher_connect"),
        patch.object(integration.dr, "async_get", return_value=MagicMock()),
        patch.object(integration, "async_register_debug_service"),
    ):
        assert await gateway_entry.async_init() is True

    gateway_entry.hass.async_add_executor_job.assert_awaited_once()
    gateway_entry.hass.config_entries.async_forward_entry_setups.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_init_wraps_gateway_creation_errors():
    gateway_entry = _gateway_entry(HTTP)
    def broken_gateway(**kwargs):
        raise RuntimeError("SSL")

    with (
        patch("bosch_thermostat_client.gateway_chooser", return_value=broken_gateway),
        patch.object(integration, "async_get_clientsession", return_value=MagicMock()),
    ):
        with pytest.raises(ConfigEntryNotReady, match="Failed to initialize"):
            await gateway_entry.async_init()


@pytest.mark.asyncio
async def test_init_bosch_success_discovers_capabilities():
    gateway_entry = _gateway_entry(XMPP)
    gateway_entry.gateway = SimpleNamespace(
        uuid="uuid-1", bus_type="xmpp", device_name="Home", database={"db": True},
        check_connection=AsyncMock(),
        get_capabilities=AsyncMock(return_value=[integration.HC, integration.SWITCH]),
    )

    assert await gateway_entry.async_init_bosch() is True
    assert CLIMATE in gateway_entry.supported_platforms
    assert SWITCH in gateway_entry.supported_platforms
    assert gateway_entry._data.gateway is gateway_entry.gateway


@pytest.mark.asyncio
async def test_init_bosch_maps_connection_errors():
    gateway_entry = _gateway_entry(XMPP)
    gateway_entry.gateway = SimpleNamespace(check_connection=AsyncMock(side_effect=ConfigEntryAuthFailed("bad")))
    with pytest.raises(ConfigEntryAuthFailed):
        await gateway_entry.async_init_bosch()

    gateway_entry.gateway = SimpleNamespace(
        check_connection=AsyncMock(), uuid=None, bus_type="xmpp", database=None,
    )
    with pytest.raises(ConfigEntryNotReady, match="UUID"):
        await gateway_entry.async_init_bosch()


@pytest.mark.asyncio
async def test_component_update_updates_entities_and_handles_unsupported_type():
    gateway_entry = _gateway_entry(XMPP)
    entity = SimpleNamespace(
        enabled=True, entity_id="sensor.one", name="One", bosch_object=SimpleNamespace(update=AsyncMock()),
    )
    gateway_entry.supported_platforms = [SENSOR]
    gateway_entry._data.sensor = [entity]

    with patch.object(integration, "async_dispatcher_send") as send:
        assert await gateway_entry.component_update(SENSOR) is True
        assert await gateway_entry.component_update(BINARY_SENSOR) is False
    entity.bosch_object.update.assert_awaited_once()
    send.assert_called_once_with(gateway_entry.hass, SIGNAL_SENSOR_UPDATE_BOSCH)


@pytest.mark.asyncio
async def test_recording_update_schedules_next_run_and_dispatches():
    gateway_entry = _gateway_entry(XMPP)
    entity = SimpleNamespace(
        enabled=True, name="Hourly", signal=SIGNAL_SENSOR_UPDATE_BOSCH,
        bosch_object=SimpleNamespace(update=AsyncMock()),
    )
    gateway_entry._data.recording = [entity]
    recording_callback = MagicMock()
    gateway_entry._data.recording_interval = recording_callback

    with (
        patch.object(integration, "async_track_point_in_utc_time", return_value=MagicMock()),
        patch.object(integration, "async_dispatcher_send") as send,
    ):
        assert await gateway_entry.recording_sensors_update() is True

    recording_callback.assert_called_once_with()
    send.assert_called_once_with(gateway_entry.hass, SIGNAL_SENSOR_UPDATE_BOSCH)


@pytest.mark.asyncio
async def test_firmware_refresh_and_reset_delegate_to_gateway():
    gateway_entry = _gateway_entry(XMPP)
    gateway_entry._update_lock = asyncio.Lock()
    gateway_entry.gateway = SimpleNamespace(check_firmware_validity=AsyncMock(), close=AsyncMock())
    gateway_entry.supported_platforms = [SENSOR, SWITCH]
    gateway_entry._data.gateway = gateway_entry.gateway
    gateway_entry._data.interval = None
    gateway_entry._data.fw_interval = None
    gateway_entry._data.recording_interval = None
    gateway_entry.hass.config_entries.async_forward_entry_unload = AsyncMock(
        return_value=True
    )

    await gateway_entry.firmware_refresh()
    assert await gateway_entry.async_reset() is True
    gateway_entry.gateway.close.assert_awaited_once_with(force=False)


@pytest.mark.asyncio
async def test_migrate_entry_v1_renames_legacy_pointtapi_entities():
    entry = MagicMock()
    entry.version = 1
    entry.entry_id = "entry-1"
    entry.data = {CONF_PROTOCOL: POINTTAPI}
    registry = MagicMock()

    def registry_lookup(entity_id):
        return f"{entity_id}.entity" if entity_id.startswith(
            ("sensor.solar_solar_", "sensor.solar_total_", "water_heater.water_heater")
        ) else None

    registry.async_get.side_effect = registry_lookup
    hass = MagicMock()
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=registry):
        assert await integration.async_migrate_entry(hass, entry) is True

    assert registry.async_update_entity.call_count >= 5
    hass.config_entries.async_update_entry.assert_any_call(entry, version=2)


def _energy_sensor(attributes=None, new_stats_api=False):
    obj = SimpleNamespace(
        parent_id=None,
        id="energy1",
        state="old",
        name="Energy",
        entity_category=None,
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total",
        get_property=MagicMock(return_value={"value": {"CH": 2.5, "T": 18.0}}),
        fetch_range=AsyncMock(return_value={}),
        fetch_all=AsyncMock(return_value={}),
        last_entry=SimpleNamespace(values=MagicMock(return_value=[])),
    )
    sensor = EnergySensor(
        attributes or EnergySensors[1],
        "uuid-1",
        hass=MagicMock(),
        bosch_object=obj,
        gateway=MagicMock(),
        attr_uri="energy",
        new_stats_api=new_stats_api,
        is_enabled=True,
    )
    sensor.async_schedule_update_ha_state = MagicMock()
    sensor._attr_entity_id = "sensor.energy"
    sensor._short_id = "energy"
    return sensor


@pytest.mark.asyncio
async def test_energy_sensor_updates_normalized_and_unavailable_values():
    sensor = _energy_sensor()
    await sensor.async_update()
    assert sensor.native_value == 2.5
    assert sensor.statistic_id == "energy:chenergyexternal"

    sensor._bosch_object.get_property.return_value = {"value": {"OTHER": 1}}
    await sensor.async_update()
    assert sensor.native_value is None

    normalized = _energy_sensor(EcusRecordingSensors[0])
    normalized._bosch_object.get_property.return_value = {"value": {"T": 250}}
    await normalized.async_update()
    assert normalized.native_value == 25.0


def test_energy_sensor_generates_hourly_statistics_and_device_name():
    sensor = _energy_sensor()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    total, stats = sensor._generate_easycontrol_statistics(
        start, start + timedelta(hours=3), 1.25, 0
    )
    assert total == 3.75
    assert len(stats) == 3
    assert sensor.device_name == "Energy sensors"


@pytest.mark.asyncio
async def test_energy_sensor_fetches_past_data_and_appends_statistics():
    sensor = _energy_sensor()
    sensor._attr_read_key = "CH"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sensor._bosch_object.fetch_range = AsyncMock(return_value={"ok": True})
    assert await sensor.fetch_past_data(start, start) == {"ok": True}

    sensor.add_external_stats = MagicMock()
    with patch(
        "custom_components.bosch.sensor.energy.dt_util.start_of_local_day",
        return_value=start,
    ):
        total = sensor.append_statistics(
            [{"d": "01-01-2026", "CH": 24.0}], 0
        )
    assert total == 24.0
    sensor.add_external_stats.assert_called_once()


@pytest.mark.asyncio
async def test_energy_sensor_upserts_past_day_statistics():
    sensor = _energy_sensor()
    sensor._attr_read_key = "CH"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = datetime(2026, 1, 3, 12, tzinfo=timezone.utc)
    sensor.fetch_past_data = AsyncMock(
        return_value={"01-01-2026": {"CH": 24.0}}
    )
    sensor.get_stats_from_ha_db = AsyncMock(return_value={})
    sensor.add_external_stats = MagicMock()
    with patch("custom_components.bosch.sensor.energy.dt_util.now", return_value=now):
        await sensor._upsert_past_statistics(start, start + timedelta(hours=1))
    sensor.add_external_stats.assert_called_once()


@pytest.mark.asyncio
async def test_energy_sensor_inserts_from_empty_and_existing_statistics():
    sensor = _energy_sensor(new_stats_api=True)
    sensor.get_last_stat = AsyncMock(return_value={})
    sensor._bosch_object.fetch_all = AsyncMock(
        return_value={"day": {"d": "01-01-2026", "CH": 24.0}}
    )
    sensor.append_statistics = MagicMock()
    await sensor._insert_statistics()
    sensor.append_statistics.assert_called_once()

    sensor.get_last_stat = AsyncMock(
        return_value={sensor.statistic_id: [{"start": 1767225600.0, "state": 1.0, "sum": 2.0}]}
    )
    sensor.get_stats_from_ha_db = AsyncMock(return_value={})
    sensor.append_statistics.reset_mock()
    with patch(
        "custom_components.bosch.sensor.energy.dt_util.now",
        return_value=datetime(2026, 1, 3, 12, tzinfo=timezone.utc),
    ):
        await sensor._insert_statistics()
    sensor.append_statistics.assert_called_once()


@pytest.mark.asyncio
async def test_notification_sensor_copies_code_and_cause_attributes():
    obj = SimpleNamespace(
        state="active",
        parent_id=None,
        id="notification1",
        device_class=None,
        state_class=None,
        entity_category=None,
        get_value=MagicMock(side_effect=["E1", 7]),
    )
    sensor = NotificationSensor(
        hass=MagicMock(), uuid="uuid-1", bosch_object=obj, gateway=MagicMock(),
        name="Notification", attr_uri="notification", domain_name="Sensors",
    )
    sensor.attrs_write = MagicMock()
    await sensor.async_update()
    assert sensor._state == "active"
    sensor.attrs_write.assert_called_once_with(data={"displayCode": "E1", "cause": 7}, units=None)


@pytest.mark.asyncio
async def test_sensor_setup_pointtapi_filters_solar_and_schedules_backfill():
    coordinator = SimpleNamespace(
        data={"/gateway": {"value": "ok"}},
        last_update_success=True,
        async_request_refresh=AsyncMock(),
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    hass = MagicMock()
    hass.data = {}
    normal = SimpleNamespace(key="/gateway/DateTime")
    solar = SimpleNamespace(key="/solarCircuits/sc1/collectorTemperature")
    added = []
    scheduled = []

    with (
        patch.object(sensor_module, "_pointtapi_sensor_descriptions", return_value=[normal, solar]),
        patch.object(sensor_module, "BoschPoinTTAPISensorEntity", side_effect=lambda *args: args[-1]),
        patch.object(sensor_module, "_solar_data_available", return_value=False),
        patch.object(sensor_module, "_remove_solar_registry_entries") as remove_solar,
        patch("homeassistant.helpers.event.async_call_later", side_effect=lambda *args: scheduled.append(args[-1])),
    ):
        assert await async_setup_sensor_entry(hass, entry, added.extend) is True

    assert added == [normal]
    remove_solar.assert_called_once_with(hass, "uuid-1")
    assert "bosch_gas_backfill_entry-1" in hass.data
    assert scheduled


@pytest.mark.asyncio
async def test_sensor_setup_pointtapi_backfill_refreshes_and_calls_statistics():
    coordinator = SimpleNamespace(
        data={},
        last_update_success=True,
        async_request_refresh=AsyncMock(side_effect=lambda: setattr(coordinator, "data", {"/gateway": {}})),
    )
    entry = SimpleNamespace(
        entry_id="entry-2",
        data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
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
        patch.object(sensor_module, "async_backfill_gas_history", new=AsyncMock()) as backfill,
    ):
        assert await async_setup_sensor_entry(hass, entry, MagicMock()) is True
        await callback()

    coordinator.async_request_refresh.assert_awaited_once()
    backfill.assert_awaited_once_with(hass, coordinator.data, "sensor.pointtapi")


@pytest.mark.asyncio
async def test_sensor_setup_legacy_routes_sensor_kinds_and_circuits():
    from bosch_thermostat_client.const import ECUS_RECORDING, RECORDING, REGULAR, SENSOR
    from bosch_thermostat_client.const.easycontrol import ENERGY

    kinds = [RECORDING, REGULAR, "notification", ENERGY, ECUS_RECORDING, "ignored"]
    gateway_sensors = [SimpleNamespace(kind=kind, name=kind, attr_id=f"/{kind}") for kind in kinds]
    circuit_sensor = SimpleNamespace(name="Circuit sensor", attr_id="/circuit")
    circuit = SimpleNamespace(name="Heating", sensors=[circuit_sensor])
    gateway = SimpleNamespace(
        sensors=gateway_sensors,
        get_circuits=MagicMock(side_effect=lambda kind: [circuit] if kind == "hc" else []),
    )
    entry = SimpleNamespace(
        data={CONF_PROTOCOL: "xmpp", UUID: "uuid-1"},
        options={"new_stats_api": True},
        runtime_data=SimpleNamespace(gateway=gateway),
    )
    fake_classes = {kind: MagicMock(side_effect=lambda **kwargs: kwargs) for kind in sensor_module.SensorClass}
    added = []
    with patch.object(sensor_module, "SensorClass", fake_classes), patch.object(sensor_module, "CircuitSensor", return_value="circuit"):
        assert await async_setup_sensor_entry(MagicMock(), entry, added.extend) is True

    assert entry.runtime_data.sensor
    assert entry.runtime_data.recording
    assert "circuit" in added


@pytest.mark.asyncio
async def test_recording_sensor_upserts_historical_values_and_fills_gaps():
    now = datetime(2026, 1, 3, 12, tzinfo=timezone.utc)
    start = datetime(2026, 1, 2, 8, tzinfo=timezone.utc)
    obj = SimpleNamespace(
        parent_id=None,
        id="recording1",
        name="Recording",
        state=[{"d": start, "value": 4.0}],
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total",
        entity_category=None,
    )
    sensor = RecordingSensor(
        hass=MagicMock(), uuid="uuid-1", bosch_object=obj, gateway=MagicMock(),
        name="Recording", attr_uri="recording", new_stats_api=True,
    )
    sensor._attr_entity_id = "sensor.recording"
    sensor._short_id = "recording"
    sensor.fetch_past_data = AsyncMock(
        return_value={
            "one": {"d": start, "value": 2.0},
            "two": {"d": start + timedelta(hours=2), "value": 3.0},
        }
    )
    sensor.get_stats_from_ha_db = AsyncMock(return_value={})
    sensor.add_external_stats = MagicMock()

    with patch("custom_components.bosch.sensor.recording.dt_util.now", return_value=now):
        await sensor._upsert_past_statistics(start, start + timedelta(hours=3))

    sensor.add_external_stats.assert_called_once()
    pushed = sensor.add_external_stats.call_args.kwargs["stats"]
    assert [row["state"] for row in pushed] == [2.0, 0, 3.0, 0]


@pytest.mark.asyncio
async def test_binary_sensor_legacy_setup_and_state_updates():
    obj = SimpleNamespace(
        kind="binary", name="Door", attr_id="door", state="on", state_message="open",
        get_value=MagicMock(return_value="true"), get_property=MagicMock(return_value={"x": 1}),
        parent_id=None,
    )
    gateway = SimpleNamespace(sensors=[obj])
    entry = SimpleNamespace(data={CONF_PROTOCOL: "xmpp", UUID: "uuid-1"}, runtime_data=SimpleNamespace(gateway=gateway))
    added = []
    with patch.object(binary_module, "async_dispatcher_send"):
        assert await binary_module.async_setup_entry(MagicMock(), entry, added.extend) is True
    sensor = added[0]
    sensor.async_schedule_update_ha_state = MagicMock()
    await sensor.async_update()
    assert sensor.is_on is True
    assert sensor.extra_state_attributes == {"x": 1}
    assert sensor.should_poll is False


@pytest.mark.asyncio
async def test_binary_sensor_pointtapi_setup_without_coordinator_and_used_state():
    entry = SimpleNamespace(
        data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
        runtime_data=SimpleNamespace(coordinator=None),
    )
    added = MagicMock()
    assert await binary_module.async_setup_entry(MagicMock(), entry, added) is True
    added.assert_called_once_with([])

    obj = SimpleNamespace(
        parent_id=None, name="Door", attr_id="door", state="used", state_message="used",
        get_value=MagicMock(return_value="true"), get_property=MagicMock(return_value={}),
    )
    sensor = binary_module.BoschBinarySensor(MagicMock(), "uuid-1", obj, MagicMock(), "Door", "door")
    sensor.async_schedule_update_ha_state = MagicMock()
    await sensor.async_update()
    assert sensor.is_on is True
    await sensor.async_update()
    assert sensor.async_schedule_update_ha_state.call_count == 1


@pytest.mark.asyncio
async def test_binary_sensor_pointtapi_setup_with_coordinator():
    coordinator = SimpleNamespace(data={})
    entry = SimpleNamespace(
        entry_id="entry-binary", data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    add_entities = MagicMock()
    binary_entities = import_module("custom_components.bosch.pointtapi_entities")
    with (
        patch.object(binary_entities, "POINTTAPI_BINARY_SENSOR_DESCRIPTIONS", [MagicMock()]),
        patch.object(binary_entities, "BoschPoinTTAPIBinarySensorEntity", return_value="point-binary"),
        patch.object(binary_entities, "_pointtapi_open_window_binary_sensor_descriptions", return_value=[]),
        patch.object(binary_entities, "_pointtapi_thermostat_valve_warning_binary_sensor_descriptions", return_value=[]),
    ):
        assert await binary_module.async_setup_entry(MagicMock(), entry, add_entities) is True
    assert add_entities.call_args.args[0] == ["point-binary"]


@pytest.mark.asyncio
async def test_number_legacy_entity_properties_and_write():
    obj = SimpleNamespace(
        state=12, min_value=None, max_value=None, step=0.5,
        unit_of_measurement="C", name="Limit", attr_id="limit", parent_id=None,
        set_value=AsyncMock(),
    )
    number = number_module.BoschNumber(
        MagicMock(), "uuid-1", obj, MagicMock(), "Limit", "limit", "Switches", is_enabled=True
    )
    assert number.native_min_value == 0
    assert number.native_max_value == 255
    assert number.native_value == 12.0
    assert number.native_step == 0.5
    await number.async_set_native_value(15)
    obj.set_value.assert_awaited_once_with(15)
    obj.state = None
    assert number.native_value is None


def test_simple_sensor_classes_expose_device_names():
    base = SimpleNamespace(
        parent_id=None, id="sensor", name="Sensor", attr_id="sensor",
        state=None, device_class=None, state_class=None, entity_category=None,
        unit_of_measurement="C",
    )
    gateway = SimpleNamespace(device_model="CT200", device_type="EASYCONTROL", firmware="1")
    assert BoschSensor(MagicMock(), "uuid-1", base, gateway, "Sensor", "sensor").device_name == "Bosch sensors"
    assert CircuitSensor(
        hass=MagicMock(), uuid="uuid-1", bosch_object=base, gateway=gateway,
        name="Sensor", attr_uri="sensor", domain_name="Heating", circuit_type="hc",
    ).device_name == "Heating circuit Heating"


@pytest.mark.asyncio
async def test_number_pointtapi_setup_and_circuit_properties():
    entry = SimpleNamespace(
        data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
        runtime_data=SimpleNamespace(coordinator=None),
    )
    added = MagicMock()
    assert await number_module.async_setup_entry(MagicMock(), entry, added) is True
    added.assert_called_once_with([])

    obj = SimpleNamespace(
        state=4, min_value=1, max_value=9, step=1, unit_of_measurement=None,
        name="Limit", attr_id="limit", parent_id=None,
    )
    number = number_module.CircuitNumber(
        MagicMock(), "uuid-1", obj, MagicMock(), "Limit", "limit", "Heating", "hc"
    )
    assert number.native_min_value == 1.0
    assert number.native_max_value == 9.0
    assert number.native_unit_of_measurement is None
    assert number.device_name == "Heating circuit Heating"
    assert await number_module.async_setup_platform(MagicMock(), {}, MagicMock()) is None


@pytest.mark.asyncio
async def test_number_setup_pointtapi_and_legacy_paths():
    coordinator = SimpleNamespace(data={})
    point_entry = SimpleNamespace(
        entry_id="entry-number", data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    add_entities = MagicMock()
    with (
        patch.object(number_module, "_pointtapi_number_descriptions", return_value=[MagicMock()]),
        patch.object(number_module, "BoschPoinTTAPINumberEntity", return_value="point-number"),
    ):
        assert await number_module.async_setup_entry(MagicMock(), point_entry, add_entities) is True
    assert add_entities.call_args.args[0] == ["point-number"]

    switch = SimpleNamespace(state=1, min_value=0, max_value=10, step=1, unit_of_measurement="C", name="Limit", attr_id="limit", parent_id=None)
    circuit = SimpleNamespace(name="Heating", number_switches=[switch])
    gateway = SimpleNamespace(number_switches=[switch], get_circuits=MagicMock(side_effect=lambda kind: [circuit] if kind == "hc" else []))
    legacy_entry = SimpleNamespace(
        data={CONF_PROTOCOL: "xmpp", UUID: "uuid-1"},
        runtime_data=SimpleNamespace(gateway=gateway),
    )
    add_entities.reset_mock()
    with patch.object(number_module, "async_dispatcher_send"):
        assert await number_module.async_setup_entry(MagicMock(), legacy_entry, add_entities) is True
    assert len(add_entities.call_args.args[0]) == 2


@pytest.mark.asyncio
async def test_select_legacy_entity_options_and_update():
    obj = SimpleNamespace(
        state="auto", options=["auto", "manual"], name="Mode", attr_id="mode", parent_id=None,
        set_value=AsyncMock(),
    )
    select = select_module.BoschSelect(
        MagicMock(), "uuid-1", obj, MagicMock(), "Mode", "mode", "Select", is_enabled=True
    )
    select.schedule_update_ha_state = MagicMock()
    assert select.current_option == "auto"
    assert select.options == ["auto", "manual"]
    await select.async_select_option("manual")
    obj.set_value.assert_awaited_once_with(value="manual")
    obj.state = "manual"
    await select.async_update()
    assert select.current_option == "manual"
    assert select.should_poll is False


@pytest.mark.asyncio
async def test_select_pointtapi_setup_without_coordinator_and_empty_options():
    entry = SimpleNamespace(
        data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
        runtime_data=SimpleNamespace(coordinator=None),
    )
    added = MagicMock()
    assert await select_module.async_setup_entry(MagicMock(), entry, added) is True
    added.assert_called_once_with([])
    obj = SimpleNamespace(state="x", options=None, name="Mode", attr_id="mode", parent_id=None, set_value=AsyncMock())
    select = select_module.BoschSelect(MagicMock(), "uuid-1", obj, MagicMock(), "Mode", "mode", "Select")
    assert select.options == []
    assert await select_module.async_setup_platform(MagicMock(), {}, MagicMock()) is None


@pytest.mark.asyncio
async def test_select_setup_pointtapi_and_legacy_paths():
    coordinator = SimpleNamespace(data={})
    point_entry = SimpleNamespace(
        entry_id="entry-select", data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    add_entities = MagicMock()
    with (
        patch.object(select_module, "_pointtapi_select_descriptions", return_value=[MagicMock()]),
        patch.object(select_module, "BoschPoinTTAPISelectEntity", return_value="point-select"),
    ):
        assert await select_module.async_setup_entry(MagicMock(), point_entry, add_entities) is True
    assert add_entities.call_args.args[0] == ["point-select"]

    choice = SimpleNamespace(state="auto", options=["auto"], name="Mode", attr_id="mode", parent_id=None, set_value=AsyncMock())
    gateway = SimpleNamespace(switches=SimpleNamespace(selects=[choice]))
    legacy_entry = SimpleNamespace(
        data={CONF_PROTOCOL: "xmpp", UUID: "uuid-1"},
        runtime_data=SimpleNamespace(gateway=gateway),
    )
    add_entities.reset_mock()
    with patch.object(select_module, "async_dispatcher_send"):
        assert await select_module.async_setup_entry(MagicMock(), legacy_entry, add_entities) is True
    assert len(add_entities.call_args.args[0]) == 1


@pytest.mark.asyncio
async def test_update_setup_handles_protocol_and_coordinator_states():
    add_entities = MagicMock()
    legacy = SimpleNamespace(data={CONF_PROTOCOL: "xmpp"}, runtime_data=SimpleNamespace())
    assert await update_module.async_setup_entry(MagicMock(), legacy, add_entities) is True
    add_entities.assert_called_once_with([])

    coordinator = SimpleNamespace(data={})
    point_entry = SimpleNamespace(
        entry_id="entry-3", data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    add_entities.reset_mock()
    with patch("custom_components.bosch.pointtapi_entities.POINTTAPI_UPDATE_DESCRIPTIONS", [MagicMock()]):
        assert await update_module.async_setup_entry(MagicMock(), point_entry, add_entities) is True
    assert len(add_entities.call_args.args[0]) == 1

    no_coordinator = SimpleNamespace(data={CONF_PROTOCOL: POINTTAPI}, runtime_data=SimpleNamespace(coordinator=None))
    add_entities.reset_mock()
    assert await update_module.async_setup_entry(MagicMock(), no_coordinator, add_entities) is True
    add_entities.assert_called_once_with([])


def _water_heater_object():
    return SimpleNamespace(
        parent_id=None,
        id="dhw1",
        name="Hot water",
        state="heating",
        setpoint=50,
        schedule=None,
        ha_mode="eco",
        ha_modes=["eco", "boost"],
        support_target_temp=True,
        current_temp=42,
        target_temperature=50,
        temp_units="C",
        update_initialized=True,
        set_service_call=AsyncMock(),
        set_temperature=AsyncMock(),
        set_ha_mode=AsyncMock(return_value=1),
    )


@pytest.mark.asyncio
async def test_water_heater_entity_commands_state_and_features():
    obj = _water_heater_object()
    heater = water_module.BoschWaterHeater(
        MagicMock(), "uuid-1", obj,
        SimpleNamespace(device_model="CT200", device_type="EASYCONTROL", firmware="1"),
    )
    heater.async_schedule_update_ha_state = MagicMock()
    await heater.service_charge("start")
    obj.set_service_call.assert_awaited_once()
    await heater.async_set_temperature(temperature=55)
    obj.set_temperature.assert_awaited_once_with(55)
    assert await heater.async_set_operation_mode("boost") is True
    assert heater.supported_features
    assert heater.extra_state_attributes["target_temp_step"] == 1
    await heater.async_update()
    assert heater.current_temperature == 42
    assert heater.current_operation == "eco"
    assert heater.operation_list == ["eco", "boost"]


@pytest.mark.asyncio
async def test_water_heater_setup_pointtapi_without_coordinator():
    entry = SimpleNamespace(
        data={CONF_PROTOCOL: POINTTAPI, UUID: "uuid-1"},
        runtime_data=SimpleNamespace(coordinator=None),
    )
    add_entities = MagicMock()
    assert await water_module.async_setup_entry(MagicMock(), entry, add_entities) is True
    add_entities.assert_called_once_with([])


@pytest.mark.asyncio
async def test_water_heater_update_handles_uninitialized_and_off_target_modes():
    obj = _water_heater_object()
    heater = water_module.BoschWaterHeater(MagicMock(), "uuid-1", obj, MagicMock())
    heater.async_schedule_update_ha_state = MagicMock()
    obj.update_initialized = False
    await heater.async_update()
    assert heater.current_temperature is None
    obj.update_initialized = True
    obj.ha_mode = "off"
    obj.ha_modes = ["off"]
    obj.support_target_temp = False
    await heater.async_update()
    assert heater.supported_features


@pytest.mark.asyncio
async def test_water_heater_legacy_setup_registers_service_and_state_attributes():
    obj = _water_heater_object()
    obj.schedule = SimpleNamespace(active_program="night")
    gateway = SimpleNamespace(dhw_circuits=[obj])
    entry = SimpleNamespace(
        data={CONF_PROTOCOL: "xmpp", UUID: "uuid-1"},
        runtime_data=SimpleNamespace(gateway=gateway),
    )
    platform = MagicMock()
    add_entities = MagicMock()
    with (
        patch.object(water_module.entity_platform, "current_platform", SimpleNamespace(get=lambda: platform)),
        patch.object(water_module, "async_dispatcher_send"),
    ):
        assert await water_module.async_setup_entry(MagicMock(), entry, add_entities) is True
    assert len(add_entities.call_args.args[0]) == 1
    platform.async_register_entity_service.assert_called_once()

    heater = entry.runtime_data.water_heater[0]
    assert heater.state_attributes["switchPoint"] == "night"
    obj.support_target_temp = False
    obj.ha_mode = "off"
    obj.setpoint = "off"
    assert heater.supported_features
