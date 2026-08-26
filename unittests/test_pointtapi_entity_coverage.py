"""Focused coverage tests for POINTTAPI entity helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.components.climate.const import HVACAction
from homeassistant.exceptions import HomeAssistantError

from custom_components.bosch.pointtapi_entities import (
    BoostSession,
    _appliance_status_attributes,
    _appliance_status_available,
    _appliance_status_state,
    _burner_flame_state,
    _coerce_int_like,
    _current_hour_entry,
    _decode_zone_name,
    _device_name,
    _gateway_installed_version,
    _gateway_latest_version,
    _gas_ch_today,
    _gas_ch_hourly,
    _gas_hw_today,
    _gas_total_hourly,
    _gas_total_today,
    _heat_demand_type_state,
    _normalize_language,
    _normalize_select_option,
    _open_window_status,
    _parse_update_timestamp,
    _path_available,
    _program_names_by_index,
    _resolve_device_info,
    _resolve_on_off,
    _thermostat_valve_battery,
    _thermostat_valve_child_lock_path,
    _thermostat_valve_device_path_from_data,
    _thermostat_valve_id_from_path,
    _thermostat_valve_name,
    _thermostat_valve_protocol_name,
    _thermostat_valve_rows,
    _thermostat_valve_warning_state,
    _thermostat_valve_zone_name,
    _today_hourly_entries,
    _zone_assigned_program_name,
    _zone_clock_program_id,
    _zone_id_from_path,
    _zone_ids_with_reference,
    _zone_room_suffix,
    _zone_program_current_option,
    _zone_program_option_map,
    _zone_program_write_value,
    _open_window_status,
    _select_state_key,
    pointtapi_zone_ids,
)


def _coord(data):
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.hass = MagicMock()
    coordinator.hass.config.language = "fr-FR"
    return coordinator


def _val(path, value):
    return {path: {"value": value}}


class TestEntityHelperConversions:
    @pytest.mark.parametrize(
        "language, expected",
        [(None, "en"), ("", "en"), ("fr-FR", "fr"), ("de_DE", "de"), ("xx", "en")],
    )
    def test_normalize_language(self, language, expected):
        assert _normalize_language(language) == expected

    def test_device_names_and_zone_path_routing(self):
        assert _device_name("boiler", "fr") == "Chaudière"
        assert _device_name("unknown", "en") == "unknown"
        assert _zone_id_from_path("/zones/zn3/name") == "zn3"
        assert _zone_id_from_path("/heatingCircuits/hc2/status") == "zn2"
        assert _zone_id_from_path("/other") == "zn1"

    @pytest.mark.parametrize(
        "path, kind, expected_name",
        [
            ("/gateway/versionFirmware", None, "EasyControl Gateway"),
            ("/heatSources/actualModulation", None, "Boiler"),
            ("/dhwCircuits/dhw1/actualTemp", None, "Hot Water Tank"),
            ("/solarCircuits/sc1/pumpModulation", None, "Solar"),
            ("/zones/zn2/status", None, "Heating Zone zn2"),
            ("/gateway", "thermal_disinfect", "Hot Water Tank"),
            ("/gateway", "annual_gas_goal", "Energy performance"),
        ],
    )
    def test_resolve_device_info_routes_paths_and_kinds(self, path, kind, expected_name):
        info = _resolve_device_info("uuid1", path, kind=kind, language="en")
        assert info["name"] == expected_name
        if expected_name == "EasyControl Gateway":
            assert "via_device" not in info
        else:
            assert info["via_device"] == ("bosch", "uuid1")

    def test_resolve_device_info_uses_room_name_for_multi_zone(self):
        data = {
            "/zones/zn1/temperatureHeatingSetpoint": {"value": 20},
            "/zones/zn2/temperatureHeatingSetpoint": {"value": 20},
            "/zones/zn2/name": {"value": "TG91bmdl"},
        }
        info = _resolve_device_info("uuid1", "/zones/zn2/status", data=data)
        assert info["name"] == "Heating Zone Lounge"

    def test_decode_and_path_availability_are_defensive(self):
        assert _decode_zone_name("U2Fsb24=") == "Salon"
        assert _decode_zone_name("not-base64") == "not-base64"
        assert _decode_zone_name(12) is None
        assert _path_available({}, "/missing") is False
        assert _path_available({"/x": {"available": "false"}}, "/x") is False
        assert _path_available({"/x": {"available": "true"}}, "/x") is True

    def test_zone_discovery_and_room_suffix_ignore_unrelated_payloads(self):
        data = {
            "/zones/zn10": {"references": [{"id": "/zones/zn10/status"}]},
            "/zones/zn2": {"references": [{"id": "/zones/zn2/actualValvePosition"}]},
            "/zones/not-a-zone": {"references": [{"id": "/zones/not-a-zone/actualValvePosition"}]},
            "/other": "malformed",
        }
        assert _zone_ids_with_reference(data, "actualValvePosition") == ["zn2"]
        assert pointtapi_zone_ids({}) == ["zn1"]
        assert _zone_room_suffix(data, "zn1") is None

    @pytest.mark.parametrize(
        "value, expected",
        [(True, True), (False, False), (1, True), (0, False), (" YES ", True), ("off", False), ("unknown", None), (None, None)],
    )
    def test_resolve_on_off(self, value, expected):
        assert _resolve_on_off(value) is expected

    @pytest.mark.parametrize("value, expected", [(None, None), (True, None), (3.8, 3), ("4.2", 4), ("bad", None)])
    def test_coerce_int_like(self, value, expected):
        assert _coerce_int_like(value) == expected


class TestThermostatValveHelpers:
    def test_valve_rows_sort_and_normalize_fields(self):
        data = {
            "/devices/list": {
                "value": [
                    {"id": "10", "type": "thermostat_valve", "name": "bad", "battery": "low", "zone": 2, "protocol": " homematicip "},
                    {"id": 2, "type": "thermostat_valve", "name": "VmFsdmUy", "battery": "ok", "zone": 1, "protocol": "other"},
                    {"id": "invalid", "type": "thermostat_valve"},
                    {"id": 3, "type": "other"},
                ]
            },
            "/zones/zn1/name": {"value": "U2Fsb24="},
        }
        rows = _thermostat_valve_rows(data)
        assert [row["id"] for row in rows] == [2, "10", "invalid"]
        assert _thermostat_valve_name(rows[0]) == "Valve2"
        assert _thermostat_valve_name({"id": 10}) == "#10"
        assert _thermostat_valve_battery(data, 2) == "OK"
        assert _thermostat_valve_battery(data, 10) == "low"
        assert _thermostat_valve_zone_name(data, 2) == "Salon"
        assert _thermostat_valve_protocol_name(data, 2) == "other"

    def test_valve_path_helpers_cover_layouts_and_nested_lock(self):
        assert _thermostat_valve_id_from_path("/devices/list/thermostat_valve/7/name") == 7
        assert _thermostat_valve_id_from_path("/devices/device12/etrv/name") == 12
        assert _thermostat_valve_id_from_path("/other") is None
        data = {"/devices/device7/etrv/temperatureActual": {"value": 20}}
        assert _thermostat_valve_device_path_from_data(data, 7, "etrv/temperatureActual") == "/devices/device7/etrv/temperatureActual"
        nested = {
            "/devices/list": {"value": [{"id": 7, "type": "thermostat_valve", "childLock": {"enabled": True}}]}
        }
        assert _thermostat_valve_child_lock_path(nested, 7) is None
        assert _thermostat_valve_device_path_from_data({}, 7, "etrv/name") is None
        assert _thermostat_valve_battery(nested, 99) is None
        assert _thermostat_valve_zone_name(nested, 7) is None
        assert _thermostat_valve_protocol_name(nested, 7) is None

        referenced = {
            "/devices/device7/etrv/childLock/refEnum": {
                "references": [{"id": "/devices/device7/etrv/childLock/enabled"}]
            },
            "/devices/device7/etrv/childLock/enabled": {
                "type": "stringValue",
                "writeable": 1,
                "used": "true",
                "recordable": 0,
                "available": "true",
                "value": "true",
            },
        }
        assert _thermostat_valve_child_lock_path(referenced, 7).endswith("/enabled")

    @pytest.mark.parametrize("warning, expected", [(0, False), (1, True), ("bad", True), (None, None)])
    def test_valve_warning_state(self, warning, expected):
        data = {"/devices/list": {"value": [{"id": 7, "type": "thermostat_valve", "warning": warning}]}}
        assert _thermostat_valve_warning_state(data, 7) is expected


class TestGasAndDiagnostics:
    def test_gas_helpers_support_flat_and_nested_history(self):
        now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
        data = {
            "/energy/historyHourly": {
                "value": [{"entries": [{"d": "10-07-2024", "h": "11", "gCh": 1.25, "gHw": 0.5}, {"d": "10-07-2024", "h": "12", "gCh": 2.0}]}]
            }
        }
        with patch("custom_components.bosch.pointtapi_entities.dt_util.now", return_value=now):
            assert len(_today_hourly_entries(data)) == 2
            assert _gas_ch_today(data) == 3.25
            assert _gas_hw_today(data) == 0.5
            assert _gas_total_today(data) == 3.75
            assert _gas_ch_hourly(data) == 2.0
            assert _gas_total_hourly(data) == 2.0

    def test_gas_helpers_return_none_for_missing_history(self):
        assert _today_hourly_entries({}) == []
        assert _gas_ch_today({}) is None
        assert _current_hour_entry({}) is None

    def test_gas_helpers_support_flat_history_and_latest_hour_fallback(self):
        now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
        data = {
            "/energy/historyHourly": {
                "value": [
                    {"d": "10-07-2024", "h": "bad", "gCh": 1.0, "gHw": 2.0},
                    {"d": "10-07-2024", "h": "10", "gCh": 3.0, "gHw": 4.0},
                ]
            }
        }
        with patch("custom_components.bosch.pointtapi_entities.dt_util.now", return_value=now):
            assert _current_hour_entry(data)["h"] == "10"
            assert _gas_hw_today(data) == 6.0

    def test_open_window_and_select_normalizers(self):
        assert _open_window_status({"/zones/zn1/openWindowDetection/status": {"value": "open"}}, "/zones/zn1/openWindowDetection/status") is True
        assert _open_window_status({}, "/missing") is None
        assert _select_state_key("Some Label") == "some_label"
        assert _normalize_select_option("some_label", {"some_label"}) == "some_label"
        assert _normalize_select_option("unknown", {"some_label"}) is None

    @pytest.mark.parametrize("raw, expected", [("off", "off"), ("ch", "ch"), ("dhw", "dhw"), ("unknown", None), (3, None)])
    def test_heat_demand_and_flame_helpers(self, raw, expected):
        assert _heat_demand_type_state(_val("/heatSources/flameIndication", raw)) == expected
        flame = _burner_flame_state(_val("/heatSources/actualModulation", raw))
        assert flame is (True if raw == 3 else None)

    def test_appliance_status_mapping_and_attributes(self):
        data = {
            "/system/appliance/displayCode": {"value": "-H"},
            "/system/appliance/causeCode": {"value": 200},
        }
        assert _appliance_status_state(data) == "heating_operation"
        assert _appliance_status_attributes(data) == {"display_code": "-H", "cause_code": 200}
        assert _appliance_status_available(data) is True
        assert _appliance_status_state({}) is None

        fault = {
            "/system/appliance/displayCode": {"value": "bad"},
            "/system/appliance/blockingError": {"value": "true"},
        }
        assert _appliance_status_state(fault) == "blocking_fault_code_active"

        assert _appliance_status_state({"/system/appliance/causeCode": {"value": 250}}) == "internal_error_service_required"
        assert _appliance_status_state({"/system/appliance/causeCode": {"value": 999}}) == "unknown"
        attrs = _appliance_status_attributes(
            {
                "/system/appliance/blockingError": {"value": 358},
                "/system/appliance/lockingError": {"value": "false"},
            }
        )
        assert attrs["blocking_code"] == 358


class TestProgramsAndVersions:
    def test_program_helpers_decode_names_and_disambiguate_duplicates(self):
        data = {
            "/zones/zn1/temperatureHeatingSetpoint": {"value": 20},
            "/zones/zn1/clockProgram": {"value": 2},
            "/programs/pg1/name": {"value": "U2Fsb24="},
            "/programs/pg2/name": {"value": "U2Fsb24="},
            "/programs/pg3/name": {"value": ""},
        }
        assert _program_names_by_index(data) == {1: "Salon", 2: "Salon", 3: "pg3"}
        assert _zone_clock_program_id(data, "zn1") == "pg2"
        assert _zone_assigned_program_name(data, "zn1") == "Salon"
        option_map = _zone_program_option_map(data)
        assert option_map == {"Salon": 1, "Salon (pg2)": 2, "pg3": 3}
        assert _zone_program_current_option(data, "zn1") == "Salon (pg2)"
        assert _zone_program_write_value("pg3", data) == 3
        with pytest.raises(HomeAssistantError):
            _zone_program_write_value("missing", data)

    def test_firmware_version_helpers(self):
        installed = _val("/gateway/versionFirmware", "1.2.3")
        assert _gateway_installed_version(installed) == "1.2.3"
        assert _gateway_latest_version(installed) == "1.2.3"
        update = {**installed, **_val("/gateway/update/state", "available")}
        assert _gateway_latest_version(update) == "1.2.3 (update available)"
        assert _gateway_latest_version({}) is None

    @pytest.mark.parametrize("raw, expected", [("2026-05-11T01:02:00+02:00 Mo", True), ("bad", False), (None, False)])
    def test_update_timestamp_parser(self, raw, expected):
        assert (_parse_update_timestamp(raw) is not None) is expected

    def test_boost_session_countdown_is_never_negative(self):
        session = BoostSession(datetime.now(timezone.utc), 0)
        with patch("custom_components.bosch.pointtapi_entities.dt_util.utcnow", return_value=datetime.now(timezone.utc)):
            assert session.remaining_minutes == 0.0
