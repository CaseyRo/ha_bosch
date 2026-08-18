"""Tests for pointtapi_coordinator.py."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.bosch.pointtapi_coordinator import (
    POINTTAPI_COORDINATOR_ROOTS,
    _fetch_paths,
    _device_roots,
    _program_roots,
    _zone_roots,
)


# ── _fetch_paths ─────────────────────────────────────────────────────────────


class TestFetchPaths:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("root_helper, path", [
        (_zone_roots, "/zones/zn1"),
        (_program_roots, "/programs"),
        (_device_roots, "/devices"),
    ])
    async def test_root_discovery_falls_back_for_invalid_listing(
        self, root_helper, path
    ):
        client = AsyncMock()
        client.get = AsyncMock(return_value={"references": [{"id": None}, "bad"]})

        assert await root_helper(client) == [path]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("root_helper, path", [
        (_zone_roots, "/zones/zn1"),
        (_program_roots, "/programs"),
        (_device_roots, "/devices"),
    ])
    async def test_root_discovery_falls_back_on_error(self, root_helper, path):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("unavailable"))

        assert await root_helper(client) == [path]

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
    async def test_malformed_nested_reference_is_skipped(self):
        async def mock_get(path):
            if path == "/gateway":
                return {
                    "id": "/gateway",
                    "references": [{"id": "/gateway/broken"}],
                }
            if path == "/gateway/broken":
                raise ValueError("malformed resource")
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)

        assert "/gateway" in data
        assert "/gateway/broken" not in data

    @pytest.mark.asyncio
    async def test_history_hourly_error_is_skipped(self):
        async def mock_get(path):
            if path == "/energy/historyHourly":
                raise ConfigEntryAuthFailed("403")
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)

        assert "/energy/historyHourly" not in data

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

    @pytest.mark.asyncio
    async def test_program_listing_expands_roots(self):
        """/programs should expand to listed program roots, like /zones does."""

        async def mock_get(path):
            if path == "/programs":
                return {
                    "id": "/programs",
                    "type": "refEnum",
                    "references": [{"id": "/programs/A"}, {"id": "/programs/B"}],
                }
            if path in ("/programs/A", "/programs/B"):
                return {
                    "id": path,
                    "references": [{"id": f"{path}/active"}],
                }
            if path in ("/programs/A/active", "/programs/B/active"):
                return {"id": path, "value": "true"}
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/programs/A/active" in data
        assert "/programs/B/active" in data
        # Expanded roots are fetched instead of the plain listing root.
        assert "/programs" not in data

    @pytest.mark.asyncio
    async def test_program_listing_failure_falls_back_to_programs_root(self):
        """If /programs listing fails, keep legacy /programs root behavior."""

        programs_calls = 0

        async def mock_get(path):
            nonlocal programs_calls
            if path == "/programs":
                programs_calls += 1
                # First call is the listing probe, second call is fallback root fetch.
                if programs_calls == 1:
                    raise RuntimeError("404")
                return {"id": "/programs", "value": "stub"}
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/programs" in data
        assert programs_calls == 2

    @pytest.mark.asyncio
    async def test_device_listing_expands_roots(self):
        """/devices should expand to listed device roots, like /zones does."""

        async def mock_get(path):
            if path == "/devices":
                return {
                    "id": "/devices",
                    "type": "refEnum",
                    "references": [{"id": "/devices/dev1"}, {"id": "/devices/dev2"}],
                }
            if path in ("/devices/dev1", "/devices/dev2"):
                return {
                    "id": path,
                    "references": [{"id": f"{path}/rssi"}],
                }
            if path in ("/devices/dev1/rssi", "/devices/dev2/rssi"):
                return {"id": path, "value": -60}
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/devices/dev1/rssi" in data
        assert "/devices/dev2/rssi" in data
        # Expanded roots are fetched instead of the plain listing root.
        assert "/devices" not in data

    @pytest.mark.asyncio
    async def test_device_listing_failure_falls_back_to_devices_root(self):
        """If /devices listing fails, keep legacy /devices root behavior."""

        devices_calls = 0

        async def mock_get(path):
            nonlocal devices_calls
            if path == "/devices":
                devices_calls += 1
                # First call is the listing probe, second call is fallback root fetch.
                if devices_calls == 1:
                    raise RuntimeError("404")
                return {"id": "/devices", "value": "stub"}
            return {"id": path, "value": "stub"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=mock_get)

        data = await _fetch_paths(client)
        assert "/devices" in data
        assert devices_calls == 2


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


# ── historyHourly pagination (unofficial API cursor walk) ────────────────────


from custom_components.bosch.pointtapi_coordinator import _fetch_history_hourly_all


def _paging_client(pages):
    """Client serving /energy/historyHourly pages keyed by their `next` cursor.

    `pages` maps a cursor (None for the first, un-queried page) to the response
    dict that page should return. A cursor mapped to an Exception instance is
    raised instead, to exercise the mid-walk error path.
    """
    async def mock_get(path):
        if "?next=" in path:
            cursor = path.split("?next=", 1)[1]
        else:
            cursor = None
        resp = pages[cursor]
        if isinstance(resp, Exception):
            raise resp
        return resp

    client = AsyncMock()
    client.get = AsyncMock(side_effect=mock_get)
    return client


def _page(entries, nxt):
    return {"id": HISTORY_HOURLY_PATH, "value": [{"entries": entries, "next": nxt}]}


class TestHistoryHourlyPagination:
    @pytest.mark.asyncio
    async def test_walks_all_pages_and_flattens(self):
        client = _paging_client({
            None: _page([{"e": "a"}], "c1"),
            "c1": _page([{"e": "b"}], "c2"),
            "c2": _page([{"e": "c"}], None),
        })
        merged = await _fetch_history_hourly_all(client)
        assert [e["e"] for e in merged["value"][0]["entries"]] == ["a", "b", "c"]
        # Flattened result is re-shaped with a terminal cursor.
        assert merged["value"][0]["next"] is None

    @pytest.mark.asyncio
    async def test_cursor_loop_terminates(self):
        # Second page points back at its own cursor — must not loop forever.
        client = _paging_client({
            None: _page([{"e": "a"}], "c1"),
            "c1": _page([{"e": "b"}], "c1"),
        })
        merged = await _fetch_history_hourly_all(client)
        assert [e["e"] for e in merged["value"][0]["entries"]] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_pagination_capped_at_20(self):
        # Every page yields a fresh cursor forever; the cap must stop the walk.
        class Endless(dict):
            def __missing__(self, key):
                nxt = f"c{int(key[1:]) + 1}" if key and key != "None" else "c1"
                return _page([{"e": key}], nxt)
        client = _paging_client(Endless({None: _page([{"e": "seed"}], "c1")}))
        merged = await _fetch_history_hourly_all(client)
        # 1 seed page + at most 20 followed pages; the loop is bounded, not infinite.
        assert len(merged["value"][0]["entries"]) <= 21
        assert client.get.await_count <= 21

    @pytest.mark.asyncio
    async def test_mid_walk_error_returns_partial(self):
        client = _paging_client({
            None: _page([{"e": "a"}], "c1"),
            "c1": RuntimeError("page fetch blew up"),
        })
        merged = await _fetch_history_hourly_all(client)
        # Keeps what it collected before the failure instead of crashing.
        assert [e["e"] for e in merged["value"][0]["entries"]] == ["a"]

    @pytest.mark.asyncio
    async def test_first_fetch_non_dict_returns_none(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value="garbage")
        assert await _fetch_history_hourly_all(client) is None

    @pytest.mark.asyncio
    async def test_single_page_no_next(self):
        client = _paging_client({None: _page([{"e": "only"}], None)})
        merged = await _fetch_history_hourly_all(client)
        assert [e["e"] for e in merged["value"][0]["entries"]] == ["only"]


# ── _async_update_data error mapping ─────────────────────────────────────────


class TestAsyncUpdateDataMapping:
    @pytest.mark.asyncio
    async def test_success_returns_data(self):
        coord = _bare_coordinator(AsyncMock())
        coord._fetch = AsyncMock(return_value={"/gateway": {"ok": True}})
        assert await coord._async_update_data() == {"/gateway": {"ok": True}}

    @pytest.mark.asyncio
    async def test_auth_failure_propagates(self):
        coord = _bare_coordinator(AsyncMock())
        coord._fetch = AsyncMock(side_effect=ConfigEntryAuthFailed("401"))
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_update_failed_propagates(self):
        coord = _bare_coordinator(AsyncMock())
        coord._fetch = AsyncMock(side_effect=UpdateFailed("connection"))
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_timeout_becomes_update_failed(self):
        coord = _bare_coordinator(AsyncMock())
        coord._fetch = AsyncMock(side_effect=TimeoutError())
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_unexpected_error_becomes_update_failed(self):
        coord = _bare_coordinator(AsyncMock())
        coord._fetch = AsyncMock(side_effect=ValueError("surprise"))
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
