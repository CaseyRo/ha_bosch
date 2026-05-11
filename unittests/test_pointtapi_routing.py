"""Smoke tests for the POINTTAPI device-routing helper.

These tests synthesize paths the live coordinator would produce and assert that
_resolve_device_info routes each one to the expected device identifier.
"""
from __future__ import annotations

import pytest

from custom_components.bosch.const import DOMAIN
from custom_components.bosch.pointtapi_entities import _resolve_device_info


UUID = "101506113"


@pytest.mark.parametrize(
    ("path", "expected_id"),
    [
        # Solar
        ("/solarCircuits/sc1/collectorTemperature", f"{UUID}_solar"),
        ("/solarCircuits/sc1/totalSolarGain", f"{UUID}_solar"),
        # Hot Water Tank
        ("/dhwCircuits/dhw1/actualTemp", f"{UUID}_dhw1"),
        ("/dhwCircuits/dhw1/state", f"{UUID}_dhw1"),
        ("/dhwCircuits/dhw1/thermalDisinfect/state", f"{UUID}_dhw1"),
        # Boiler
        ("/heatSources/flameIndication", f"{UUID}_boiler"),
        ("/heatSources/numberOfStarts", f"{UUID}_boiler"),
        ("/heatSources/actualSupplyTemperature", f"{UUID}_boiler"),
        ("/system/appliance/blockingError", f"{UUID}_boiler"),
        ("/system/appliance/systemPressure", f"{UUID}_boiler"),
        ("/energy/history_total", f"{UUID}_boiler"),
        ("/energy/historyHourly_ch", f"{UUID}_boiler"),
        ("/energy/gas/annualGoal", f"{UUID}_boiler"),
        # Heating Zone (zn1 → no suffix on name)
        ("/zones/zn1/temperatureActual", f"{UUID}_zn1"),
        ("/zones/zn1/actualValvePosition", f"{UUID}_zn1"),
        ("/heatingCircuits/hc1/maxSupply", f"{UUID}_zn1"),
        ("/heatingCircuits/hc1/nightThreshold", f"{UUID}_zn1"),
        ("/heatingCircuits/hc1/roomInfluence", f"{UUID}_zn1"),
        ("/system/sensors/temperatures/outdoor_t1", f"{UUID}_zn1"),
        ("/system/sensors/humidity/indoor_h1", f"{UUID}_zn1"),
        ("/system/sensors/temperatures/offset", f"{UUID}_zn1"),
        # Gateway (fallthrough)
        ("/gateway/wifi/rssi", UUID),
        ("/gateway/versionFirmware", UUID),
        ("/gateway/update/enabled", UUID),
        ("/gateway/notificationLight/enabled", UUID),
    ],
)
def test_resolve_device_info_routes_path_to_expected_device(path: str, expected_id: str) -> None:
    info = _resolve_device_info(UUID, path)
    identifiers = set(info["identifiers"])
    assert (DOMAIN, expected_id) in identifiers, (
        f"{path} should route to {expected_id}, got {identifiers}"
    )


def test_multizone_zn2_routes_to_its_own_device() -> None:
    """Hypothetical zn2 should land on its own device, not the catch-all."""
    info = _resolve_device_info(UUID, "/zones/zn2/temperatureActual")
    assert (DOMAIN, f"{UUID}_zn2") in info["identifiers"]
    assert info["name"] == "Heating Zone zn2"


def test_zn1_single_zone_drops_suffix_in_display_name() -> None:
    """Single-zone installs get a clean 'Heating Zone' display name (no zn1 suffix)."""
    info = _resolve_device_info(UUID, "/zones/zn1/temperatureActual")
    assert info["name"] == "Heating Zone"


def test_unknown_path_falls_through_to_gateway() -> None:
    """Anything not matching a known prefix falls back to the bare gateway id."""
    info = _resolve_device_info(UUID, "/some/unrecognized/path")
    assert (DOMAIN, UUID) in info["identifiers"]
    assert info["name"] == "EasyControl Gateway"
