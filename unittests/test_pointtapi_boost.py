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
