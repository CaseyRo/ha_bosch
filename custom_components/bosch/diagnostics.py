"""Diagnostics support for Bosch thermostat (POINTTAPI)."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_DEVICE_ID, CONF_PROTOCOL, POINTTAPI, UUID

TO_REDACT_CONFIG = {
    "access_token",
    "refresh_token",
    "access_key",
    "password",
    "expires_at",
    # POINTTAPI writes the appliance serial to all three of these
    # (config_flow._async_create_pointtapi_entry). It is the pairing
    # identifier in /gateways/{device_id}/resource/, and testers paste
    # diagnostics into public issues.
    CONF_ADDRESS,
    CONF_DEVICE_ID,
    UUID,
}

# Paths whose *value* identifies the appliance. POINTTAPI responses are
# shaped {"id": ..., "value": ...}, so the key-based checks below never see
# these — the serial sits under "value" and has to be matched on the path.
_IDENTIFYING_PATH_SUFFIXES = ("/uuid", "/serialnumber", "/macaddress")


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
    if coordinator is not None:
        # Native-boost probe verdict (v1.0.0): which route worked (or
        # "fallback"), with per-rung outcomes — see boost-probe-notes.md.
        diag["boost_probe_result"] = getattr(coordinator, "boost_probe_result", None)
    return diag


def _redact_path_response(path: str, resp: Any) -> Any:
    """Redact sensitive values from coordinator path responses."""
    if not isinstance(resp, dict):
        return resp
    redacted = dict(resp)
    if path.lower().endswith(_IDENTIFYING_PATH_SUFFIXES) and "value" in redacted:
        redacted["value"] = "**REDACTED**"
    if "uuid" in redacted:
        redacted["uuid"] = "**REDACTED**"
    if "serialNumber" in redacted:
        redacted["serialNumber"] = "**REDACTED**"
    return redacted
