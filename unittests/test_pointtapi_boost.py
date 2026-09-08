"""Tests for v0.33.0: BoostSession + synthetic countdown value_fn."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from homeassistant.exceptions import ConfigEntryAuthFailed
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from asyncio import Lock
from custom_components.bosch.pointtapi_coordinator import PoinTTAPIDataUpdateCoordinator
from custom_components.bosch.pointtapi_entities import (
    BoschPoinTTAPIBoostSwitchEntity,
    BoostSession,
    _boost_remaining_minutes,
    _boost_zone_values,
    pointtapi_boost_zone_ids,
)
from custom_components.bosch.switch import async_setup_entry


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


def _mock_coordinator(data=None, probe_result=None):
    coord = MagicMock(spec=PoinTTAPIDataUpdateCoordinator)
    coord.hass = MagicMock()
    coord.data = data or {}
    coord.last_update_success = True
    coord.client = MagicMock()
    coord.client.put = AsyncMock()
    coord.client.get = AsyncMock(
        side_effect=lambda path: coord.data.get(path)
    )
    coord.async_request_refresh = AsyncMock()
    coord.async_refresh = AsyncMock()
    coord.boost_session = None
    coord._auto_off_cancels = {}
    coord.boost_probe_result = probe_result
    coord._boost_lock = Lock()
    coord._boost_selected_zones = None
    coord._confirm_native_active = PoinTTAPIDataUpdateCoordinator._confirm_native_active.__get__(coord, PoinTTAPIDataUpdateCoordinator)
    coord._probe_native_boost = PoinTTAPIDataUpdateCoordinator._probe_native_boost.__get__(coord, PoinTTAPIDataUpdateCoordinator)
    coord._native_boost_on = PoinTTAPIDataUpdateCoordinator._native_boost_on.__get__(coord, PoinTTAPIDataUpdateCoordinator)
    coord._native_boost_off = PoinTTAPIDataUpdateCoordinator._native_boost_off.__get__(coord, PoinTTAPIDataUpdateCoordinator)
    coord._refresh_boost_state = PoinTTAPIDataUpdateCoordinator._refresh_boost_state.__get__(coord, PoinTTAPIDataUpdateCoordinator)
    coord.async_set_zone_boost = PoinTTAPIDataUpdateCoordinator.async_set_zone_boost.__get__(coord, PoinTTAPIDataUpdateCoordinator)
    listeners = []

    def add_listener(cb):
        listeners.append(cb)
        def unsub():
            if cb in listeners:
                listeners.remove(cb)
        return unsub

    coord.async_add_listener = add_listener
    coord._listeners = listeners
    return coord


def _boost_switch(coord, zone_id=1):
    ent = BoschPoinTTAPIBoostSwitchEntity(coord, "entry1", "uuid1", zone_id)
    ent.hass = MagicMock()
    ent.async_write_ha_state = MagicMock()
    return ent


_BOOST_DATA = {
    "/heatingCircuits/hc1/boostTemperature": {"value": 24.0},
    "/heatingCircuits/hc1/boostDuration": {"value": 3.0},
    "/heatingCircuits/hc1/boostShortcut": {
        "used": "true",
        "available": "true",
        "writeable": 1,
    },
    "/heatingCircuits/hc1/boostZones": {
        "value": [{"zones": [1], "allowedZones": [1]}]
    },
    "/zones/zn1/userMode": {"value": "clock"},
}


def test_boost_switch_uses_its_heating_zone_device() -> None:
    switch = _boost_switch(_mock_coordinator(dict(_BOOST_DATA)))

    assert switch.device_info["identifiers"] == {("bosch", "uuid1_zn1")}


def test_boost_switch_unique_id_per_zone() -> None:
    coord = _mock_coordinator(dict(_BOOST_DATA))
    switch = _boost_switch(coord, zone_id=2)

    assert switch.unique_id == "entry1_pointtapi_boost_zone_2"
    assert switch.translation_key == "boost_zone"


def test_boost_switches_are_created_for_all_configured_zones() -> None:
    data = {
        "/zones/zn1/temperatureHeatingSetpoint": {"value": 20.0},
        "/zones/zn2/temperatureHeatingSetpoint": {"value": 20.0},
        "/zones/zn3/temperatureHeatingSetpoint": {"value": 20.0},
    }

    assert pointtapi_boost_zone_ids(data) == [1, 2, 3]


@pytest.mark.asyncio
async def test_switch_setup_does_not_create_boost_switches():
    coord = _mock_coordinator({
        **_BOOST_DATA,
        "/zones/zn1/temperatureHeatingSetpoint": {"value": 20.0},
        "/zones/zn2/temperatureHeatingSetpoint": {"value": 20.0},
        "/zones/zn3/temperatureHeatingSetpoint": {"value": 20.0},
    })
    entry = SimpleNamespace(
        entry_id="entry1",
        data={"http_xmpp": "pointtapi", "uuid": "uuid1"},
        runtime_data=SimpleNamespace(coordinator=coord),
    )
    add_entities = MagicMock()

    assert await async_setup_entry(MagicMock(), entry, add_entities) is True

    entities = add_entities.call_args.args[0]
    boost_switches = [
        entity for entity in entities if isinstance(entity, BoschPoinTTAPIBoostSwitchEntity)
    ]
    assert boost_switches == []


def test_boost_switch_unavailable_when_zone_is_not_allowed() -> None:
    coord = _mock_coordinator({
        **_BOOST_DATA,
        "/heatingCircuits/hc1/boostZones": {
            "value": [{"zones": [2], "allowedZones": [2]}]
        },
    })

    assert _boost_switch(coord, zone_id=1).available is False
    assert _boost_switch(coord, zone_id=2).available is True


@pytest.mark.parametrize(
    "shortcut",
    [
        {"used": "false", "available": "true", "writeable": 1},
        {"used": "true", "available": "false", "writeable": 1},
        {"used": "true", "available": "true", "writeable": 0},
    ],
)
def test_boost_switch_unavailable_when_shortcut_is_not_operable(shortcut) -> None:
    coord = _mock_coordinator({
        **_BOOST_DATA,
        "/heatingCircuits/hc1/boostShortcut": shortcut,
    })

    assert _boost_switch(coord).available is False


@pytest.mark.asyncio
async def test_unavailable_boost_switch_does_not_send_put() -> None:
    coord = _mock_coordinator({
        **_BOOST_DATA,
        "/heatingCircuits/hc1/boostShortcut": {
            "used": "true", "available": "false", "writeable": 1
        },
    })

    with pytest.raises(Exception, match="Boost is unavailable"):
        await _boost_switch(coord).async_turn_on()

    coord.client.put.assert_not_awaited()


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
        assert 1 not in coord._auto_off_cancels
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
            "custom_components.bosch.pointtapi_coordinator.async_call_later",
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
    async def test_cached_shortcut_turn_on_restarts_active_boost(self):
        """Changing zones while active turns Boost off before reapplying it."""
        coord = _mock_coordinator(
            {
                **_BOOST_DATA,
                "/heatingCircuits/hc1/boostMode": {"value": "on"},
                "/heatingCircuits/hc1/boostZones": {
                    "value": [{"zones": [1], "allowedZones": [1, 2]}]
                },
            },
            probe_result={"route": "boostShortcut", "rungs": []},
        )
        _activates_on_refresh(coord)
        ent = _boost_switch(coord, zone_id=2)

        await ent.async_turn_on()

        calls = coord.client.put.await_args_list
        assert [call.args for call in calls[:2]] == [
            ("/heatingCircuits/hc1/boostMode", "off"),
            (
                "/heatingCircuits/hc1/boostShortcut",
                [{"mode": "on", "temperature": 24.0, "duration": 3, "zones": [1, 2]}],
            ),
        ]

    @pytest.mark.asyncio
    async def test_turn_on_uses_live_zones_before_restarting_boost(self):
        """A fresh GET wins over a stale coordinator selection."""
        coord = _mock_coordinator(
            {
                **_BOOST_DATA,
                "/heatingCircuits/hc1/boostMode": {"value": "on"},
                "/heatingCircuits/hc1/boostZones": {
                    "value": [{"zones": [1], "allowedZones": [1, 2, 3]}]
                },
            },
            probe_result={"route": "boostShortcut", "rungs": []},
        )
        coord.client.get = AsyncMock(
            side_effect=[
                {"value": "on"},
                {"value": [{"zones": [1, 3], "allowedZones": [1, 2, 3]}]},
            ]
        )
        _activates_on_refresh(coord)
        ent = _boost_switch(coord, zone_id=2)

        await ent.async_turn_on()

        assert coord.client.get.await_args_list[0].args == (
            "/heatingCircuits/hc1/boostMode",
        )
        assert coord.client.get.await_args_list[1].args == (
            "/heatingCircuits/hc1/boostZones",
        )
        assert coord.client.put.await_args_list[1].args[1][0]["zones"] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_turn_on_ignores_preselected_zones_when_boost_is_off(self):
        """A dormant selection must not activate every preselected zone."""
        coord = _mock_coordinator(
            {
                **_BOOST_DATA,
                "/heatingCircuits/hc1/boostMode": {"value": "off"},
                "/heatingCircuits/hc1/boostZones": {
                    "value": [{"zones": [1, 2], "allowedZones": [1, 2, 3]}]
                },
            },
            probe_result={"route": "boostShortcut", "rungs": []},
        )
        ent = _boost_switch(coord, zone_id=3)

        await ent.async_turn_on()

        path, value = coord.client.put.await_args_list[0].args
        assert path == "/heatingCircuits/hc1/boostShortcut"
        assert value[0]["zones"] == [3]

    @pytest.mark.asyncio
    async def test_shortcut_forbidden_on_off_falls_back_to_direct_route(self):
        """A shortcut 403 on turn-off retries boostZones plus boostMode."""
        coord = _mock_coordinator(
            {
                **_BOOST_DATA,
                "/heatingCircuits/hc1/boostMode": {"value": "on"},
                "/heatingCircuits/hc1/boostZones": {
                    "value": [{"zones": [1, 2], "allowedZones": [1, 2]}]
                },
            },
            probe_result={"route": "boostShortcut", "rungs": []},
        )

        async def put(path, value):
            if path == "/heatingCircuits/hc1/boostShortcut":
                raise ConfigEntryAuthFailed("HTTP 403")
            return True

        coord.client.put = AsyncMock(side_effect=put)
        ent = _boost_switch(coord, zone_id=1)

        await ent.async_turn_off()

        paths = [call.args[0] for call in coord.client.put.await_args_list]
        assert paths == [
            "/heatingCircuits/hc1/boostShortcut",
            "/heatingCircuits/hc1/boostZones",
            "/heatingCircuits/hc1/boostMode",
        ]
        assert coord.client.put.await_args_list[-1].args[1] == "on"
        assert coord.boost_probe_result["route"] == "boostMode"

    @pytest.mark.asyncio
    async def test_shortcut_forbidden_is_not_retried_for_next_zone_turn_off(self):
        """A shortcut 403 switches subsequent partial turn-offs to direct mode."""
        coord = _mock_coordinator(
            {
                **_BOOST_DATA,
                "/heatingCircuits/hc1/boostMode": {"value": "on"},
                "/heatingCircuits/hc1/boostZones": {
                    "value": [{"zones": [1, 2, 3], "allowedZones": [1, 2, 3]}]
                },
            },
            probe_result={"route": "boostShortcut", "rungs": []},
        )

        async def put(path, value):
            if path == "/heatingCircuits/hc1/boostShortcut":
                raise ConfigEntryAuthFailed("HTTP 403")
            return True

        coord.client.put = AsyncMock(side_effect=put)
        await coord.async_set_zone_boost(1, False)
        coord.client.put.reset_mock()
        await coord.async_set_zone_boost(2, False)

        paths = [call.args[0] for call in coord.client.put.await_args_list]
        assert paths == [
            "/heatingCircuits/hc1/boostZones",
            "/heatingCircuits/hc1/boostMode",
        ]

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

    @pytest.mark.asyncio
    async def test_native_off_last_zone_uses_boost_mode_off(self):
        """Removing the last native zone turns Boost off directly."""
        coord = _mock_coordinator(
            {
                **_BOOST_DATA,
                "/heatingCircuits/hc1/boostMode": {"value": "on"},
                "/heatingCircuits/hc1/boostZones": {
                    "value": [{"zones": [1], "allowedZones": [1]}]
                },
            },
            probe_result={"route": "boostShortcut", "rungs": []},
        )
        ent = _boost_switch(coord, zone_id=1)
        ent._is_on = True

        await ent.async_turn_off()

        coord.client.put.assert_awaited_once_with(
            "/heatingCircuits/hc1/boostMode", "off"
        )
        assert ent.is_on is False

    @pytest.mark.asyncio
    async def test_native_off_keeps_other_selected_zones_active(self):
        """Turning off one zone updates the native selection without stopping others."""
        coord = _mock_coordinator(
            {
                **_BOOST_DATA,
                "/heatingCircuits/hc1/boostMode": {"value": "on"},
                "/heatingCircuits/hc1/boostZones": {
                    "value": [{"zones": [2, 3], "allowedZones": [2, 3]}]
                },
            },
            probe_result={"route": "boostShortcut", "rungs": []},
        )
        ent = _boost_switch(coord, zone_id=2)
        ent._is_on = True

        await ent.async_turn_off()

        path, value = coord.client.put.await_args_list[-1].args
        assert path == "/heatingCircuits/hc1/boostShortcut"
        assert value[0]["mode"] == "on"
        assert value[0]["zones"] == [3]
        assert coord.client.put.await_args_list[0].args[1][0]["mode"] == "off"

    @pytest.mark.asyncio
    async def test_native_off_keeps_user_selection_when_refresh_is_stale(self):
        """Successive removals must not restore zones from a stale refresh."""
        coord = _mock_coordinator(
            {
                **_BOOST_DATA,
                "/heatingCircuits/hc1/boostMode": {"value": "on"},
                "/heatingCircuits/hc1/boostZones": {
                    "value": [{"zones": [1, 2, 3], "allowedZones": [1, 2, 3]}]
                },
            },
            probe_result={"route": "boostShortcut", "rungs": []},
        )
        ent1 = _boost_switch(coord, zone_id=1)
        ent1._is_on = True
        await ent1.async_turn_off()

        coord.client.put.reset_mock()
        ent2 = _boost_switch(coord, zone_id=2)
        ent2._is_on = True
        await ent2.async_turn_off()

        payloads = [
            call.args[1][0]
            for call in coord.client.put.await_args_list
            if call.args[0] == "/heatingCircuits/hc1/boostShortcut"
        ]
        assert payloads[-1]["zones"] == [3]

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
    async def test_native_restart_shutdown_uses_boost_shortcut(self):
        """An active native Boost after restart must not restore a zone mode."""
        coord = _mock_coordinator({
            **_BOOST_DATA,
            "/heatingCircuits/hc1/boostMode": {"value": "on"},
            "/heatingCircuits/hc1/boostZones": {
                "value": [{"zones": [1, 2], "allowedZones": [1, 2]}]
            },
        })
        ent = _boost_switch(coord, zone_id=1)
        ent._handle_coordinator_update()

        await ent.async_turn_off()

        path, value = coord.client.put.await_args_list[-1].args
        assert path == "/heatingCircuits/hc1/boostShortcut"
        assert value[0]["mode"] == "on"
        assert value[0]["zones"] == [2]
        assert all(
            not call.args[0].startswith("/zones/zn1/")
            for call in coord.client.put.await_args_list
        )

    @pytest.mark.asyncio
    async def test_selected_zone_ids_come_from_boost_zones_struct(self):
        """Selected zones come from the Boost struct as integer identifiers."""
        coord = _mock_coordinator(
            {**_BOOST_DATA, "/heatingCircuits/hc1/boostZones": {
                "value": [{"zones": [1, 2], "allowedZones": [1, 2, 3]}]
            }},
        )
        assert sorted(_boost_zone_values(coord.data, "zones")) == [1, 2]
        assert sorted(_boost_zone_values({}, "zones")) == []


# ── CDI-1172: one-shot _clear_boost_flag listener deregistration ─────────────


class TestClearBoostOneShotListener:
    """HA's DataUpdateCoordinator has no async_remove_listener.

    The old code called coordinator.async_remove_listener from
    _clear_boost_flag → AttributeError on every coordinator cycle and the
    listener never unregistered. The fix stores the unsub callable returned
    by async_add_listener and calls it from the one-shot.
    """

    @pytest.mark.asyncio
    async def test_native_off_registers_one_shot_and_unsubs(self):
        coord = _mock_coordinator(
            {**_BOOST_DATA, "/heatingCircuits/hc1/boostMode": {"value": "on"}},
            probe_result={"route": "boostMode", "rungs": []},
        )
        del coord.async_remove_listener  # real coordinators don't have it
        unsub = MagicMock()
        coord.async_add_listener = MagicMock(return_value=unsub)
        ent = _boost_switch(coord)
        ent._is_on = True

        await ent.async_turn_off()

        coord.async_add_listener.assert_called_once_with(ent._clear_boost_flag)
        assert ent._clear_boost_unsub is unsub
        assert ent._boost_set_by_us is True

        # First coordinator cycle: flag cleared, listener unsubs itself
        ent._clear_boost_flag()
        assert ent._boost_set_by_us is False
        unsub.assert_called_once()
        assert ent._clear_boost_unsub is None

        # A spurious second cycle must not raise or double-unsub
        ent._clear_boost_flag()
        unsub.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_off_registers_one_shot_and_unsubs(self):
        coord = _mock_coordinator(
            dict(_BOOST_DATA),
            probe_result={"route": "fallback", "rungs": []},
        )
        del coord.async_remove_listener
        unsub = MagicMock()
        coord.async_add_listener = MagicMock(return_value=unsub)
        ent = _boost_switch(coord)
        ent._is_on = True
        ent._pre_boost_mode = "clock"

        await ent.async_turn_off()

        coord.async_add_listener.assert_called_once_with(ent._clear_boost_flag)
        assert ent._clear_boost_unsub is unsub

        ent._clear_boost_flag()
        assert ent._boost_set_by_us is False
        unsub.assert_called_once()
        assert ent._clear_boost_unsub is None

    @pytest.mark.asyncio
    async def test_pending_one_shot_not_double_registered(self):
        """A second off while a one-shot is pending must not leak a listener."""
        coord = _mock_coordinator(
            {**_BOOST_DATA, "/heatingCircuits/hc1/boostMode": {"value": "on"}},
            probe_result={"route": "boostMode", "rungs": []},
        )
        del coord.async_remove_listener
        unsub = MagicMock()
        coord.async_add_listener = MagicMock(return_value=unsub)
        ent = _boost_switch(coord)
        ent._is_on = True

        await ent.async_turn_off()
        await ent.async_turn_off()  # no cycle ran in between

        coord.async_add_listener.assert_called_once_with(ent._clear_boost_flag)
        assert ent._clear_boost_unsub is unsub


@pytest.mark.asyncio
async def test_sequential_zone_boost_in_same_poll_window():
    """Turning on zone 1 then zone 2 in one poll window preserves zone 1 in the list."""
    data = {
        **_BOOST_DATA,
        "/heatingCircuits/hc1/boostZones": {
            "value": [{"zones": [], "allowedZones": [1, 2]}]
        },
    }
    coord = _mock_coordinator(data, probe_result={"route": "boostShortcut", "rungs": []})

    async def mock_refresh():
        last_zones = (
            coord.client.put.await_args_list[-1].args[1][0]["zones"]
            if coord.client.put.await_args_list
            else []
        )
        coord.data = {
            **coord.data,
            "/heatingCircuits/hc1/boostMode": {"value": "on"},
            "/heatingCircuits/hc1/boostZones": {
                "value": [{"zones": last_zones, "allowedZones": [1, 2]}]
            },
        }

    coord.async_refresh = AsyncMock(side_effect=mock_refresh)

    ent1 = _boost_switch(coord, zone_id=1)
    ent2 = _boost_switch(coord, zone_id=2)

    await ent1.async_turn_on()
    await ent2.async_turn_on()

    # The last PUT must contain both [1, 2]
    last_put_call = coord.client.put.await_args_list[-1]
    assert last_put_call.args[0] == "/heatingCircuits/hc1/boostShortcut"
    assert last_put_call.args[1] == [{"mode": "on", "temperature": 24.0, "duration": 3, "zones": [1, 2]}]


@pytest.mark.asyncio
async def test_version_4_migrates_boost_registry_entries():
    """Migrating to v4 removes stale per-zone Boost registry entries."""
    from custom_components.bosch.__init__ import async_migrate_entry

    hass = MagicMock()
    entry = MagicMock()
    entry.version = 2
    entry.entry_id = "test_entry_123"
    entry.data = {"http_xmpp": "pointtapi"}

    stale_entity = SimpleNamespace(
        config_entry_id="test_entry_123",
        domain="switch",
        unique_id="test_entry_123_pointtapi_boost_zone_1",
        entity_id="switch.bibliotheque_thermostat_bibliotheque",
    )
    mock_er = MagicMock()
    mock_er.entities = {stale_entity.entity_id: stale_entity}
    mock_er.async_get_entity_id.return_value = "switch.heating_boost"

    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er):
        res = await async_migrate_entry(hass, entry)
        assert res is True
        mock_er.async_get_entity_id.assert_called_once_with("switch", "bosch", "test_entry_123_pointtapi_boost")
        mock_er.async_update_entity.assert_any_call(
            "switch.heating_boost", new_unique_id="test_entry_123_pointtapi_boost_zone_1"
        )
        mock_er.async_remove.assert_any_call(
            "switch.bibliotheque_thermostat_bibliotheque"
        )
        hass.config_entries.async_update_entry.assert_any_call(entry, version=4)


@pytest.mark.asyncio
async def test_version_5_clears_custom_boost_registry_names():
    """Migrating to v5 restores translated names for existing Boost switches."""
    from custom_components.bosch.__init__ import async_migrate_entry

    hass = MagicMock()
    entry = MagicMock()
    entry.version = 4
    entry.entry_id = "test_entry_123"
    entry.data = {"http_xmpp": "pointtapi"}

    entity = SimpleNamespace(
        config_entry_id="test_entry_123",
        domain="switch",
        unique_id="test_entry_123_pointtapi_boost_zone_1",
        entity_id="switch.salon_boost",
        name="Heating boost",
        original_name="Heating boost",
    )
    mock_er = MagicMock()
    mock_er.entities = {entity.entity_id: entity}

    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er):
        assert await async_migrate_entry(hass, entry) is True

    mock_er.async_update_entity.assert_any_call(
        "switch.salon_boost", name=None, original_name=None
    )
    hass.config_entries.async_update_entry.assert_any_call(entry, version=5)
    hass.config_entries.async_update_entry.assert_any_call(entry, version=6)


@pytest.mark.asyncio
async def test_version_6_moves_thermostat_child_lock_to_zone_device():
    """Migrating to v6 moves only the regular thermostat child-lock switch."""
    from custom_components.bosch.__init__ import async_migrate_entry

    hass = MagicMock()
    entry = MagicMock()
    entry.version = 5
    entry.entry_id = "test_entry_123"
    entry.data = {"http_xmpp": "pointtapi", "uuid": "uuid-1"}

    entity = SimpleNamespace(
        config_entry_id="test_entry_123",
        domain="switch",
        unique_id=(
            "test_entry_123_pointtapi_switch_devices_device1_"
            "thermostat_childLock_enabled"
        ),
        entity_id="switch.thermostat_child_lock",
        device_id="gateway-device",
    )
    mock_er = MagicMock()
    mock_er.entities = {entity.entity_id: entity}
    zone_device = SimpleNamespace(id="zone1-device")
    mock_dr = MagicMock()
    mock_dr.async_get_device.return_value = SimpleNamespace(id="gateway-device")
    mock_dr.async_get_or_create.return_value = zone_device

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr),
    ):
        assert await async_migrate_entry(hass, entry) is True

    mock_dr.async_get_or_create.assert_called_once_with(
        config_entry_id="test_entry_123",
        identifiers={("bosch", "uuid-1_zn1")},
        name="Heating Zone",
        manufacturer="Bosch",
        via_device_id="gateway-device",
    )
    mock_er.async_update_entity.assert_any_call(
        "switch.thermostat_child_lock", device_id="zone1-device"
    )
    hass.config_entries.async_update_entry.assert_any_call(entry, version=6)
    hass.config_entries.async_update_entry.assert_any_call(entry, version=7)


@pytest.mark.asyncio
async def test_version_7_clears_all_legacy_boost_registry_names():
    """Migrating to v7 clears names for old and per-zone Boost unique IDs."""
    from custom_components.bosch.__init__ import async_migrate_entry

    hass = MagicMock()
    entry = MagicMock()
    entry.version = 6
    entry.entry_id = "test_entry_123"
    entry.data = {"http_xmpp": "pointtapi"}

    entities = {
        "switch.old_boost": SimpleNamespace(
            config_entry_id="test_entry_123",
            domain="switch",
            unique_id="test_entry_123_pointtapi_boost",
            entity_id="switch.old_boost",
            name="Heating boost",
            original_name="Heating boost",
        ),
        "switch.zone_boost": SimpleNamespace(
            config_entry_id="test_entry_123",
            domain="switch",
            unique_id="test_entry_123_pointtapi_boost_zone_1",
            entity_id="switch.zone_boost",
            name="Heating boost",
            original_name="Heating boost",
        ),
    }
    mock_er = MagicMock()
    mock_er.entities = entities

    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er):
        assert await async_migrate_entry(hass, entry) is True

    assert mock_er.async_update_entity.call_count == 4
    mock_er.async_update_entity.assert_any_call(
        "switch.old_boost", name=None, original_name=None
    )
    mock_er.async_update_entity.assert_any_call(
        "switch.zone_boost", name=None, original_name=None
    )
    hass.config_entries.async_update_entry.assert_any_call(entry, version=7)
    hass.config_entries.async_update_entry.assert_any_call(entry, version=8)
