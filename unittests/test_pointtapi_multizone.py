"""Multi-zone discovery: /zones listing -> one climate entity per zone (issue #11)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bosch.climate import _pointtapi_zone_ids
from custom_components.bosch.pointtapi_coordinator import _fetch_paths
from custom_components.bosch.pointtapi_entities import (
    BoschPoinTTAPIClimateEntity,
    _decode_zone_name,
)


def _coord(data):
    coord = MagicMock()
    coord.data = data
    return coord


class TestZoneRootExpansion:
    @pytest.mark.asyncio
    async def test_all_listed_zones_walked(self):
        async def mock_get(path):
            if path == "/zones":
                return {
                    "id": "/zones",
                    "type": "refEnum",
                    "references": [{"id": "/zones/zn1"}, {"id": "/zones/zn2"}],
                }
            if path in ("/zones/zn1", "/zones/zn2"):
                return {
                    "id": path,
                    "type": "refEnum",
                    "references": [{"id": f"{path}/temperatureHeatingSetpoint"}],
                }
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/zones/zn1/temperatureHeatingSetpoint" in data
        assert "/zones/zn2/temperatureHeatingSetpoint" in data

    @pytest.mark.asyncio
    async def test_listing_failure_falls_back_to_zn1(self):
        async def mock_get(path):
            if path == "/zones":
                raise RuntimeError("404")
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/zones/zn1" in data
        assert "/zones" not in data


class TestZoneIds:
    def test_discovers_and_sorts_numerically(self):
        data = {
            f"/zones/{z}/temperatureHeatingSetpoint": {"value": 21.0}
            for z in ("zn10", "zn2", "zn1")
        }
        data["/zones/zn3/name"] = {"value": "no setpoint -> not a zone"}
        assert _pointtapi_zone_ids(data) == ["zn1", "zn2", "zn10"]

    def test_empty_data_falls_back_to_zn1(self):
        assert _pointtapi_zone_ids({}) == ["zn1"]


class TestZoneDeviceNaming:
    def test_decodes_base64_zone_name(self):
        coord = _coord({"/zones/zn2/name": {"value": "Rmx1ci9aZW50cmFsZQ=="}})
        ent = BoschPoinTTAPIClimateEntity(coord, "entry1", "uuid1", "zn2")
        assert ent.device_info["name"] == "Heating Zone Flur/Zentrale"

    def test_keeps_plain_zone_name(self):
        assert _decode_zone_name("Küche") == "Küche"

    def test_zn2_named_after_room(self):
        coord = _coord({"/zones/zn2/name": {"value": "Küche"}})
        ent = BoschPoinTTAPIClimateEntity(coord, "entry1", "uuid1", "zn2")
        assert ent.unique_id == "entry1_pointtapi_zn2"
        assert ent.device_info["name"] == "Heating Zone Küche"
        assert (("bosch", "uuid1_zn2") in ent.device_info["identifiers"])

    def test_zn1_keeps_bare_name(self):
        coord = _coord({"/zones/zn1/name": {"value": "Wohnzimmer"}})
        ent = BoschPoinTTAPIClimateEntity(coord, "entry1", "uuid1", "zn1")
        assert ent.device_info["name"] == "Heating Zone"
