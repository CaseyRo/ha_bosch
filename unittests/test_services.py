"""Unit tests for Bosch service registration and handlers."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.const import ATTR_DEVICE_ID

from custom_components.bosch.const import (
    DOMAIN,
    RECORDING_SERVICE_UPDATE,
    SERVICE_DEBUG,
    SERVICE_GET,
    SERVICE_PUT_FLOAT,
    SERVICE_PUT_STRING,
    SERVICE_UPDATE,
)
from custom_components.bosch.services import (
    async_register_debug_service,
    async_register_services,
    find_gateway_entry,
)


def _service_call(**data):
    return SimpleNamespace(data=data)


def _gateway_entry():
    gateway = MagicMock()
    gateway.uuid = "uuid1"
    gateway.make_rawscan = AsyncMock(return_value={"scan": True})
    gateway.thermostat_refresh = AsyncMock()
    gateway.recording_sensors_update = AsyncMock()
    gateway.custom_get = AsyncMock(return_value={"value": 12})
    gateway.custom_put = AsyncMock(return_value=True)
    config_entry = SimpleNamespace(
        runtime_data=SimpleNamespace(recording=[]),
    )
    gateway_entry = SimpleNamespace(
        gateway=gateway,
        config_entry=config_entry,
        uuid="uuid1",
        make_rawscan=gateway.make_rawscan,
        thermostat_refresh=gateway.thermostat_refresh,
        recording_sensors_update=gateway.recording_sensors_update,
        custom_get=gateway.custom_get,
        custom_put=gateway.custom_put,
    )
    return gateway_entry


def _registered_handlers(hass):
    return {
        call.args[1]: call.args[2]
        for call in hass.services.async_register.call_args_list
    }


class TestFindGatewayEntry:
    def test_finds_unique_bosch_runtime_gateway_entries(self):
        hass = MagicMock()
        entry = SimpleNamespace(
            domain=DOMAIN,
            runtime_data=SimpleNamespace(gateway_entry="gateway-entry"),
        )
        other = SimpleNamespace(
            domain="light",
            runtime_data=SimpleNamespace(gateway_entry="ignored"),
        )
        device = SimpleNamespace(config_entries={"entry1", "entry2"})
        registry = MagicMock()
        registry.async_get.side_effect = [device, None]
        hass.config_entries.async_get_entry.side_effect = [entry, entry, other]

        with patch("custom_components.bosch.services.dr.async_get", return_value=registry):
            result = find_gateway_entry(hass, ["device1", "unknown"])

        assert result == ["gateway-entry"]
        assert registry.async_get.call_count == 2

    def test_ignores_entries_without_runtime_data(self):
        hass = MagicMock()
        entry = SimpleNamespace(domain=DOMAIN, runtime_data=None)
        device = SimpleNamespace(config_entries={"entry1"})
        registry = MagicMock()
        registry.async_get.return_value = device
        hass.config_entries.async_get_entry.return_value = entry

        with patch("custom_components.bosch.services.dr.async_get", return_value=registry):
            assert find_gateway_entry(hass, ["device1"]) == []


class TestServiceRegistration:
    def test_registers_debug_service(self):
        hass = MagicMock()
        async_register_debug_service(hass, MagicMock())

        handlers = _registered_handlers(hass)
        assert SERVICE_DEBUG in handlers
        assert hass.services.async_register.call_args.kwargs["supports_response"]

    def test_registers_all_services(self):
        hass = MagicMock()

        async_register_services(hass, MagicMock())

        handlers = _registered_handlers(hass)
        assert set(handlers) >= {
            SERVICE_UPDATE,
            RECORDING_SERVICE_UPDATE,
            SERVICE_GET,
            SERVICE_PUT_STRING,
            SERVICE_PUT_FLOAT,
            "fetch_recordings_sensor_range",
        }


class TestDebugService:
    @pytest.mark.asyncio
    async def test_debug_handler_returns_scans(self):
        hass = MagicMock()
        hass.config.path.return_value = "www/bosch_scan.json"
        gateway = _gateway_entry()
        async_register_debug_service(hass, MagicMock())
        handler = _registered_handlers(hass)[SERVICE_DEBUG]

        with patch("custom_components.bosch.services.find_gateway_entry", return_value=[gateway]):
            result = await handler(_service_call(**{ATTR_DEVICE_ID: ["device1"]}))

        assert result == {"data": [{"scan": True}]}
        gateway.make_rawscan.assert_awaited_once_with("www/bosch_scan.json")

    @pytest.mark.asyncio
    async def test_debug_handler_returns_none_without_gateway(self):
        hass = MagicMock()
        async_register_debug_service(hass, MagicMock())
        handler = _registered_handlers(hass)[SERVICE_DEBUG]

        with patch("custom_components.bosch.services.find_gateway_entry", return_value=[]):
            assert await handler(_service_call(**{ATTR_DEVICE_ID: ["missing"]})) is None


class TestRegisteredHandlers:
    @pytest.fixture
    def handlers(self):
        hass = MagicMock()
        async_register_services(hass, MagicMock())
        return _registered_handlers(hass)

    @pytest.mark.asyncio
    async def test_update_refreshes_all_gateways(self, handlers):
        entries = [_gateway_entry(), _gateway_entry()]
        with patch("custom_components.bosch.services.find_gateway_entry", return_value=entries):
            await handlers[SERVICE_UPDATE](_service_call(**{ATTR_DEVICE_ID: ["device1"]}))

        for entry in entries:
            entry.thermostat_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recording_refresh_updates_gateway_and_recordings(self, handlers):
        entry = _gateway_entry()
        with patch("custom_components.bosch.services.find_gateway_entry", return_value=[entry]):
            await handlers[RECORDING_SERVICE_UPDATE](_service_call(**{ATTR_DEVICE_ID: ["device1"]}))

        entry.thermostat_refresh.assert_awaited_once()
        entry.recording_sensors_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_range_only_updates_matching_enabled_recording(self, handlers):
        entry = _gateway_entry()
        matching = SimpleNamespace(
            enabled=True,
            statistic_id="recording:match",
            insert_statistics_range=AsyncMock(),
        )
        disabled = SimpleNamespace(
            enabled=False,
            statistic_id="recording:match",
            insert_statistics_range=AsyncMock(),
        )
        other = SimpleNamespace(
            enabled=True,
            statistic_id="recording:other",
            insert_statistics_range=AsyncMock(),
        )
        entry.config_entry.runtime_data.recording = [matching, disabled, other]
        day = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)

        with patch("custom_components.bosch.services.find_gateway_entry", return_value=[entry]):
            await handlers["fetch_recordings_sensor_range"](
                _service_call(
                    **{
                        ATTR_DEVICE_ID: ["device1"],
                        "day": day,
                        "statistic_id": "recording:match",
                    }
                )
            )

        matching.insert_statistics_range.assert_awaited_once()
        disabled.insert_statistics_range.assert_not_awaited()
        other.insert_statistics_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_returns_gateway_values_and_handles_missing_inputs(self, handlers):
        entry = _gateway_entry()
        with patch("custom_components.bosch.services.find_gateway_entry", return_value=[entry]):
            result = await handlers[SERVICE_GET](_service_call(**{ATTR_DEVICE_ID: ["device1"], "path": "/gateway/name"}))
            missing = await handlers[SERVICE_GET](_service_call(**{ATTR_DEVICE_ID: ["device1"], "path": ""}))

        assert result == {"data": [{"value": 12}]}
        assert missing == {"data": ""}
        entry.custom_get.assert_awaited_once_with(path="/gateway/name")

        with patch("custom_components.bosch.services.find_gateway_entry", return_value=[]):
            assert await handlers[SERVICE_GET](_service_call(**{ATTR_DEVICE_ID: ["missing"], "path": "/gateway/name"})) == {"data": []}

    @pytest.mark.asyncio
    async def test_put_returns_gateway_values_and_skips_missing_inputs(self, handlers):
        entry = _gateway_entry()
        with patch("custom_components.bosch.services.find_gateway_entry", return_value=[entry]):
            result = await handlers[SERVICE_PUT_STRING](_service_call(**{ATTR_DEVICE_ID: ["device1"], "path": "/x", "value": "on"}))
            missing = await handlers[SERVICE_PUT_FLOAT](_service_call(**{ATTR_DEVICE_ID: ["device1"], "path": "/x", "value": 0}))

        assert result == {"data": [True]}
        assert missing is None
        entry.custom_put.assert_awaited_once_with(path="/x", value="on")

    @pytest.mark.asyncio
    async def test_handlers_return_without_gateway(self, handlers):
        with patch("custom_components.bosch.services.find_gateway_entry", return_value=[]):
            assert await handlers[SERVICE_UPDATE](_service_call(**{ATTR_DEVICE_ID: ["missing"]})) is None
            assert await handlers[RECORDING_SERVICE_UPDATE](_service_call(**{ATTR_DEVICE_ID: ["missing"]})) is None
            assert await handlers["fetch_recordings_sensor_range"](
                _service_call(**{ATTR_DEVICE_ID: ["missing"], "day": datetime.now(), "statistic_id": "x"})
            ) is None
            assert await handlers[SERVICE_PUT_STRING](_service_call(**{ATTR_DEVICE_ID: ["missing"], "path": "/x", "value": "x"})) is None
