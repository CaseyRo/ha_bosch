"""Service teardown must not remove services it never registered (#7)."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.bosch.const import DOMAIN, SERVICE_DEBUG, SERVICE_REFRESH_GATEWAY, SERVICE_UPDATE
from custom_components.bosch.services import async_remove_services


def _hass(registered: set[str]) -> MagicMock:
    hass = MagicMock()
    hass.services.has_service.side_effect = (
        lambda domain, service: domain == DOMAIN and service in registered
    )
    return hass


def test_unregistered_debug_scan_is_not_removed():
    """POINTTAPI entries never register debug_scan.

    Removing it anyway makes HA log "Unable to remove unknown service
    bosch/debug_scan" on every unload and reload.
    """
    hass = _hass({SERVICE_UPDATE, SERVICE_REFRESH_GATEWAY})

    async_remove_services(hass, MagicMock())

    removed = {call.args[1] for call in hass.services.async_remove.call_args_list}
    assert removed == {SERVICE_UPDATE, SERVICE_REFRESH_GATEWAY}


def test_registered_services_are_still_removed():
    hass = _hass({SERVICE_DEBUG, SERVICE_UPDATE, SERVICE_REFRESH_GATEWAY})

    async_remove_services(hass, MagicMock())

    removed = {call.args[1] for call in hass.services.async_remove.call_args_list}
    assert removed == {SERVICE_DEBUG, SERVICE_UPDATE, SERVICE_REFRESH_GATEWAY}
