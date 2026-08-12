"""Tests for v1.0.0 entities: notifications sensor + comfort controls."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory

from custom_components.bosch.pointtapi_entities import (
    POINTTAPI_BINARY_SENSOR_DESCRIPTIONS,
    POINTTAPI_NUMBER_DESCRIPTIONS,
    POINTTAPI_SELECT_DESCRIPTIONS,
    POINTTAPI_SWITCH_DESCRIPTIONS,
    BoschPoinTTAPIBinarySensorEntity,
    BoschPoinTTAPIGenericSwitchEntity,
    BoschPoinTTAPINumberEntity,
    BoschPoinTTAPISensorEntity,
    BoschPoinTTAPISelectEntity,
    _notification_entries,
    _notifications_attributes,
    _notifications_count,
    _pointtapi_open_window_binary_sensor_descriptions,
    _pointtapi_number_descriptions,
    _pointtapi_thermostat_valve_warning_binary_sensor_descriptions,
    _pointtapi_open_window_switch_descriptions,
    _pointtapi_sensor_descriptions,
    _pointtapi_zone_valve_sensor_descriptions,
)


ROOT = Path(__file__).resolve().parents[1]
STRINGS = json.loads((ROOT / "custom_components" / "bosch" / "strings.json").read_text(encoding="utf-8"))


# ── Notifications helpers (spec: pointtapi-notifications) ───────────────────


class TestNotificationsHelpers:
    def test_empty_value_list_counts_zero(self):
        data = {"/notifications": {"id": "/notifications", "value": []}}
        assert _notifications_count(data) == 0
        assert _notifications_attributes(data) == {"notifications": []}

    def test_zone_valve_sensors_are_discovered_from_zone_references(self):
        data = {
            "/zones/zn1": {
                "references": [
                    {"id": "/zones/zn1/actualValvePosition"},
                    {"id": "/zones/zn1/status"},
                ]
            },
            "/zones/zn2": {
                "references": [
                    {"id": "/zones/zn2/actualValvePosition"},
                ]
            },
            "/zones/zn10": {
                "references": [
                    {"id": "/zones/zn10/actualValvePosition"},
                ]
            },
            "/zones/zn3": {
                "references": [
                    {"id": "/zones/zn3/status"},
                ]
            },
        }

        descs = _pointtapi_zone_valve_sensor_descriptions(data)
        assert [desc.key for desc in descs] == [
            "/zones/zn1/actualValvePosition",
            "/zones/zn2/actualValvePosition",
            "/zones/zn10/actualValvePosition",
        ]
        assert descs[1].translation_key == "valve_position"

    def test_open_window_entities_are_discovered_from_zone_references(self):
        data = {
            "/zones/zn2": {
                "references": [
                    {"id": "/zones/zn2/openWindowDetection"},
                    {"id": "/zones/zn2/status"},
                ]
            },
            "/zones/zn1": {
                "references": [
                    {"id": "/zones/zn1/openWindowDetection"},
                ]
            },
            "/zones/zn10": {
                "references": [
                    {"id": "/zones/zn10/status"},
                ]
            },
        }

        switch_descs = _pointtapi_open_window_switch_descriptions(data)
        binary_descs = _pointtapi_open_window_binary_sensor_descriptions(data)

        assert [desc.key for desc in switch_descs] == [
            "/zones/zn1/openWindowDetection/enabled",
            "/zones/zn2/openWindowDetection/enabled",
        ]
        assert [desc.key for desc in binary_descs] == [
            "/zones/zn1/openWindowDetection/status",
            "/zones/zn2/openWindowDetection/status",
        ]
        assert switch_descs[0].translation_key == "open_window_detection"
        assert binary_descs[0].translation_key == "open_window_detected"

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

    def test_energy_efficiency_sensor_is_added_when_gateway_ui_references_eco(self):
        data = {
            "/gateway/ui": {
                "references": [
                    {"id": "/gateway/ui/eco"},
                ]
            }
        }
        descs = {d.key: d for d in _pointtapi_sensor_descriptions(data)}
        desc = descs["/gateway/ui/eco"]
        assert desc.translation_key == "energy_efficiency"
        assert desc.native_unit_of_measurement == "%"

    def test_energy_efficiency_sensor_routes_to_energy_performance_device(self):
        data = {
            "/gateway/ui": {
                "references": [
                    {"id": "/gateway/ui/eco"},
                ]
            },
            "/gateway/ui/eco": {"value": 70},
        }
        coord = _mock_coordinator(data, language="fr")
        desc = {d.key: d for d in _pointtapi_sensor_descriptions(data)}["/gateway/ui/eco"]
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        ent._handle_coordinator_update()

        assert ent.device_info["name"] == "Performance énergétique"
        assert (("bosch", "uuid1_energy") in ent.device_info["identifiers"])

    def test_energy_efficiency_sensor_is_not_added_without_reference(self):
        data = {
            "/gateway/ui": {
                "references": [
                    {"id": "/gateway/ui/icons"},
                ]
            }
        }
        descs = {d.key: d for d in _pointtapi_sensor_descriptions(data)}
        assert "/gateway/ui/eco" not in descs

    def test_electricity_average_sensors_are_added_when_available(self):
        data = {
            "/energy/electricity/dayAverage": {"value": 3.21, "available": "true"},
            "/energy/electricity/monthAverage": {"value": 4.56},
        }
        descs = {d.key: d for d in _pointtapi_sensor_descriptions(data)}

        assert "/energy/electricity/dayAverage" in descs
        assert "/energy/electricity/monthAverage" in descs
        assert descs["/energy/electricity/dayAverage"].translation_key == "electricity_day_average"
        assert descs["/energy/electricity/monthAverage"].translation_key == "electricity_month_average"
        assert descs["/energy/electricity/dayAverage"].native_unit_of_measurement == "kWh"
        assert descs["/energy/electricity/monthAverage"].native_unit_of_measurement == "kWh"
        assert descs["/energy/electricity/dayAverage"].device_class == "energy"
        assert descs["/energy/electricity/monthAverage"].device_class == "energy"

    def test_electricity_average_sensors_are_not_added_when_unavailable(self):
        data = {
            "/energy/electricity/dayAverage": {"value": 3.21, "available": "false"},
            # monthAverage omitted entirely
        }
        descs = {d.key: d for d in _pointtapi_sensor_descriptions(data)}

        assert "/energy/electricity/dayAverage" not in descs
        assert "/energy/electricity/monthAverage" not in descs


# ── Description tables (spec: pointtapi-comfort-controls) ───────────────────


class TestTranslationCatalog:
    def test_thermal_disinfect_switch_translation_exists(self):
        switch = STRINGS["entity"]["switch"]
        assert switch["thermal_disinfect"]["name"] == "Thermal disinfect"

    def test_dhw_heating_binary_sensor_uses_on_off_state_keys(self):
        state = STRINGS["entity"]["binary_sensor"]["dhw_heating"]["state"]
        assert state["on"] == "Heating"
        assert state["off"] == "Off"
        assert "false" not in state
        assert "true" not in state


class TestComfortControlDescriptions:
    def test_wifi_firmware_sensor_is_described(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        d = descs["/gateway/wifi/versionFirmware"]
        assert d.translation_key == "wifi_firmware_version"

    def test_zigbee_firmware_sensor_is_described_when_present(self):
        descs = {
            d.key: d
            for d in _pointtapi_sensor_descriptions(
                {"/gateway/zigbee/versionFirmware": {"value": "00.00.01"}}
            )
        }
        d = descs["/gateway/zigbee/versionFirmware"]
        assert d.translation_key == "zigbee_firmware_version"
        assert d.entity_category == EntityCategory.DIAGNOSTIC

    def test_return_temperature_sensor_is_described(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        d = descs["/heatSources/returnTemperature"]
        assert d.translation_key == "return_temperature"

    def test_annual_electricity_goal_number_is_described_when_present(self):
        descs = {
            d.key: d
            for d in _pointtapi_number_descriptions(
                {"/energy/electricity/annualGoal": {"value": 2500}}
            )
        }
        d = descs["/energy/electricity/annualGoal"]
        assert d.translation_key == "annual_electricity_goal"
        assert d.native_unit_of_measurement == "kWh"
        assert d.entity_category == EntityCategory.CONFIG

    def test_annual_gas_goal_number_is_described_when_present(self):
        descs = {
            d.key: d
            for d in _pointtapi_number_descriptions({"/energy/gas/annualGoal": {"value": 2500}})
        }
        d = descs["/energy/gas/annualGoal"]
        assert d.translation_key == "annual_gas_goal"
        assert d.native_unit_of_measurement == "kWh"
        assert d.entity_category == EntityCategory.CONFIG

    def test_annual_gas_goal_number_is_not_described_when_missing(self):
        descs = {d.key: d for d in _pointtapi_number_descriptions({})}
        assert "/energy/gas/annualGoal" not in descs

    def test_extra_dhw_switch_uses_translation_key(self):
        descs = {d.key: d for d in POINTTAPI_SWITCH_DESCRIPTIONS}
        d = descs["/dhwCircuits/dhw1/extraDhw"]
        assert d.translation_key == "extra_hot_water"

    def test_thermal_disinfect_switch_uses_translation_key(self):
        descs = {d.key: d for d in POINTTAPI_SWITCH_DESCRIPTIONS}
        d = descs["/dhwCircuits/dhw1/thermalDisinfect/state"]
        assert d.translation_key == "thermal_disinfect"

    def test_thermal_disinfect_switch_uses_on_off(self):
        descs = {d.key: d for d in POINTTAPI_SWITCH_DESCRIPTIONS}
        d = descs["/dhwCircuits/dhw1/thermalDisinfect/state"]
        assert d.on_value == "on"
        assert d.off_value == "off"

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

    def test_thermal_disinfect_last_result_keeps_the_raw_api_value(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/dhwCircuits/dhw1/thermalDisinfect/lastResult"]
        assert desc.translation_key == "thermal_disinfect_last_result"
        assert desc.value_fn is None

    def test_appliance_status_sensor_maps_0h_203_to_standby(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/system/appliance/status"]
        data = {
            "/system/appliance/displayCode": {"value": "0H"},
            "/system/appliance/causeCode": {"value": 203.0},
        }
        assert desc.translation_key == "appliance_status"
        assert desc.value_fn is not None
        assert desc.value_fn(data) == "standby_no_heat_demand"
        assert desc.attributes_fn is not None
        assert desc.attributes_fn(data) == {"display_code": "0H", "cause_code": 203}

    def test_cause_code_sensor_normalizes_float_to_int(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/system/appliance/causeCode"]
        data = {"/system/appliance/causeCode": {"value": 201.0}}
        assert desc.value_fn is not None
        assert desc.value_fn(data) == 201

    def test_heat_demand_type_sensor_is_described(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/heatSources/flameIndication"]
        assert desc.translation_key == "heat_demand_type"
        assert desc.value_fn is not None

    def test_heat_demand_type_sensor_maps_known_values(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/heatSources/flameIndication"]
        assert desc.value_fn is not None

        assert desc.value_fn({"/heatSources/flameIndication": {"value": "off"}}) == "off"
        assert desc.value_fn({"/heatSources/flameIndication": {"value": "ch"}}) == "ch"
        assert desc.value_fn({"/heatSources/flameIndication": {"value": "dhw"}}) == "dhw"

    def test_heat_demand_type_sensor_returns_none_for_unknown(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/heatSources/flameIndication"]
        assert desc.value_fn is not None
        assert desc.value_fn({"/heatSources/flameIndication": {"value": "unexpected"}}) is None

    def test_appliance_status_sensor_maps_unknown_pair_to_unknown(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/system/appliance/status"]
        data = {
            "/system/appliance/displayCode": {"value": "ZZ"},
            "/system/appliance/causeCode": {"value": 999.0},
        }
        assert desc.value_fn is not None
        assert desc.value_fn(data) == "unknown"

    def test_appliance_status_sensor_maps_flue_gas_test_variants(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/system/appliance/status"]
        assert desc.value_fn is not None

        data_a = {
            "/system/appliance/displayCode": {"value": "A"},
            "/system/appliance/causeCode": {"value": 208.0},
        }
        assert desc.value_fn(data_a) == "flue_gas_test_heat_demand"

        data_dash_a = {
            "/system/appliance/displayCode": {"value": "-A"},
            "/system/appliance/causeCode": {"value": 208.0},
        }
        assert desc.value_fn(data_dash_a) == "flue_gas_test_heat_demand"

    def test_appliance_status_sensor_maps_internal_error_cause_range(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/system/appliance/status"]
        assert desc.value_fn is not None

        data = {
            "/system/appliance/displayCode": {"value": "EA"},
            "/system/appliance/causeCode": {"value": 250.0},
        }
        assert desc.value_fn(data) == "internal_error_service_required"

    def test_appliance_status_sensor_falls_back_to_cause_when_display_missing(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/system/appliance/status"]
        assert desc.value_fn is not None

        data = {
            "/system/appliance/causeCode": {"value": 200.0},
        }
        assert desc.value_fn(data) == "heating_operation"

    def test_appliance_status_sensor_maps_no_flame_after_ignition(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/system/appliance/status"]
        assert desc.value_fn is not None

        data = {
            "/system/appliance/displayCode": {"value": "6A"},
            "/system/appliance/causeCode": {"value": 227.0},
        }
        assert desc.value_fn(data) == "no_flame_after_ignition"

    def test_appliance_status_sensor_maps_return_sensor_disconnected(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/system/appliance/status"]
        assert desc.value_fn is not None

        data = {
            "/system/appliance/displayCode": {"value": "CY"},
            "/system/appliance/causeCode": {"value": 242.0},
        }
        assert desc.value_fn(data) == "return_sensor_disconnected"

    def test_appliance_status_sensor_maps_regulation_system_test(self):
        descs = {d.key: d for d in _pointtapi_sensor_descriptions()}
        desc = descs["/system/appliance/status"]
        assert desc.value_fn is not None

        data = {
            "/system/appliance/displayCode": {"value": "5H"},
            "/system/appliance/causeCode": {"value": 268.0},
        }
        assert desc.value_fn(data) == "regulation_system_test"

    def test_thermostat_valve_diagnostics_are_discovered_from_devices_list(self):
        data = {
            "/devices/list": {
                "value": [
                    {
                        "id": 1,
                        "name": "TG9nYW1hdGljIFRDMTAw",
                        "type": "thermostat",
                        "signal": 0,
                        "battery": "unknown",
                        "zone": 1,
                        "protocol": "no_protocol",
                    },
                    {
                        "id": 2,
                        "name": "U2FsbGUgZGUgYmFpbnMtMQ==",
                        "type": "thermostat_valve",
                        "signal": 71,
                        "battery": "ok",
                        "zone": 2,
                        "protocol": "homematicip",
                    },
                    {
                        "id": 3,
                        "name": "Q3Vpc2luZS0x",
                        "type": "thermostat_valve",
                        "signal": 59,
                        "battery": "ok",
                        "zone": 3,
                        "protocol": "homematicip",
                    },
                ]
            }
        }
        descs = {d.key: d for d in _pointtapi_sensor_descriptions(data)}

        assert "/devices/list/thermostat_valve/2/signal" in descs
        assert "/devices/list/thermostat_valve/2/battery" in descs
        assert "/devices/list/thermostat_valve/2/zone" in descs
        assert "/devices/list/thermostat_valve/2/protocol" in descs
        assert "/devices/list/thermostat_valve/3/signal" in descs
        assert "/devices/list/thermostat_valve/1/signal" not in descs

    def test_zone_assigned_program_sensors_are_discovered_from_zone_paths(self):
        data = {
            "/zones/zn1/temperatureHeatingSetpoint": {"value": 20.0},
            "/zones/zn2/temperatureHeatingSetpoint": {"value": 20.0},
            "/zones/zn10/temperatureHeatingSetpoint": {"value": 20.0},
        }

        descs = {d.key: d for d in _pointtapi_sensor_descriptions(data)}
        assert "/zones/zn1/assignedProgramName" in descs
        assert "/zones/zn2/assignedProgramName" in descs
        assert "/zones/zn10/assignedProgramName" in descs
        assert descs["/zones/zn2/assignedProgramName"].translation_key == "assigned_program"

    def test_zone_assigned_program_sensor_resolves_base64_program_name(self):
        data = {
            "/zones/zn2": {"id": "/zones/zn2"},
            "/zones/zn2/temperatureHeatingSetpoint": {"value": 20.0},
            "/zones/zn2/clockProgram": {"value": 3.0},
            "/programs/pg3/name": {"value": "U2FsbGUgZGUgYmFpbnM="},
        }

        coord = _mock_coordinator(data)
        desc = next(
            d
            for d in _pointtapi_sensor_descriptions(data)
            if d.key == "/zones/zn2/assignedProgramName"
        )
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        ent._handle_coordinator_update()

        assert ent.native_value == "Salle de bains"
        assert ent.extra_state_attributes["program_id"] == "pg3"
        assert ent.extra_state_attributes["program_name_path"] == "/programs/pg3/name"

    def test_zone_assigned_program_sensor_falls_back_when_program_name_missing(self):
        data = {
            "/zones/zn2": {"id": "/zones/zn2"},
            "/zones/zn2/temperatureHeatingSetpoint": {"value": 20.0},
            "/zones/zn2/clockProgram": {"value": 3.0},
        }

        coord = _mock_coordinator(data)
        desc = next(
            d
            for d in _pointtapi_sensor_descriptions(data)
            if d.key == "/zones/zn2/assignedProgramName"
        )
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        ent._handle_coordinator_update()

        assert ent.native_value == "pg3"
        assert ent.extra_state_attributes["program_id"] == "pg3"

    def test_zone_assigned_program_sensor_returns_none_when_clock_program_missing(self):
        data = {
            "/zones/zn2": {"id": "/zones/zn2"},
            "/zones/zn2/temperatureHeatingSetpoint": {"value": 20.0},
        }

        coord = _mock_coordinator(data)
        desc = next(
            d
            for d in _pointtapi_sensor_descriptions(data)
            if d.key == "/zones/zn2/assignedProgramName"
        )
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        ent._handle_coordinator_update()

        assert ent.native_value is None
        assert ent.extra_state_attributes == {}

    def test_thermostat_valve_sensor_uses_dedicated_device_and_decoded_name(self):
        data = {
            "/devices/list": {
                "value": [
                    {
                        "id": 2,
                        "name": "U2FsbGUgZGUgYmFpbnMtMQ==",
                        "type": "thermostat_valve",
                        "signal": 71,
                        "battery": "ok",
                        "zone": 2,
                        "protocol": "homematicip",
                    }
                ]
            }
        }
        coord = _mock_coordinator(data)
        desc = next(
            d
            for d in _pointtapi_sensor_descriptions(data)
            if d.key == "/devices/list/thermostat_valve/2/signal"
        )
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        ent._handle_coordinator_update()

        assert ent.native_value == 71
        assert ent.entity_category == EntityCategory.DIAGNOSTIC
        assert ent.native_unit_of_measurement == "%"
        assert ent.icon == "mdi:signal"
        assert ent.device_info["name"] == "Thermostat valve Salle de bains-1"
        assert (("bosch", "uuid1_trv_2") in ent.device_info["identifiers"])

    def test_thermostat_valve_battery_value_is_uppercased(self):
        data = {
            "/devices/list": {
                "value": [
                    {
                        "id": 2,
                        "name": "U2FsbGUgZGUgYmFpbnMtMQ==",
                        "type": "thermostat_valve",
                        "battery": "ok",
                    }
                ]
            }
        }
        coord = _mock_coordinator(data)
        desc = next(
            d
            for d in _pointtapi_sensor_descriptions(data)
            if d.key == "/devices/list/thermostat_valve/2/battery"
        )
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        ent._handle_coordinator_update()

        assert ent.native_value == "OK"

    def test_thermostat_valve_zone_value_uses_zone_name_when_available(self):
        data = {
            "/devices/list": {
                "value": [
                    {
                        "id": 2,
                        "name": "U2FsbGUgZGUgYmFpbnMtMQ==",
                        "type": "thermostat_valve",
                        "zone": 2,
                    }
                ]
            },
            "/zones/zn2/name": {"value": "Saal"},
        }
        coord = _mock_coordinator(data)
        desc = next(
            d
            for d in _pointtapi_sensor_descriptions(data)
            if d.key == "/devices/list/thermostat_valve/2/zone"
        )
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        ent._handle_coordinator_update()

        assert ent.native_value == "Saal"

    def test_thermostat_valve_zone_value_falls_back_to_raw_zone_id(self):
        data = {
            "/devices/list": {
                "value": [
                    {
                        "id": 2,
                        "name": "U2FsbGUgZGUgYmFpbnMtMQ==",
                        "type": "thermostat_valve",
                        "zone": 2,
                    }
                ]
            }
        }
        coord = _mock_coordinator(data)
        desc = next(
            d
            for d in _pointtapi_sensor_descriptions(data)
            if d.key == "/devices/list/thermostat_valve/2/zone"
        )
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        ent._handle_coordinator_update()

        assert ent.native_value == 2

    def test_thermostat_valve_sensor_device_name_is_localized(self):
        data = {
            "/devices/list": {
                "value": [
                    {
                        "id": 2,
                        "name": "U2FsbGUgZGUgYmFpbnMtMQ==",
                        "type": "thermostat_valve",
                        "signal": 71,
                    }
                ]
            }
        }
        coord = _mock_coordinator(data, language="fr")
        desc = next(
            d
            for d in _pointtapi_sensor_descriptions(data)
            if d.key == "/devices/list/thermostat_valve/2/signal"
        )
        ent = BoschPoinTTAPISensorEntity(coord, "entry1", "uuid1", desc)
        ent.async_write_ha_state = MagicMock()

        ent._handle_coordinator_update()

        assert ent.device_info["name"] == "Vanne thermostatique Salle de bains-1"

    def test_thermostat_valve_warning_binary_sensors_are_discovered(self):
        data = {
            "/devices/list": {
                "value": [
                    {
                        "id": 2,
                        "name": "U2FsbGUgZGUgYmFpbnMtMQ==",
                        "type": "thermostat_valve",
                        "warning": 0,
                    },
                    {
                        "id": 3,
                        "name": "Q3Vpc2luZS0x",
                        "type": "thermostat_valve",
                        "warning": 1,
                    },
                    {
                        "id": 1,
                        "name": "TG9nYW1hdGljIFRDMTAw",
                        "type": "thermostat",
                        "warning": 1,
                    },
                ]
            }
        }
        descs = _pointtapi_thermostat_valve_warning_binary_sensor_descriptions(data)
        keys = [d.key for d in descs]
        assert keys == [
            "/devices/list/thermostat_valve/2/warning",
            "/devices/list/thermostat_valve/3/warning",
        ]

    def test_thermostat_valve_warning_binary_sensor_state_mapping(self):
        data = {
            "/devices/list": {
                "value": [
                    {
                        "id": 2,
                        "name": "U2FsbGUgZGUgYmFpbnMtMQ==",
                        "type": "thermostat_valve",
                        "warning": 0,
                    },
                    {
                        "id": 3,
                        "name": "Q3Vpc2luZS0x",
                        "type": "thermostat_valve",
                        "warning": 2,
                    },
                ]
            }
        }
        coord = _mock_coordinator(data)
        descs = _pointtapi_thermostat_valve_warning_binary_sensor_descriptions(data)

        d2 = next(d for d in descs if d.key.endswith("/2/warning"))
        e2 = BoschPoinTTAPIBinarySensorEntity(coord, "entry1", "uuid1", d2)
        e2.async_write_ha_state = MagicMock()
        e2._handle_coordinator_update()
        assert e2.is_on is False
        assert e2.device_info["name"] == "Thermostat valve Salle de bains-1"

        d3 = next(d for d in descs if d.key.endswith("/3/warning"))
        e3 = BoschPoinTTAPIBinarySensorEntity(coord, "entry1", "uuid1", d3)
        e3.async_write_ha_state = MagicMock()
        e3._handle_coordinator_update()
        assert e3.is_on is True


# ── Entity behavior (value mapping, availability, failure path) ─────────────


def _mock_coordinator(data, language: str | None = None):
    coord = MagicMock()
    coord.data = data
    coord.last_update_success = True
    coord.client = MagicMock()
    coord.client.put = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    if language is not None:
        coord.hass = MagicMock()
        coord.hass.config = MagicMock()
        coord.hass.config.language = language
    return coord


def _switch(coord, key):
    desc = next(d for d in POINTTAPI_SWITCH_DESCRIPTIONS if d.key == key)
    ent = BoschPoinTTAPIGenericSwitchEntity(coord, "entry1", "uuid1", desc)
    ent.async_write_ha_state = MagicMock()
    return ent


def _binary_sensor(coord, key):
    desc = next(d for d in POINTTAPI_BINARY_SENSOR_DESCRIPTIONS if d.key == key)
    ent = BoschPoinTTAPIBinarySensorEntity(coord, "entry1", "uuid1", desc)
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

    def test_dhw_binary_sensor_on_maps_to_true(self):
        coord = _mock_coordinator({"/dhwCircuits/dhw1/state": {"value": "on"}})
        ent = _binary_sensor(coord, "/dhwCircuits/dhw1/state")
        ent._handle_coordinator_update()
        assert ent.is_on is True

    def test_dhw_binary_sensor_off_maps_to_false(self):
        coord = _mock_coordinator({"/dhwCircuits/dhw1/state": {"value": "off"}})
        ent = _binary_sensor(coord, "/dhwCircuits/dhw1/state")
        ent._handle_coordinator_update()
        assert ent.is_on is False

    def test_burner_flame_uses_actual_modulation_positive_as_on(self):
        coord = _mock_coordinator(
            {
                "/heatSources/flameIndication": {"value": "dhw"},
                "/heatSources/actualModulation": {"value": 12.0},
            }
        )
        ent = _binary_sensor(coord, "/heatSources/flameIndication")
        ent._handle_coordinator_update()
        assert ent.is_on is True

    def test_burner_flame_uses_actual_modulation_zero_as_off(self):
        coord = _mock_coordinator(
            {
                "/heatSources/flameIndication": {"value": "ch"},
                "/heatSources/actualModulation": {"value": 0.0},
            }
        )
        ent = _binary_sensor(coord, "/heatSources/flameIndication")
        ent._handle_coordinator_update()
        assert ent.is_on is False

    def test_burner_flame_unknown_when_actual_modulation_missing(self):
        coord = _mock_coordinator({"/heatSources/flameIndication": {"value": "dhw"}})
        ent = _binary_sensor(coord, "/heatSources/flameIndication")
        ent._handle_coordinator_update()
        assert ent.is_on is None

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


def test_sensor_units_are_valid_for_their_device_class() -> None:
    """HA rejects a unit that isn't allowed for the description's device class.

    Guards the whole POINTTAPI sensor table at once (e.g. SIGNAL_STRENGTH only
    accepts dB/dBm, so a percentage link quality must not claim that class).
    """
    from homeassistant.components.sensor.const import DEVICE_CLASS_UNITS

    data = {
        "/devices/list": {
            "value": [
                {
                    "id": 2,
                    "name": "Q3Vpc2luZS0x",
                    "type": "thermostat_valve",
                    "signal": 71,
                    "battery": "ok",
                    "zone": 2,
                    "protocol": "homematicip",
                }
            ]
        },
        "/energy/electricity/dayAverage": {"value": 3.21},
    }

    for desc in _pointtapi_sensor_descriptions(data):
        allowed = DEVICE_CLASS_UNITS.get(desc.device_class)
        if allowed is None:
            continue
        assert desc.native_unit_of_measurement in allowed, (
            f"{desc.key}: unit {desc.native_unit_of_measurement!r} is invalid "
            f"for device class {desc.device_class}"
        )
