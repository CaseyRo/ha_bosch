"""Tests for v0.32.0 helpers: extended on/off resolver + update timestamp parser."""
from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.bosch.pointtapi_entities import (
    _parse_update_timestamp,
    _resolve_on_off,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Legacy "on"/"off" still works (regression guard for v0.31.0 behavior)
        ("on", True),
        ("off", False),
        ("On", True),
        ("OFF", False),
        (" on ", True),
        # New "true"/"false" handling
        ("true", True),
        ("false", False),
        ("TRUE", True),
        ("False", False),
        (" true ", True),
        # Bool passthrough
        (True, True),
        (False, False),
        # Unknown/malformed → None (HA shows "unknown")
        ("yes", None),
        ("no", None),
        ("", None),
        (None, None),
        (0, None),
        (1, None),
    ],
)
def test_resolve_on_off(raw, expected) -> None:
    assert _resolve_on_off(raw) is expected


def test_parse_update_timestamp_well_formed() -> None:
    """Bosch appends a 2-letter weekday after a space; helper strips it before fromisoformat."""
    dt = _parse_update_timestamp("2026-05-11T01:02:00+02:00 Mo")
    assert isinstance(dt, datetime)
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 11
    assert dt.hour == 1
    assert dt.minute == 2
    assert dt.tzinfo is not None


def test_parse_update_timestamp_other_weekdays() -> None:
    """Helper must accept every 2-letter English abbreviation: Mo/Tu/We/Th/Fr/Sa/Su."""
    for wd in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"):
        dt = _parse_update_timestamp(f"2025-06-12T06:02:35+02:00 {wd}")
        assert dt is not None
        assert dt.year == 2025


def test_parse_update_timestamp_malformed() -> None:
    """Anything unparseable → None (entity renders as unknown)."""
    assert _parse_update_timestamp("bogus") is None
    assert _parse_update_timestamp("") is None
    assert _parse_update_timestamp(None) is None
    assert _parse_update_timestamp(12345) is None
