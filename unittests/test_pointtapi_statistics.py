"""Tests for pointtapi_statistics.py (gas-history backfill into HA statistics).

Focus is hardening: the backfill runs once at first-refresh writing to HA's
long-term statistics, so a single crash on malformed cloud data would abort the
whole import silently. These tests assert graceful degradation (skip bad rows,
no raise) as much as the happy path.

`dt_util.now` is pinned to a fixed non-leap year (2026-07-10) via an autouse
fixture so every date calculation is deterministic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.bosch import pointtapi_statistics
from custom_components.bosch.pointtapi_statistics import (
    _build_statistics,
    _fix_history_date,
    _to_float,
    async_backfill_gas_history,
)

# 2026 is intentionally a non-leap year (see the Feb-29 regression test).
FIXED_NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_now():
    """Pin dt_util.now so year-remapping and future-date logic are deterministic."""
    with patch.object(pointtapi_statistics.dt_util, "now", return_value=FIXED_NOW):
        yield


def _make_hass(existing=None, existing_side_effect=None):
    """Minimal hass whose async_add_executor_job returns fake get_last_statistics."""
    hass = MagicMock()
    if existing_side_effect is not None:
        hass.async_add_executor_job = AsyncMock(side_effect=existing_side_effect)
    else:
        hass.async_add_executor_job = AsyncMock(return_value=existing or {})
    return hass


def _history(entries):
    return {"/energy/history": {"value": entries}}


def _calls_by_id(imp):
    """Map statistic_id -> stats list from captured async_import_statistics calls."""
    return {c.args[1]["statistic_id"]: c.args[2] for c in imp.call_args_list}


# ── _to_float ────────────────────────────────────────────────────────────────


class TestToFloat:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (10.0, 10.0),
            (0, 0.0),
            (0.0, 0.0),
            (-3.5, -3.5),
            (None, 0.0),
            ("", 0.0),
            ("7.5", 7.5),      # numeric string still coerces
            ("abc", 0.0),      # non-numeric -> 0.0, no raise
            ([], 0.0),         # unexpected type -> 0.0, no raise
        ],
    )
    def test_coercion(self, value, expected):
        assert _to_float(value) == expected


# ── _fix_history_date ────────────────────────────────────────────────────────


class TestFixHistoryDate:
    def test_valid_past_date_keeps_current_year(self):
        dt = _fix_history_date("20-03-2024")  # remapped to 2026, before "now"
        assert dt is not None
        assert (dt.year, dt.month, dt.day) == (2026, 3, 20)
        assert dt.tzinfo is not None  # tz-aware

    def test_future_date_rolls_back_a_year(self):
        # 20-12 remapped to 2026 is after 2026-07-10 -> treated as last year.
        dt = _fix_history_date("20-12-2024")
        assert dt is not None
        assert (dt.year, dt.month, dt.day) == (2025, 12, 20)

    @pytest.mark.parametrize("bad", ["", "not-a-date", "31-13-2024", "2024-03-01"])
    def test_unparseable_returns_none(self, bad):
        assert _fix_history_date(bad) is None

    @pytest.mark.parametrize("bad", [None, 12345, {"d": "x"}])
    def test_non_string_returns_none(self, bad):
        assert _fix_history_date(bad) is None

    def test_feb_29_into_non_leap_year_degrades_gracefully(self):
        # 29-02-2024 is a valid leap date; remapping onto 2026 (non-leap) would
        # raise ValueError. It must be skipped (None), not crash the backfill.
        assert _fix_history_date("29-02-2024") is None


# ── _build_statistics ────────────────────────────────────────────────────────


class TestBuildStatistics:
    def test_happy_path_running_sum_and_metadata(self):
        entries = [
            {"d": "01-03-2024", "gCh": 10.0},
            {"d": "02-03-2024", "gCh": 12.5},
        ]
        meta, stats = _build_statistics(
            entries, "gCh", "sensor.pointtapi_gas_heating_today", "Gas heating today"
        )
        assert len(stats) == 2
        assert stats[0]["state"] == 10.0 and stats[0]["sum"] == 10.0
        assert stats[1]["state"] == 12.5 and stats[1]["sum"] == 22.5
        assert stats[0]["start"].tzinfo is not None
        assert meta["statistic_id"] == "sensor.pointtapi_gas_heating_today"
        assert meta["unit_of_measurement"] == "kWh"
        assert meta["has_sum"] is True and meta["has_mean"] is False
        assert meta["source"] == "recorder"

    def test_missing_field_treated_as_zero(self):
        entries = [{"d": "01-03-2024"}, {"d": "02-03-2024", "gCh": 4.0}]
        _, stats = _build_statistics(entries, "gCh", "id", "name")
        assert [s["state"] for s in stats] == [0.0, 4.0]
        assert [s["sum"] for s in stats] == [0.0, 4.0]

    def test_none_value_treated_as_zero(self):
        entries = [{"d": "01-03-2024", "gCh": None}]
        _, stats = _build_statistics(entries, "gCh", "id", "name")
        assert stats[0]["state"] == 0.0

    def test_bad_date_rows_are_skipped(self):
        entries = [
            {"d": "not-a-date", "gCh": 5.0},
            {"d": "02-03-2024", "gCh": 7.0},
        ]
        _, stats = _build_statistics(entries, "gCh", "id", "name")
        assert len(stats) == 1
        assert stats[0]["state"] == 7.0 and stats[0]["sum"] == 7.0

    def test_empty_entries_yield_no_stats_but_metadata(self):
        meta, stats = _build_statistics([], "gCh", "id", "name")
        assert stats == []
        assert meta["statistic_id"] == "id"

    def test_zero_and_negative_readings(self):
        entries = [
            {"d": "01-03-2024", "gCh": 0.0},
            {"d": "02-03-2024", "gCh": -3.0},
        ]
        _, stats = _build_statistics(entries, "gCh", "id", "name")
        assert [s["state"] for s in stats] == [0.0, -3.0]
        assert [s["sum"] for s in stats] == [0.0, -3.0]

    def test_non_numeric_reading_does_not_crash(self):
        # Regression: without _to_float, `running_sum += "abc"` raises TypeError.
        entries = [
            {"d": "01-03-2024", "gCh": "abc"},
            {"d": "02-03-2024", "gCh": 5.0},
        ]
        _, stats = _build_statistics(entries, "gCh", "id", "name")
        assert [s["state"] for s in stats] == [0.0, 5.0]
        assert [s["sum"] for s in stats] == [0.0, 5.0]


# ── async_backfill_gas_history ───────────────────────────────────────────────


class TestBackfill:
    @pytest.mark.asyncio
    async def test_happy_path_imports_three_series(self):
        data = _history([
            {"d": "01-03-2024", "gCh": 10.0, "gHw": 5.0},
            {"d": "02-03-2024", "gCh": 12.0, "gHw": 6.0},
            {"d": "03-03-2024", "gCh": 8.0, "gHw": 4.0},  # today: dropped
        ])
        hass = _make_hass({})  # no existing statistics
        with patch.object(pointtapi_statistics, "async_import_statistics") as imp:
            await async_backfill_gas_history(hass, data, "sensor.pointtapi")

        calls = _calls_by_id(imp)
        assert imp.call_count == 3
        assert calls["sensor.pointtapi_gas_heating_today"][-1]["sum"] == 22.0
        assert calls["sensor.pointtapi_gas_hot_water_today"][-1]["sum"] == 11.0
        assert calls["sensor.pointtapi_gas_total_today"][-1]["sum"] == 33.0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "data",
        [
            {},                                                  # empty
            {"/other": {"value": []}},                           # missing key
            {"/energy/history": "garbage"},                      # not a dict
            {"/energy/history": None},                           # None value
            {"/energy/history": {"value": None}},                # inner None
            {"/energy/history": {"value": {"d": "01-03-2024"}}},  # not a list
            {"/energy/history": {"value": [                       # < 2 entries
                {"d": "01-03-2024", "gCh": 1.0, "gHw": 1.0},
            ]}},
        ],
    )
    async def test_malformed_top_level_imports_nothing(self, data):
        hass = _make_hass({})
        with patch.object(pointtapi_statistics, "async_import_statistics") as imp:
            await async_backfill_gas_history(hass, data, "sensor.x")
        imp.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_bad_dates_imports_nothing(self):
        data = _history([
            {"d": "bad1", "gCh": 1.0, "gHw": 1.0},
            {"d": "bad2", "gCh": 2.0, "gHw": 2.0},
            {"d": "bad3", "gCh": 3.0, "gHw": 3.0},
        ])
        hass = _make_hass({})
        with patch.object(pointtapi_statistics, "async_import_statistics") as imp:
            await async_backfill_gas_history(hass, data, "sensor.x")
        imp.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_up_to_date_skips_import(self):
        def up_to_date(func, hass_, n, stat_id, *a):
            return {stat_id: [{"start": 9_999_999_999.0}]}  # far future ts

        data = _history([
            {"d": "01-03-2024", "gCh": 10.0, "gHw": 5.0},
            {"d": "02-03-2024", "gCh": 12.0, "gHw": 6.0},
            {"d": "03-03-2024", "gCh": 8.0, "gHw": 4.0},
        ])
        hass = _make_hass(existing_side_effect=up_to_date)
        with patch.object(pointtapi_statistics, "async_import_statistics") as imp:
            await async_backfill_gas_history(hass, data, "sensor.x")
        imp.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_fields_reimport_but_total_skipped_when_present(self):
        # Existing rows present but older than incoming -> heating/hot-water
        # re-import; the total series only backfills when absent, so it stays put.
        def stale(func, hass_, n, stat_id, *a):
            return {stat_id: [{"start": 1000.0}]}  # 1970, older than 2026 data

        data = _history([
            {"d": "01-03-2024", "gCh": 10.0, "gHw": 5.0},
            {"d": "02-03-2024", "gCh": 12.0, "gHw": 6.0},
            {"d": "03-03-2024", "gCh": 8.0, "gHw": 4.0},
        ])
        hass = _make_hass(existing_side_effect=stale)
        with patch.object(pointtapi_statistics, "async_import_statistics") as imp:
            await async_backfill_gas_history(hass, data, "sensor.x")

        calls = _calls_by_id(imp)
        assert set(calls) == {
            "sensor.x_gas_heating_today",
            "sensor.x_gas_hot_water_today",
        }
        assert "sensor.x_gas_total_today" not in calls

    @pytest.mark.asyncio
    async def test_mixed_malformed_rows_degrade_gracefully(self):
        data = _history([
            {"d": "01-03-2024", "gCh": 10.0},              # missing gHw
            {"d": "02-03-2024", "gCh": None, "gHw": 6.0},  # None gCh
            {"d": "bad", "gCh": 1.0, "gHw": 1.0},          # bad date -> skipped
            {"d": "04-03-2024", "gCh": 2.0, "gHw": 2.0},   # today: dropped
        ])
        hass = _make_hass({})
        with patch.object(pointtapi_statistics, "async_import_statistics") as imp:
            await async_backfill_gas_history(hass, data, "sensor.x")

        calls = _calls_by_id(imp)
        assert imp.call_count == 3
        assert calls["sensor.x_gas_heating_today"][-1]["sum"] == 10.0   # 10 + 0
        assert calls["sensor.x_gas_hot_water_today"][-1]["sum"] == 6.0  # 0 + 6
        assert calls["sensor.x_gas_total_today"][-1]["sum"] == 16.0     # 10 + 6

    @pytest.mark.asyncio
    async def test_non_numeric_readings_do_not_crash_total_loop(self):
        # Regression for the inline total loop: `"abc" or 0.0` -> "abc", then
        # "abc" + "xyz" raised TypeError before _to_float guarded it.
        data = _history([
            {"d": "01-03-2024", "gCh": "abc", "gHw": "xyz"},
            {"d": "02-03-2024", "gCh": 5.0, "gHw": 5.0},
            {"d": "03-03-2024", "gCh": 1.0, "gHw": 1.0},  # today: dropped
        ])
        hass = _make_hass({})
        with patch.object(pointtapi_statistics, "async_import_statistics") as imp:
            await async_backfill_gas_history(hass, data, "sensor.x")

        calls = _calls_by_id(imp)
        assert imp.call_count == 3
        assert calls["sensor.x_gas_total_today"][-1]["sum"] == 10.0  # 0 + 10
