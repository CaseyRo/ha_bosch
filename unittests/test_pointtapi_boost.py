"""Tests for v0.33.0: BoostSession + synthetic countdown value_fn."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.bosch.pointtapi_entities import (
    BoostSession,
    _boost_remaining_minutes,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def test_boost_session_just_started_full_remaining() -> None:
    """Session created now with 2h duration → ~120 minutes remaining."""
    s = BoostSession(started_at=_utcnow(), duration_hours=2.0)
    assert 119.0 < s.remaining_minutes <= 120.0


def test_boost_session_halfway_through() -> None:
    """Session started 1h ago with 2h duration → ~60 minutes remaining."""
    s = BoostSession(started_at=_utcnow() - timedelta(hours=1), duration_hours=2.0)
    assert 59.0 < s.remaining_minutes <= 60.0


def test_boost_session_expired_clamps_to_zero() -> None:
    """Session ended an hour ago → 0.0, not negative."""
    s = BoostSession(started_at=_utcnow() - timedelta(hours=3), duration_hours=2.0)
    assert s.remaining_minutes == 0.0


def test_value_fn_prefers_session_when_present() -> None:
    """When __boost_session__ is injected, the value_fn uses it."""
    s = BoostSession(started_at=_utcnow() - timedelta(minutes=30), duration_hours=2.0)
    data = {"__boost_session__": s}
    result = _boost_remaining_minutes(data)
    assert result is not None
    assert 89.0 < result <= 90.0


def test_value_fn_falls_back_to_bosch_value() -> None:
    """No session → read Bosch's reported value."""
    data = {"/heatingCircuits/hc1/boostRemainingTime": {"value": 42.5}}
    assert _boost_remaining_minutes(data) == 42.5


def test_value_fn_falls_back_to_zero_when_neither_present() -> None:
    """No session and no Bosch value → None (HA shows unknown)."""
    assert _boost_remaining_minutes({}) is None


def test_value_fn_handles_session_value_zero() -> None:
    """An expired session (remaining=0) still reports 0, not falls through."""
    s = BoostSession(started_at=_utcnow() - timedelta(hours=5), duration_hours=2.0)
    data = {"__boost_session__": s, "/heatingCircuits/hc1/boostRemainingTime": {"value": 99}}
    # Session is present, even though zero, so we trust it (don't fall through to Bosch's stale 99)
    assert _boost_remaining_minutes(data) == 0.0


# ── v1.0.0: native-first probe ladder ────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.bosch.pointtapi_entities import (
    BoschPoinTTAPIBoostSwitchEntity,
)


def _mock_coordinator(data=None, probe_result=None):
    coord = MagicMock()
    coord.data = data or {}
    coord.last_update_success = True
    coord.client = MagicMock()
    coord.client.put = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    coord.async_refresh = AsyncMock()
    coord.boost_session = None
    coord.boost_probe_result = probe_result
    return coord


def _boost_switch(coord):
    ent = BoschPoinTTAPIBoostSwitchEntity(coord, "entry1", "uuid1")
    ent.hass = MagicMock()
    ent.async_write_ha_state = MagicMock()
    return ent


_BOOST_DATA = {
    "/heatingCircuits/hc1/boostTemperature": {"value": 24.0},
    "/heatingCircuits/hc1/boostDuration": {"value": 3.0},
    "/heatingCircuits/hc1/boostZones": {
        "value": [{"zones": [1], "allowedZones": [1]}]
    },
    "/zones/zn1/userMode": {"value": "clock"},
}


def _activates_on_refresh(coord):
    """Make coord.async_refresh flip boostMode to on (device confirms)."""
    async def refresh():
        coord.data = {**coord.data, "/heatingCircuits/hc1/boostMode": {"value": "on"}}
    coord.async_refresh = AsyncMock(side_effect=refresh)


