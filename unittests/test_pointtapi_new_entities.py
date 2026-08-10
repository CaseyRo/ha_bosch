"""Tests for v1.0.0 entities: notifications sensor + comfort controls."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.bosch.pointtapi_entities import (
    POINTTAPI_NUMBER_DESCRIPTIONS,
    POINTTAPI_SELECT_DESCRIPTIONS,
    POINTTAPI_SWITCH_DESCRIPTIONS,
    BoschPoinTTAPIGenericSwitchEntity,
    BoschPoinTTAPINumberEntity,
    BoschPoinTTAPISelectEntity,
    _notification_entries,
    _notifications_attributes,
    _notifications_count,
    _pointtapi_sensor_descriptions,
)


# ── Notifications helpers (spec: pointtapi-notifications) ───────────────────


class TestNotificationsHelpers:
    def test_empty_value_list_counts_zero(self):
        data = {"/notifications": {"id": "/notifications", "value": []}}
        assert _notifications_count(data) == 0
        assert _notifications_attributes(data) == {"notifications": []}

    def test_values_key_also_accepted(self):
        """Cloud route on other device types uses 'values' (homecom_alt)."""
        data = {"/notifications": {"values": [{"dcd": 200}]}}
        assert _notifications_count(data) == 1
        assert _notifications_attributes(data) == {"notifications": [{"dcd": 200}]}

    def test_one_entry_passes_verbatim(self):
        entry = {"dcd": 200, "ccd": 7, "ts": "2026-06-05T10:00:00Z"}
        data = {"/notifications": {"value": [entry]}}
        assert _notifications_count(data) == 1
        assert _notifications_attributes(data)["notifications"][0] is entry

    def test_missing_path_returns_none(self):
        assert _notification_entries({}) is None
        assert _notifications_count({}) is None
        assert _notifications_attributes({}) is None

    def test_sensor_description_exists_with_availability(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/notifications"]
        assert desc.value_fn is _notifications_count
        assert desc.attributes_fn is _notifications_attributes
        assert desc.available_fn is not None
        assert desc.available_fn({}) is False
        assert desc.available_fn({"/notifications": {"value": []}}) is True


# ── Description tables (spec: pointtapi-comfort-controls) ───────────────────


class TestComfortControlDescriptions:
    def test_extra_dhw_switch_uses_translation_key(self):
        descs = {d.key: d for d in POINTTAPI_SWITCH_DESCRIPTIONS}
        d = descs["/dhwCircuits/dhw1/extraDhw"]
        assert d.translation_key == "extra_hot_water"

    def test_away_mode_switch_described(self):
        descs = {d.key: d for d in POINTTAPI_SWITCH_DESCRIPTIONS}
        d = descs["/system/awayMode/enabled"]
        assert d.on_value == "true"
        assert d.off_value == "false"

    def test_extra_dhw_switch_uses_on_off(self):
        descs = {d.key: d for d in POINTTAPI_SWITCH_DESCRIPTIONS}
        d = descs["/dhwCircuits/dhw1/extraDhw"]
        assert d.on_value == "on"
        assert d.off_value == "off"

    def test_extra_dhw_duration_constraints(self):
        """Probe-confirmed: 15–2880 minutes, step 15."""
        descs = {d.key: d for d in POINTTAPI_NUMBER_DESCRIPTIONS}
        d = descs["/dhwCircuits/dhw1/extraDhwDuration"]
        assert d.native_min_value == 15.0
        assert d.native_max_value == 2880.0
        assert d.native_step == 15.0

    def test_thermal_disinfect_time_constraints(self):
        """Probe-confirmed: minute-of-day 0–1439, step 1."""
        descs = {d.key: d for d in POINTTAPI_NUMBER_DESCRIPTIONS}
        d = descs["/dhwCircuits/dhw1/thermalDisinfect/time"]
        assert d.native_min_value == 0.0
        assert d.native_max_value == 1439.0
        assert d.native_step == 1.0

    def test_thermal_disinfect_weekday_options(self):
        descs = {d.key: d for d in POINTTAPI_SELECT_DESCRIPTIONS}
        d = descs["/dhwCircuits/dhw1/thermalDisinfect/weekDay"]
        assert d.options == ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")

    def test_thermal_disinfect_last_result_sensor_described(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        assert "/dhwCircuits/dhw1/thermalDisinfect/lastResult" in descs


# ── Entity behavior (value mapping, availability, failure path) ─────────────


def _mock_coordinator(data):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = True
    coord.client = MagicMock()
    coord.client.put = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    return coord


def _switch(coord, key):
    desc = next(d for d in POINTTAPI_SWITCH_DESCRIPTIONS if d.key == key)
    ent = BoschPoinTTAPIGenericSwitchEntity(coord, "entry1", "uuid1", desc)
    ent.async_write_ha_state = MagicMock()
    return ent


class TestEntityBehavior:
    def test_away_mode_true_maps_to_on(self):
        coord = _mock_coordinator(
            {"/system/awayMode/enabled": {"value": "true"}}
        )
        ent = _switch(coord, "/system/awayMode/enabled")
        ent._handle_coordinator_update()
        assert ent.is_on is True
        assert ent.available is True

    def test_extra_dhw_off_maps_to_off(self):
        coord = _mock_coordinator({"/dhwCircuits/dhw1/extraDhw": {"value": "off"}})
        ent = _switch(coord, "/dhwCircuits/dhw1/extraDhw")
        ent._handle_coordinator_update()
        assert ent.is_on is False
        assert ent.available is True

    def test_switch_unavailable_when_path_absent(self):
        coord = _mock_coordinator({})
        ent = _switch(coord, "/dhwCircuits/dhw1/extraDhw")
        assert ent.available is False

    @pytest.mark.asyncio
    async def test_switch_put_failure_keeps_device_state(self):
        """4xx on PUT: raise, refresh, and do NOT adopt the attempted value.

        The raise is the point — a swallowed failure made HA report the service
        call as successful while the entity silently bounced back.
        """
        coord = _mock_coordinator(
            {"/system/awayMode/enabled": {"value": "false"}}
        )
        coord.client.put = AsyncMock(side_effect=RuntimeError("400"))
        ent = _switch(coord, "/system/awayMode/enabled")
        ent._handle_coordinator_update()

        with pytest.raises(HomeAssistantError, match="400"):
            await ent.async_turn_on()

        assert ent.is_on is False  # still the device-reported state
        coord.async_request_refresh.assert_awaited()

    @pytest.mark.asyncio
    async def test_switch_put_success_sets_state_and_refreshes(self):
        coord = _mock_coordinator(
            {"/dhwCircuits/dhw1/extraDhw": {"value": "off"}}
        )
        ent = _switch(coord, "/dhwCircuits/dhw1/extraDhw")
        ent._handle_coordinator_update()

        await ent.async_turn_on()

        coord.client.put.assert_awaited_once_with("/dhwCircuits/dhw1/extraDhw", "on")
        assert ent.is_on is True
        coord.async_request_refresh.assert_awaited()

    def test_number_unavailable_when_path_absent(self):
        desc = next(
            d for d in POINTTAPI_NUMBER_DESCRIPTIONS
            if d.key == "/dhwCircuits/dhw1/extraDhwDuration"
        )
        ent = BoschPoinTTAPINumberEntity(_mock_coordinator({}), "entry1", "uuid1", desc)
        assert ent.available is False

    def test_select_unavailable_when_path_absent(self):
        desc = next(
            d for d in POINTTAPI_SELECT_DESCRIPTIONS
            if d.key == "/dhwCircuits/dhw1/thermalDisinfect/weekDay"
        )
        ent = BoschPoinTTAPISelectEntity(_mock_coordinator({}), "entry1", "uuid1", desc)
        assert ent.available is False

    def test_select_reads_weekday(self):
        desc = next(
            d for d in POINTTAPI_SELECT_DESCRIPTIONS
            if d.key == "/dhwCircuits/dhw1/thermalDisinfect/weekDay"
        )
        coord = _mock_coordinator(
            {"/dhwCircuits/dhw1/thermalDisinfect/weekDay": {"value": "Mo"}}
        )
        ent = BoschPoinTTAPISelectEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()
        ent._handle_coordinator_update()
        assert ent.current_option == "mo"
        assert ent.available is True

    def test_select_unknown_value_makes_entity_unavailable(self):
        desc = next(
            d for d in POINTTAPI_SELECT_DESCRIPTIONS
            if d.key == "/dhwCircuits/dhw1/thermalDisinfect/weekDay"
        )
        coord = _mock_coordinator(
            {"/dhwCircuits/dhw1/thermalDisinfect/weekDay": {"value": "foo"}}
        )
        ent = BoschPoinTTAPISelectEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()
        ent._handle_coordinator_update()
        assert ent.current_option is None
        assert ent.available is False

    @pytest.mark.asyncio
    async def test_select_weekday_maps_display_value_to_api_value(self):
        desc = next(
            d for d in POINTTAPI_SELECT_DESCRIPTIONS
            if d.key == "/dhwCircuits/dhw1/thermalDisinfect/weekDay"
        )
        coord = _mock_coordinator(
            {"/dhwCircuits/dhw1/thermalDisinfect/weekDay": {"value": "Mo"}}
        )
        ent = BoschPoinTTAPISelectEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        await ent.async_select_option("mo")

        coord.client.put.assert_awaited_once_with(
            "/dhwCircuits/dhw1/thermalDisinfect/weekDay", "Mo"
        )
        assert ent.current_option == "mo"
