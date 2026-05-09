"""Data models for the Bosch integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry


@dataclass
class BoschRuntimeData:
    """Runtime data stored in config entry."""

    gateway_entry: Any
    gateway: Any = None
    coordinator: Any = None
    climate: list = field(default_factory=list)
    water_heater: list = field(default_factory=list)
    sensor: list = field(default_factory=list)
    recording: list = field(default_factory=list)
    binary_sensor: list = field(default_factory=list)
    switch: list = field(default_factory=list)
    select: list = field(default_factory=list)
    number: list = field(default_factory=list)
    interval: Any = None
    fw_interval: Any = None
    recording_interval: Any = None
    # Snapshot of entry.options taken at setup; used to suppress reloads
    # triggered by entry.data updates (POINTTAPI token refresh writes to data
    # every ~55 min, which fires the update_listener — we only want to reload
    # when the user actually changed an option).
    options_snapshot: dict = field(default_factory=dict)


type BoschConfigEntry = ConfigEntry[BoschRuntimeData]
