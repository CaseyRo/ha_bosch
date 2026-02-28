"""Shared fixtures and import setup for POINTTAPI unit tests.

The component files use relative imports (from .const, from .pointtapi_client, etc.)
so they must be imported as part of a package. We set up `custom_components.bosch`
as a shell package pointing to the repo root WITHOUT executing __init__.py
(which has heavy side effects / XMPP imports we don't need for POINTTAPI tests).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Package bootstrapping ────────────────────────────────────────────────────
# Create custom_components.bosch as a shell package so that relative imports
# (from .const, from .pointtapi_client, etc.) resolve to files in REPO_ROOT.
# We do NOT execute the real __init__.py because it imports bosch_thermostat_client
# heavily and has side effects (builtins.print patching).

_cc = ModuleType("custom_components")
_cc.__path__ = [str(REPO_ROOT / "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_bosch_pkg = ModuleType("custom_components.bosch")
_bosch_pkg.__path__ = [str(REPO_ROOT / "custom_components" / "bosch")]
_bosch_pkg.__package__ = "custom_components.bosch"
sys.modules.setdefault("custom_components.bosch", _bosch_pkg)

# Also make the sensor sub-package discoverable
_sensor_pkg = ModuleType("custom_components.bosch.sensor")
_sensor_pkg.__path__ = [str(REPO_ROOT / "custom_components" / "bosch" / "sensor")]
_sensor_pkg.__package__ = "custom_components.bosch.sensor"
sys.modules.setdefault("custom_components.bosch.sensor", _sensor_pkg)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_session():
    """Return a mock aiohttp ClientSession."""
    return AsyncMock()


@pytest.fixture
def mock_hass():
    """Return a minimal mock HomeAssistant object."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=None)
    return hass


@pytest.fixture
def mock_config_entry():
    """Return a mock ConfigEntry with POINTTAPI data."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.data = {
        "uuid": "101506113",
        "address": "101506113",
        "device_id": "101506113",
        "device_type": "EASYCONTROL",
        "http_xmpp": "pointtapi",
        "access_key": "",
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token",
        "expires_at": "2099-12-31T23:59:59+00:00",
    }
    return entry
