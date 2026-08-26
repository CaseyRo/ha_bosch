"""Tests for POINTTAPI stale device cleanup."""
from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

integration = import_module("custom_components.bosch.__init__")


def test_removes_stale_valve_device_and_entities(monkeypatch):
    stale = SimpleNamespace(
        id="stale-device",
        identifiers={("bosch", "uuid_trv_1")},
    )
    current = SimpleNamespace(
        id="current-device",
        identifiers={("bosch", "uuid_trv_2")},
    )
    stale_entity = SimpleNamespace(
        entity_id="switch.old_child_lock",
        device_id="stale-device",
        config_entry_id="entry-1",
    )
    device_registry = MagicMock(devices={stale.id: stale, current.id: current})
    entity_registry = MagicMock(entities={stale_entity.entity_id: stale_entity})
    monkeypatch.setattr(dr, "async_get", lambda _: device_registry)
    monkeypatch.setattr(er, "async_get", lambda _: entity_registry)

    integration._remove_stale_pointtapi_valve_devices(
        MagicMock(),
        "entry-1",
        "uuid",
        {
            "/devices/device1/type": {"value": "thermostat"},
            "/devices/device2/type": {"value": "thermostat_valve"},
        },
    )

    entity_registry.async_remove.assert_called_once_with("switch.old_child_lock")
    device_registry.async_remove_device.assert_called_once_with("stale-device")
