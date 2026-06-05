"""Tests for pointtapi_coordinator.py."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.bosch.pointtapi_coordinator import (
    POINTTAPI_COORDINATOR_ROOTS,
    _fetch_paths,
)


# ── _fetch_paths ─────────────────────────────────────────────────────────────


class TestFetchPaths:
    @pytest.mark.asyncio
    async def test_fetches_root_paths(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value={"id": "/test", "value": "ok"})

        data = await _fetch_paths(client)
        assert len(data) >= len(POINTTAPI_COORDINATOR_ROOTS)

    @pytest.mark.asyncio
    async def test_follows_references(self):
        async def mock_get(path):
            if path == "/gateway":
                return {
                    "id": "/gateway",
                    "references": [{"id": "/gateway/DateTime"}],
                }
            if path == "/gateway/DateTime":
                return {"id": "/gateway/DateTime", "value": "2024-01-01"}
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/gateway" in data
        assert "/gateway/DateTime" in data

    @pytest.mark.asyncio
    async def test_follows_refenum_second_level(self):
        """refEnum references should be followed one extra level."""
        async def mock_get(path):
            if path == "/dhwCircuits/dhw1":
                return {
                    "id": "/dhwCircuits/dhw1",
                    "references": [{"id": "/dhwCircuits/dhw1/temperatureLevels"}],
                }
            if path == "/dhwCircuits/dhw1/temperatureLevels":
                return {
                    "id": "/dhwCircuits/dhw1/temperatureLevels",
                    "type": "refEnum",
                    "references": [{"id": "/dhwCircuits/dhw1/temperatureLevels/high"}],
                }
            if path == "/dhwCircuits/dhw1/temperatureLevels/high":
                return {"id": path, "value": 55}
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/dhwCircuits/dhw1/temperatureLevels/high" in data

    @pytest.mark.asyncio
    async def test_gateway_auth_failure_propagates(self):
        """Auth failure on /gateway should re-raise (token is genuinely bad)."""
        async def mock_get(path):
            if path == "/gateway":
                raise ConfigEntryAuthFailed("401")
            return {"id": path}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        with pytest.raises(ConfigEntryAuthFailed):
            await _fetch_paths(client)

    @pytest.mark.asyncio
    async def test_non_gateway_auth_failure_skipped(self):
        """Auth failure on non-gateway roots should be skipped, not re-raised."""
        call_count = 0

        async def mock_get(path):
            nonlocal call_count
            call_count += 1
            if path == "/gateway":
                return {"id": "/gateway", "value": "ok"}
            if path == "/heatingCircuits/hc1":
                raise ConfigEntryAuthFailed("403 forbidden")
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        # Should have /gateway but NOT /heatingCircuits/hc1
        assert "/gateway" in data
        assert "/heatingCircuits/hc1" not in data
        # Should have continued to other roots after the 403
        assert call_count > 2

    @pytest.mark.asyncio
    async def test_reference_auth_failure_skipped(self):
        """Auth failure on a reference path should be skipped."""
        async def mock_get(path):
            if path == "/gateway":
                return {
                    "id": "/gateway",
                    "references": [{"id": "/gateway/forbidden"}],
                }
            if path == "/gateway/forbidden":
                raise ConfigEntryAuthFailed("403")
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/gateway" in data
        assert "/gateway/forbidden" not in data

    @pytest.mark.asyncio
    async def test_non_dict_response_skipped(self):
        async def mock_get(path):
            if path == "/gateway":
                return "not a dict"
            return {"id": path, "value": "ok"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/gateway" not in data

    @pytest.mark.asyncio
    async def test_gateway_error_raises_update_failed(self):
        """Non-auth error on /gateway should raise UpdateFailed."""
        async def mock_get(path):
            if path == "/gateway":
                raise ConnectionError("network down")
            return {"id": path}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        with pytest.raises(UpdateFailed):
            await _fetch_paths(client)

    @pytest.mark.asyncio
    async def test_optional_path_error_skipped(self):
        """Non-auth error on optional paths should be skipped."""
        async def mock_get(path):
            if path == "/gateway":
                return {"id": "/gateway", "value": "ok"}
            if path == "/system/sensors":
                raise ConnectionError("timeout")
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/gateway" in data
        assert "/system/sensors" not in data


# ── Bulk steady state (discovery-then-bulk, fallback, rediscovery) ──────────


import time

from custom_components.bosch.pointtapi_coordinator import (
    HISTORY_HOURLY_PATH,
    REDISCOVERY_INTERVAL,
    PoinTTAPIDataUpdateCoordinator,
)


def _bare_coordinator(client):
    """Coordinator with only the _fetch() state, skipping HA machinery."""
    coord = PoinTTAPIDataUpdateCoordinator.__new__(PoinTTAPIDataUpdateCoordinator)
    coord._client = client
    coord._bulk_paths = []
    coord._last_discovery = 0.0
    coord._bulk_warned_at = None
    return coord


def _walk_client():
    """Client whose get() serves a small reference-walk tree."""
    async def mock_get(path):
        if path == "/gateway":
            return {"id": "/gateway", "references": [{"id": "/gateway/DateTime"}]}
        if path == "/gateway/DateTime":
            return {"id": "/gateway/DateTime", "value": "2026-01-01"}
        if path.startswith("/energy/historyHourly"):
            return {"id": HISTORY_HOURLY_PATH, "value": [{"entries": [], "next": None}]}
        return {"id": path, "value": "stub"}

    client = AsyncMock()
    client.get = AsyncMock(side_effect=mock_get)
    return client


class TestBulkSteadyState:
    @pytest.mark.asyncio
    async def test_first_fetch_runs_discovery_walk(self):
        client = _walk_client()
        coord = _bare_coordinator(client)

        data = await coord._fetch()

        client.bulk.assert_not_called()
        assert "/gateway" in data
        assert "/gateway/DateTime" in data
        # historyHourly is excluded from the bulk path set (paginated)
        assert HISTORY_HOURLY_PATH not in coord._bulk_paths
        assert "/gateway" in coord._bulk_paths
        assert coord._last_discovery > 0

    @pytest.mark.asyncio
    async def test_steady_state_uses_bulk(self):
        client = _walk_client()
        coord = _bare_coordinator(client)
        await coord._fetch()  # discovery
        client.get.reset_mock()
        client.bulk = AsyncMock(return_value={
            p: {"id": p, "value": "bulk"} for p in coord._bulk_paths
        })

        data = await coord._fetch()

        client.bulk.assert_awaited_once_with(coord._bulk_paths)
        assert data["/gateway"]["value"] == "bulk"
        # Only the paginated resource still rides sequential GETs
        for call in client.get.await_args_list:
            assert call.args[0].startswith("/energy/historyHourly")
        assert HISTORY_HOURLY_PATH in data

    @pytest.mark.asyncio
    async def test_bulk_failure_falls_back_to_walk(self):
        client = _walk_client()
        coord = _bare_coordinator(client)
        await coord._fetch()  # discovery
        client.bulk = AsyncMock(side_effect=RuntimeError("404"))

        data = await coord._fetch()

        assert "/gateway" in data  # served by the sequential walk
        assert data["/gateway"]["references"]

    @pytest.mark.asyncio
    async def test_bulk_failure_not_sticky(self):
        client = _walk_client()
        coord = _bare_coordinator(client)
        await coord._fetch()  # discovery
        client.bulk = AsyncMock(side_effect=[
            RuntimeError("hiccup"),
            {p: {"id": p, "value": "bulk"} for p in coord._bulk_paths},
        ])

        await coord._fetch()  # falls back
        data = await coord._fetch()  # bulk again

        assert client.bulk.await_count == 2
        assert data["/gateway"]["value"] == "bulk"

    @pytest.mark.asyncio
    async def test_empty_bulk_result_falls_back(self):
        client = _walk_client()
        coord = _bare_coordinator(client)
        await coord._fetch()  # discovery
        client.bulk = AsyncMock(return_value={})

        data = await coord._fetch()

        assert "/gateway" in data  # sequential walk result

    @pytest.mark.asyncio
    async def test_bulk_auth_failure_propagates(self):
        client = _walk_client()
        coord = _bare_coordinator(client)
        await coord._fetch()  # discovery
        client.bulk = AsyncMock(side_effect=ConfigEntryAuthFailed("401"))

        with pytest.raises(ConfigEntryAuthFailed):
            await coord._fetch()

    @pytest.mark.asyncio
    async def test_rediscovery_after_interval(self):
        client = _walk_client()
        coord = _bare_coordinator(client)
        await coord._fetch()  # discovery
        client.bulk = AsyncMock()
        coord._last_discovery = time.monotonic() - REDISCOVERY_INTERVAL - 1

        data = await coord._fetch()

        client.bulk.assert_not_called()  # walk ran instead
        assert "/gateway" in data

    @pytest.mark.asyncio
    async def test_bulk_data_shape_matches_get_shape(self):
        """Entities read the same {path: response} shape on both routes."""
        client = _walk_client()
        coord = _bare_coordinator(client)
        walk_data = await coord._fetch()
        client.bulk = AsyncMock(return_value={
            p: walk_data[p] for p in coord._bulk_paths
        })

        bulk_data = await coord._fetch()

        for p in coord._bulk_paths:
            assert bulk_data[p] == walk_data[p]
