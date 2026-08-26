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