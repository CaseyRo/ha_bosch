"""Room thermostats (type room_thermostat) on a CT200: issue #69.

The fixture combines the stripped diagnostics attached to #69 with the wth
readings from the same install's scan on upstream #554.
"""
from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bosch.pointtapi_coordinator import (
    _discovery_path_needed,
    _is_slow_resource,
)
from custom_components.bosch.pointtapi_entities import (
    BoschPoinTTAPIGenericSwitchEntity,
    BoschPoinTTAPINumberEntity,
    BoschPoinTTAPISensorEntity,
    _pointtapi_number_descriptions,
    _pointtapi_sensor_descriptions,
    _pointtapi_thermostat_valve_switch_descriptions,
)

integration = import_module("custom_components.bosch.__init__")

WTH = "/devices/device2/wth"

DATA = {
    "/devices/list": {
        "value": [
            {"name": "RWFzeUNvbnRyb2w=", "zone": 1, "protocol": "no_protocol",
             "id": 1, "battery": "unknown", "signal": 0, "type": "thermostat"},
            {"name": "Um9vbSAyLTM=", "zone": 2, "protocol": "homematicip",
             "id": 2, "battery": "ok", "signal": 52, "type": "room_thermostat"},
            {"name": "Um9vbSAxLTE=", "zone": 1, "protocol": "homematicip",
             "id": 3, "battery": "ok", "signal": 85, "type": "thermostat_valve",
             "warning": 0},
        ]
    },
    "/devices/device2/type": {"type": "stringValue", "value": "room_thermostat"},
    WTH: {
        "type": "refEnum",
        "references": [
            {"id": f"{WTH}/childLock"},
            {"id": f"{WTH}/humidityActual"},
            {"id": f"{WTH}/offset"},
            {"id": f"{WTH}/temperatureActual"},
        ],
    },
    f"{WTH}/childLock": {
        "type": "refEnum",
        "references": [{"id": f"{WTH}/childLock/enabled"}],
    },
    f"{WTH}/childLock/enabled": {
        "type": "stringValue", "writeable": 1, "value": "false",
    },
    f"{WTH}/humidityActual": {
        "type": "floatValue", "writeable": 0, "value": 60,
        "unitOfMeasure": "%", "minValue": 0, "maxValue": 100,
    },
    f"{WTH}/offset": {
        "type": "floatValue", "writeable": 1, "value": 0,
        "unitOfMeasure": "C", "minValue": -2, "maxValue": 2, "stepSize": 0.5,
    },
    f"{WTH}/temperatureActual": {
        "type": "floatValue", "writeable": 0, "value": 22.2,
        "unitOfMeasure": "C", "minValue": 5, "maxValue": 30,
    },
    "/devices/device3/type": {"type": "stringValue", "value": "thermostat_valve"},
    "/devices/device3/etrv/temperatureActual": {"type": "floatValue", "value": 23},
}

ROOM_DEVICE = ("bosch", "uuid1_rth_2")


def _coordinator(data=DATA):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = True
    coord.client = MagicMock()
    coord.client.put = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    return coord


def _sensor(key):
    desc = next(d for d in _pointtapi_sensor_descriptions(DATA) if d.key == key)
    ent = BoschPoinTTAPISensorEntity(_coordinator(), "entry1", "uuid1", desc)
    ent.async_write_ha_state = MagicMock()
    ent._handle_coordinator_update()
    return ent


@pytest.mark.parametrize(
    "leaf", ["", "/childLock", "/childLock/enabled", "/humidityActual",
             "/offset", "/temperatureActual"],
)
def test_wth_paths_are_discovered_and_polled_fast(leaf):
    assert _discovery_path_needed(WTH + leaf) is True
    if leaf:
        assert _is_slow_resource(WTH + leaf) is False


def test_readings_get_a_room_thermostat_device():
    temp = _sensor(f"{WTH}/temperatureActual")
    humidity = _sensor(f"{WTH}/humidityActual")

    assert temp.native_value == 22.2
    assert humidity.native_value == 60
    for ent in (temp, humidity):
        assert ent.available
        assert ent.device_info["identifiers"] == {ROOM_DEVICE}
        assert ent.device_info["name"] == "Room thermostat Room 2-3"
        assert ent.device_info["via_device"] == ("bosch", "uuid1")


def test_battery_and_signal_come_from_the_list_row():
    assert _sensor("/devices/list/room_thermostat/2/battery").native_value == "OK"
    signal = _sensor("/devices/list/room_thermostat/2/signal")
    assert signal.native_value == 52
    assert signal.device_info["identifiers"] == {ROOM_DEVICE}


def test_readings_are_not_attached_to_a_valve_device():
    descs = _pointtapi_sensor_descriptions(DATA)
    keys = [d.key for d in descs]
    assert keys.count(f"{WTH}/temperatureActual") == 1
    assert not any(k.startswith("/devices/list/thermostat_valve/2/") for k in keys)
    # The real valve keeps its own device.
    valve = _sensor("/devices/device3/etrv/temperatureActual")
    assert valve.device_info["identifiers"] == {("bosch", "uuid1_trv_3")}


def test_readings_unavailable_until_discovered():
    data = {k: v for k, v in DATA.items() if not k.startswith(WTH)}
    desc = next(
        d for d in _pointtapi_sensor_descriptions(data)
        if d.key == f"{WTH}/temperatureActual"
    )
    ent = BoschPoinTTAPISensorEntity(_coordinator(data), "entry1", "uuid1", desc)
    assert ent.available is False


def test_offset_number_uses_api_limits_and_room_device():
    desc = next(d for d in _pointtapi_number_descriptions(DATA) if d.key == f"{WTH}/offset")
    ent = BoschPoinTTAPINumberEntity(_coordinator(), "entry1", "uuid1", desc)

    assert (desc.native_min_value, desc.native_max_value, desc.native_step) == (-2, 2, 0.5)
    assert ent.device_info["identifiers"] == {ROOM_DEVICE}


def test_child_lock_switch_uses_room_device():
    desc = next(
        d for d in _pointtapi_thermostat_valve_switch_descriptions(DATA)
        if d.key == f"{WTH}/childLock/enabled"
    )
    ent = BoschPoinTTAPIGenericSwitchEntity(_coordinator(), "entry1", "uuid1", desc)
    assert ent.device_info["identifiers"] == {ROOM_DEVICE}


@pytest.mark.asyncio
@pytest.mark.parametrize("present, removable", [(True, False), (False, True)])
async def test_room_thermostat_device_removal(present, removable):
    data = DATA if present else {"/devices/list": {"value": []}}
    entry = SimpleNamespace(
        data={"http_xmpp": "pointtapi", "uuid": "uuid1"},
        runtime_data=SimpleNamespace(coordinator=SimpleNamespace(data=data)),
    )
    device = SimpleNamespace(identifiers={ROOM_DEVICE})
    assert await integration.async_remove_config_entry_device(
        MagicMock(), entry, device
    ) is removable
