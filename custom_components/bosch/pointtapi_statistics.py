"""Backfill gas history from POINTTAPI /energy/history into HA long-term statistics.

Imports up to 20 days of daily gas consumption (heating, hot water, total)
so the Energy Dashboard has historical data from before the integration was set up.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def _fix_history_date(date_str: str) -> datetime | None:
    """Parse DD-MM-YYYY date from Bosch API and fix the year.

    The EasyControl API returns dates with the wrong year (e.g., 2024 instead
    of 2026). We fix by using the current year, adjusting for year boundaries.
    """
    try:
        parsed = datetime.strptime(date_str, "%d-%m-%Y")
    except (ValueError, TypeError):
        return None
    now = dt_util.now()
    # Replace year with current year
    fixed = parsed.replace(year=now.year)
    # If the resulting date is in the future, it's from last year
    if fixed.date() > now.date():
        fixed = fixed.replace(year=now.year - 1)
    # Convert to local timezone at midnight
    local_tz = dt_util.DEFAULT_TIME_ZONE
    return fixed.replace(tzinfo=local_tz)


def _build_statistics(
    entries: list[dict],
    field: str,
    statistic_id: str,
    name: str,
) -> tuple[StatisticMetaData, list[StatisticData]]:
    """Build StatisticMetaData and StatisticData list for a gas field."""
    metadata = StatisticMetaData(
        has_mean=False,
        has_sum=True,
        name=name,
        source="recorder",
        statistic_id=statistic_id,
        unit_of_measurement="kWh",
    )
    stats: list[StatisticData] = []
    running_sum = 0.0
    for entry in entries:
        dt = _fix_history_date(entry.get("d", ""))
        if dt is None:
            continue
        value = entry.get(field, 0.0) or 0.0
        running_sum += value
        stats.append(
            StatisticData(
                start=dt,
                state=value,
                sum=running_sum,
            )
        )
    return metadata, stats


async def async_backfill_gas_history(
    hass: HomeAssistant,
    coordinator_data: dict[str, Any],
    entity_id_prefix: str,
) -> None:
    """Import daily gas history into HA statistics.

    Args:
        hass: HomeAssistant instance
        coordinator_data: The coordinator.data dict containing /energy/history
        entity_id_prefix: The entity_id prefix for matching (e.g., "sensor.pointtapi")
    """
    history = coordinator_data.get("/energy/history") or {}
    entries = history.get("value") if isinstance(history, dict) else None
    if not entries or not isinstance(entries, list) or len(entries) < 2:
        _LOGGER.debug("Gas history: no entries to backfill")
        return

    # Don't include today's entry (it's still accumulating)
    backfill_entries = entries[:-1]

    fields = [
        ("gCh", f"{entity_id_prefix}_gas_heating_today", "Gas heating today"),
        ("gHw", f"{entity_id_prefix}_gas_hot_water_today", "Gas hot water today"),
    ]

    for field, statistic_id, name in fields:
        metadata, stats = _build_statistics(backfill_entries, field, statistic_id, name)
        if not stats:
            continue

        # Check if we already have statistics for this period
        existing = await hass.async_add_executor_job(
            get_last_statistics, hass, 1, statistic_id, True, {"sum"}
        )
        if existing.get(statistic_id):
            last = existing[statistic_id][0]
            last_start = last.get("start")
            last_stat = stats[-1]
            last_stat_start = last_stat["start"] if isinstance(last_stat, dict) else last_stat.start
            if last_start and last_stat_start and last_start >= last_stat_start.timestamp():
                _LOGGER.debug(
                    "Gas history backfill for %s: already up to date (last=%s)",
                    statistic_id,
                    last_start,
                )
                continue

        first_s = stats[0]["start"] if isinstance(stats[0], dict) else stats[0].start
        last_s = stats[-1]["start"] if isinstance(stats[-1], dict) else stats[-1].start
        _LOGGER.info(
            "Backfilling %d days of gas history for %s (%s to %s)",
            len(stats),
            statistic_id,
            first_s,
            last_s,
        )
        async_import_statistics(hass, metadata, stats)

    # Also backfill the total (gCh + gHw combined)
    total_id = f"{entity_id_prefix}_gas_total_today"
    total_metadata = StatisticMetaData(
        has_mean=False,
        has_sum=True,
        name="Gas total today",
        source="recorder",
        statistic_id=total_id,
        unit_of_measurement="kWh",
    )
    total_stats: list[StatisticData] = []
    running_sum = 0.0
    for entry in backfill_entries:
        dt = _fix_history_date(entry.get("d", ""))
        if dt is None:
            continue
        value = (entry.get("gCh") or 0.0) + (entry.get("gHw") or 0.0)
        running_sum += value
        total_stats.append(StatisticData(start=dt, state=value, sum=running_sum))

    if total_stats:
        existing = await hass.async_add_executor_job(
            get_last_statistics, hass, 1, total_id, True, {"sum"}
        )
        if not existing.get(total_id):
            _LOGGER.info("Backfilling %d days of total gas history", len(total_stats))
            async_import_statistics(hass, total_metadata, total_stats)
