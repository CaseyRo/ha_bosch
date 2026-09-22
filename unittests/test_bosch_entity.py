"""Unit tests for the legacy Bosch entity base classes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.bosch.bosch_entity import (
    BoschClimateWaterEntity,
    BoschEntity,
)
from custom_components.bosch.const import (
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DOMAIN,
)


class DummyEntity(BoschEntity):
    signal = "test_signal"

    @property
    def device_name(self):
        return "Test device"

    async def async_update(self):
        pass


def _bosch_object(*, parent_id=None, object_id="object1", name="Living room", min_temp=18, max_temp=25):
    obj = MagicMock()
    obj.parent_id = parent_id
    obj.id = object_id
    obj.name = name
    obj.min_temp = min_temp
    obj.max_temp = max_temp
    return obj


def _gateway():
    gateway = MagicMock()
    gateway.device_model = "Condens 7000i"
    gateway.device_type = "CT200"
    gateway.firmware = "1.2.3"
    return gateway


class TestBoschEntity:
    def test_initializes_from_kwargs_and_uses_domain_name(self):
        entity = DummyEntity(
            hass="hass",
            uuid="uuid1",
            domain_name="Sensors",
            bosch_object=_bosch_object(),
            gateway=_gateway(),
        )

        assert entity.hass == "hass"
        assert entity.bosch_object.id == "object1"
        assert entity._domain_identifier == {(DOMAIN, "uuid1_Sensors")}

    def test_parent_id_routes_entity_to_parent_device(self):
        entity = DummyEntity(
            uuid="uuid1",
            domain_name="Sensors",
            bosch_object=_bosch_object(parent_id="hc1"),
            gateway=_gateway(),
        )

        assert entity._domain_identifier == {(DOMAIN, "uuid1_hc1")}

    def test_device_info_contains_gateway_metadata_and_via_device(self):
        entity = DummyEntity(
            uuid="uuid1",
            domain_name="Sensors",
            bosch_object=_bosch_object(),
            gateway=_gateway(),
        )

        assert entity.device_info == {
            "identifiers": {(DOMAIN, "uuid1_Sensors")},
            "manufacturer": "Condens 7000i",
            "model": "CT200",
            "name": "Test device",
            "sw_version": "1.2.3",
            "hw_version": "uuid1",
            "via_device": (DOMAIN, "uuid1"),
        }

    def test_device_info_links_the_gateway_by_registry_id_on_ha_2026_8(self):
        entity = DummyEntity(
            hass="hass",
            uuid="uuid1",
            domain_name="Sensors",
            bosch_object=_bosch_object(),
            gateway=_gateway(),
        )
        entity.platform = SimpleNamespace(config_entry=SimpleNamespace(entry_id="entry-1"))

        def since_2026_8(*, via_device=None, via_device_id=None, **kwargs):
            """HA 2026.8 and later."""

        registry = SimpleNamespace(
            async_get_or_create=since_2026_8,
            async_get_device=MagicMock(return_value=SimpleNamespace(id="gateway-device")),
        )
        with patch("custom_components.bosch.pointtapi_entities.dr.async_get", return_value=registry):
            info = entity.device_info

        assert "via_device" not in info
        assert info["via_device_id"] == "gateway-device"
        assert info["identifiers"] == {(DOMAIN, "uuid1_Sensors")}
        registry.async_get_device.assert_called_once_with(identifiers={(DOMAIN, "uuid1")})

    @pytest.mark.asyncio
    async def test_async_added_to_hass_connects_signal_and_registers_removal(self):
        entity = DummyEntity(hass="hass", bosch_object=_bosch_object())
        entity.async_on_remove = MagicMock()
        connection = MagicMock()

        with patch(
            "custom_components.bosch.bosch_entity.async_dispatcher_connect",
            return_value=connection,
        ) as connect:
            await entity.async_added_to_hass()

        connect.assert_called_once_with("hass", "test_signal", entity.async_update)
        entity.async_on_remove.assert_called_once_with(connection)


class DummyClimateWaterEntity(BoschClimateWaterEntity):
    _name_prefix = "Zone"


def _climate_entity(**kwargs):
    return DummyClimateWaterEntity(
        uuid="uuid1",
        bosch_object=_bosch_object(**kwargs),
        gateway=_gateway(),
    )


class TestClimateWaterEntity:
    def test_exposes_name_and_temperature_properties(self):
        entity = _climate_entity(
            object_id="zn1",
            name="Living room",
            min_temp=17,
            max_temp=28,
        )

        assert entity.device_name == "Zone Living room"
        assert entity.temperature_unit == "°C"
        assert entity.current_temperature is None
        assert entity.target_temperature is None
        assert entity.min_temp == 17
        assert entity.max_temp == 28

    def test_uses_default_temperature_limits_when_object_values_are_falsey(self):
        entity = _climate_entity(min_temp=0, max_temp=0)

        assert entity.min_temp == DEFAULT_MIN_TEMP
        assert entity.max_temp == DEFAULT_MAX_TEMP
