"""Tests for POINTTAPI stale device removal eligibility."""
from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

integration = import_module("custom_components.bosch.__init__")


def _entry(data, coordinator_data):
    coordinator = SimpleNamespace(data=coordinator_data)
    return SimpleNamespace(
        data=data,
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )


@pytest.mark.asyncio
async def test_allows_removing_absent_valve_device():
    entry = _entry(
        {"http_xmpp": "pointtapi", "uuid": "uuid"},
        {"/devices/list": {"value": [{"id": 2, "type": "thermostat"}]}},
    )
    device = SimpleNamespace(identifiers={("bosch", "uuid_trv_1")})

    assert await integration.async_remove_config_entry_device(
        MagicMock(), entry, device
    ) is True


@pytest.mark.asyncio
async def test_keeps_present_valve_device():
    entry = _entry(
        {"http_xmpp": "pointtapi", "uuid": "uuid"},
        {"/devices/device2/type": {"value": "thermostat_valve"}},
    )
    device = SimpleNamespace(identifiers={("bosch", "uuid_trv_2")})

    assert await integration.async_remove_config_entry_device(
        MagicMock(), entry, device
    ) is False


@pytest.mark.asyncio
async def test_does_not_allow_removing_gateway_device():
    entry = _entry(
        {"http_xmpp": "pointtapi", "uuid": "uuid"},
        {},
    )
    device = SimpleNamespace(identifiers={("bosch", "uuid")})

    assert await integration.async_remove_config_entry_device(
        MagicMock(), entry, device
    ) is False
