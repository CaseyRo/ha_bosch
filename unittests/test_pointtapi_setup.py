"""Tests for POINTTAPI setup ordering."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.bosch.const import POINTTAPI


ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME = "bosch_setup_under_test"
spec = importlib.util.spec_from_file_location(
    MODULE_NAME, ROOT / "custom_components" / "bosch" / "__init__.py"
)
assert spec and spec.loader
bosch_module = importlib.util.module_from_spec(spec)
bosch_module.__package__ = "custom_components.bosch"
sys.modules[MODULE_NAME] = bosch_module
spec.loader.exec_module(bosch_module)
sys.modules.pop(MODULE_NAME)


def _gateway_entry(hass, entry):
    return bosch_module.BoschGatewayEntry(
        hass=hass,
        uuid="gateway-123",
        host="gateway-123",
        protocol=POINTTAPI,
        device_type="EASYCONTROL",
        access_key="",
        access_token="token",
        entry=entry,
    )


@pytest.mark.asyncio
async def test_pointtapi_refreshes_before_forwarding_platforms():
    events: list[str] = []
    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(
        side_effect=lambda *_: events.append("forward")
    )
    entry = SimpleNamespace(
        entry_id="entry-123",
        runtime_data=SimpleNamespace(gateway=None, coordinator=None),
    )
    client = MagicMock()
    client.get = AsyncMock(side_effect=lambda *_: events.append("connection"))
    device_registry = MagicMock()

    class Coordinator:
        def __init__(self, *_):
            pass

        async def async_config_entry_first_refresh(self):
            events.append("refresh")

    with (
        patch.object(bosch_module, "async_get_clientsession", return_value=MagicMock()),
        patch.object(bosch_module, "PoinTTAPIClient", return_value=client),
        patch.object(bosch_module, "PoinTTAPIDataUpdateCoordinator", Coordinator),
        patch.object(bosch_module.dr, "async_get", return_value=device_registry),
    ):
        assert await _gateway_entry(hass, entry).async_init() is True

    assert events.index("refresh") < events.index("forward")


@pytest.mark.asyncio
async def test_pointtapi_refresh_failure_does_not_forward_platforms():
    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    entry = SimpleNamespace(
        entry_id="entry-123",
        runtime_data=SimpleNamespace(gateway=None, coordinator=None),
    )
    client = MagicMock()
    client.get = AsyncMock()
    device_registry = MagicMock()

    class Coordinator:
        def __init__(self, *_):
            pass

        async def async_config_entry_first_refresh(self):
            raise ConfigEntryAuthFailed("expired token")

    with (
        patch.object(bosch_module, "async_get_clientsession", return_value=MagicMock()),
        patch.object(bosch_module, "PoinTTAPIClient", return_value=client),
        patch.object(bosch_module, "PoinTTAPIDataUpdateCoordinator", Coordinator),
        patch.object(bosch_module.dr, "async_get", return_value=device_registry),
    ):
        with pytest.raises(ConfigEntryAuthFailed, match="expired token"):
            await _gateway_entry(hass, entry).async_init()

    hass.config_entries.async_forward_entry_setups.assert_not_awaited()


@pytest.mark.asyncio
async def test_pointtapi_custom_get_and_put():
    hass = MagicMock()
    entry = SimpleNamespace(
        entry_id="entry-123",
        runtime_data=SimpleNamespace(gateway=None, coordinator=None),
    )
    gw_entry = _gateway_entry(hass, entry)
    gw_entry._update_lock = MagicMock()
    gw_entry._update_lock.__aenter__ = AsyncMock()
    gw_entry._update_lock.__aexit__ = AsyncMock()

    client = MagicMock()
    client.get = AsyncMock(return_value={"value": "2026-08-26T12:00:00"})
    client.put = AsyncMock(return_value=True)
    gw_entry.gateway = client

    # Test POINTTAPI custom_get
    get_res = await gw_entry.custom_get("/gateway/DateTime")
    assert get_res == {"value": "2026-08-26T12:00:00"}
    client.get.assert_awaited_once_with(uri="/gateway/DateTime")

    # Test POINTTAPI custom_put
    put_res = await gw_entry.custom_put("/gateway/time/timeZone", "Europe/Brussels")
    assert put_res is True
    client.put.assert_awaited_once_with(uri="/gateway/time/timeZone", value="Europe/Brussels")


@pytest.mark.asyncio
async def test_xmpp_custom_get_and_put_fallbacks():
    hass = MagicMock()
    entry = SimpleNamespace(
        entry_id="entry-123",
        runtime_data=SimpleNamespace(gateway=None, coordinator=None),
    )
    gw_entry = bosch_module.BoschGatewayEntry(
        hass=hass,
        uuid="gateway-123",
        host="192.168.1.100",
        protocol="xmpp",
        device_type="NEFIT",
        access_key="key",
        access_token="token",
        entry=entry,
    )
    gw_entry._update_lock = MagicMock()
    gw_entry._update_lock.__aenter__ = AsyncMock()
    gw_entry._update_lock.__aexit__ = AsyncMock()

    client = MagicMock()
    client.raw_query = AsyncMock(return_value="xmpp_val")
    client.raw_put = AsyncMock(return_value="xmpp_put_res")
    gw_entry.gateway = client

    get_res = await gw_entry.custom_get("/gateway/name")
    assert get_res == "xmpp_val"
    client.raw_query.assert_awaited_once_with(path="/gateway/name")

    put_res = await gw_entry.custom_put("/gateway/name", "NewName")
    assert put_res == "xmpp_put_res"
    client.raw_put.assert_awaited_once_with(path="/gateway/name", value="NewName")


@pytest.mark.asyncio
async def test_pointtapi_thermostat_refresh_triggers_coordinator():
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    entry = SimpleNamespace(
        entry_id="entry-123",
        runtime_data=SimpleNamespace(gateway=None, coordinator=coordinator),
    )
    gw_entry = _gateway_entry(hass, entry)
    gw_entry._update_lock = MagicMock()
    gw_entry._update_lock.locked.return_value = False

    await gw_entry.thermostat_refresh()
    coordinator.async_request_refresh.assert_awaited_once()