class TestNativeBoostProbe:
    @pytest.mark.asyncio
    async def test_rung1_shortcut_succeeds(self):
        """boostShortcut accepted + device confirms → native mode, no timer."""
        coord = _mock_coordinator(dict(_BOOST_DATA))
        _activates_on_refresh(coord)
        ent = _boost_switch(coord)

        await ent.async_turn_on()

        assert coord.boost_probe_result["route"] == "boostShortcut"
        assert ent.is_on is True
        assert coord.boost_session is None
        assert ent._auto_off_cancel is None
        # First PUT was the boostShortcut struct with probe-confirmed shape
        path, value = coord.client.put.await_args_list[0].args
        assert path == "/heatingCircuits/hc1/boostShortcut"
        assert value == [{"mode": "on", "temperature": 24.0, "duration": 3, "zones": [1]}]

    @pytest.mark.asyncio
    async def test_rung2_direct_succeeds_when_shortcut_403(self):
        """Shortcut 403s, boostZones+boostMode works → route boostMode."""
        coord = _mock_coordinator(dict(_BOOST_DATA))
        _activates_on_refresh(coord)

        async def put(path, value):
            if path == "/heatingCircuits/hc1/boostShortcut":
                raise RuntimeError("403")
            return True

        coord.client.put = AsyncMock(side_effect=put)
        ent = _boost_switch(coord)

        await ent.async_turn_on()

        assert coord.boost_probe_result["route"] == "boostMode"
        assert ent.is_on is True
        assert coord.boost_session is None
        rungs = coord.boost_probe_result["rungs"]
        assert rungs[0]["rung"] == "boostShortcut" and "error" in rungs[0]

    @pytest.mark.asyncio
    async def test_all_rungs_fail_falls_back_to_workaround(self):
        """Every native write 403s → v0.33 manual-mode workaround + timer."""
        coord = _mock_coordinator(dict(_BOOST_DATA))

        async def put(path, value):
            if path.startswith("/heatingCircuits/hc1/boost"):
                raise RuntimeError("403")
            return True

        coord.client.put = AsyncMock(side_effect=put)
        ent = _boost_switch(coord)

        with patch(
            "custom_components.bosch.pointtapi_entities.async_call_later",
            return_value=MagicMock(),
        ) as mock_later:
            await ent.async_turn_on()

        assert coord.boost_probe_result["route"] == "fallback"
        assert ent.is_on is True
        assert coord.boost_session is not None  # synthetic session active
        mock_later.assert_called_once()  # local auto-off timer scheduled
        # Workaround wrote manual mode + boost temperature to the zone
        paths = [c.args[0] for c in coord.client.put.await_args_list]
        assert "/zones/zn1/userMode" in paths
        assert "/zones/zn1/manualTemperatureHeating" in paths

    @pytest.mark.asyncio
    async def test_cached_route_skips_probe(self):
        """Second toggle with cached boostShortcut route probes nothing else."""
        coord = _mock_coordinator(
            dict(_BOOST_DATA),
            probe_result={"route": "boostShortcut", "rungs": []},
        )
        _activates_on_refresh(coord)
        ent = _boost_switch(coord)

        await ent.async_turn_on()

        paths = [c.args[0] for c in coord.client.put.await_args_list]
        assert paths == ["/heatingCircuits/hc1/boostShortcut"]
        assert ent.is_on is True

    @pytest.mark.asyncio
    async def test_native_off_never_touches_usermode(self):
        """Native-mode off deactivates via the route, not the zone mode."""
        coord = _mock_coordinator(
            {**_BOOST_DATA, "/heatingCircuits/hc1/boostMode": {"value": "on"}},
            probe_result={"route": "boostMode", "rungs": []},
        )
        ent = _boost_switch(coord)
        ent._is_on = True

        await ent.async_turn_off()

        paths = [c.args[0] for c in coord.client.put.await_args_list]
        assert paths == ["/heatingCircuits/hc1/boostMode"]
        assert coord.client.put.await_args_list[0].args[1] == "off"
        assert ent.is_on is False

    @pytest.mark.asyncio
    async def test_fallback_off_restores_usermode(self):
        """Fallback-mode off (session active) restores the prior userMode."""
        coord = _mock_coordinator(
            dict(_BOOST_DATA),
            probe_result={"route": "fallback", "rungs": []},
        )
        ent = _boost_switch(coord)
        ent._is_on = True
        ent._pre_boost_mode = "clock"

        await ent.async_turn_off()

        paths = [c.args[0] for c in coord.client.put.await_args_list]
        assert paths == ["/zones/zn1/userMode"]
        assert coord.client.put.await_args_list[0].args[1] == "clock"

    @pytest.mark.asyncio
    async def test_native_restart_recovery_state_from_device(self):
        """After restart (no probe cache) the switch derives state from boostMode."""
        coord = _mock_coordinator(
            {**_BOOST_DATA, "/heatingCircuits/hc1/boostMode": {"value": "on"}}
        )
        ent = _boost_switch(coord)

        ent._handle_coordinator_update()

        assert ent.is_on is True  # device-reported native boost survives restart

    @pytest.mark.asyncio
    async def test_probe_zone_ids_from_boost_zones_struct(self):
        """Zone ids come from the boostZones struct (integers, not 'zn1')."""
        coord = _mock_coordinator(
            {**_BOOST_DATA, "/heatingCircuits/hc1/boostZones": {
                "value": [{"zones": [1, 2], "allowedZones": [1, 2, 3]}]
            }},
        )
        ent = _boost_switch(coord)
        assert ent._boost_zone_ids(coord.data) == [1, 2]
        # Default when struct absent
        assert ent._boost_zone_ids({}) == [1]
