"""Solar device removal must not fire on a failed or empty refresh.

Removing the solar device deletes every entity registry entry on it —
entity_ids, customisations and history association are gone and cannot be
recovered. The coordinator swallows per-path fetch failures, so an absent
/solarCircuits key means "we did not see solar this cycle", not "this
appliance has no solar".
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.bosch.const import CONF_PROTOCOL, POINTTAPI
from custom_components.bosch.sensor import async_setup_entry


def _entry(coordinator):
    return SimpleNamespace(
        data={CONF_PROTOCOL: POINTTAPI, "uuid": "uuid1"},
        options={},
        entry_id="entry1",
        runtime_data=SimpleNamespace(coordinator=coordinator, gateway=None),
    )


async def _run(coordinator):
    hass = MagicMock()
    hass.data = {}
    with (
        patch(
            "custom_components.bosch.sensor._remove_solar_registry_entries"
        ) as remove,
        patch(
            "custom_components.bosch.sensor._pointtapi_sensor_descriptions",
            return_value=[],
        ),
        patch("homeassistant.helpers.event.async_call_later"),
    ):
        await async_setup_entry(hass, _entry(coordinator), MagicMock())
    return remove


class TestSolarRemovalGuard:
    @pytest.mark.asyncio
    async def test_failed_refresh_does_not_remove_solar(self):
        # A timeout mid-poll: last_update_success is False and the cached data
        # is whatever survived. Deleting the user's solar device here is wrong.
        coordinator = MagicMock(data={"/gateway": {"id": "/gateway"}})
        coordinator.last_update_success = False
        assert (await _run(coordinator)).call_count == 0

    @pytest.mark.asyncio
    async def test_empty_data_does_not_remove_solar(self):
        # First refresh returned nothing at all — absence of evidence.
        coordinator = MagicMock(data={})
        coordinator.last_update_success = True
        assert (await _run(coordinator)).call_count == 0

    @pytest.mark.asyncio
    async def test_successful_refresh_without_solar_removes_it(self):
        # A good poll that genuinely carries no solar circuit: this appliance
        # does not have one, so a stale device from an earlier version goes.
        coordinator = MagicMock(data={"/gateway": {"id": "/gateway", "value": "ok"}})
        coordinator.last_update_success = True
        assert (await _run(coordinator)).call_count == 1
