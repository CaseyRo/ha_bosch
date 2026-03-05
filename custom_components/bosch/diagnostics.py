"""Diagnostics support for Bosch thermostat (POINTTAPI)."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_PROTOCOL, POINTTAPI

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

    coordinator = entry.runtime_data.coordinator if hasattr(entry, "runtime_data") and entry.runtime_data else None
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
