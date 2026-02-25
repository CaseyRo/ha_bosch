"""Diagnostics support for Bosch thermostat (POINTTAPI)."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_PROTOCOL, DOMAIN, POINTTAPI, UUID

TO_REDACT_CONFIG = {
    "access_token",
    "refresh_token",
    "access_key",
    "password",
    "expires_at",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    diag: dict[str, Any] = {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT_CONFIG),
    }
    if entry.data.get(CONF_PROTOCOL) != POINTTAPI:
        diag["note"] = "Diagnostics details are only available for POINTTAPI entries."
        return diag

    uuid = entry.data.get(UUID)
    domain_data = hass.data.get(DOMAIN, {}).get(uuid, {})
    coordinator = domain_data.get("coordinator")
    if coordinator and coordinator.data:
        diag["coordinator_data"] = {
            path: _redact_path_response(path, resp)
            for path, resp in coordinator.data.items()
        }
    else:
        diag["coordinator_data"] = None
    return diag


def _redact_path_response(path: str, resp: Any) -> Any:
    """Redact sensitive values from coordinator path responses."""
    if not isinstance(resp, dict):
        return resp
    redacted = dict(resp)
    if "uuid" in redacted:
        redacted["uuid"] = "**REDACTED**"
    if "serialNumber" in redacted:
        redacted["serialNumber"] = "**REDACTED**"
    return redacted
