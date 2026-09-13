"""Tests for diagnostics.py."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.bosch.diagnostics import (
    TO_REDACT_CONFIG,
    _redact_path_response,
    async_get_config_entry_diagnostics,
)


# ── _redact_path_response ───────────────────────────────────────────────────


class TestRedactPathResponse:
    def test_redacts_uuid(self):
        resp = {"id": "/gateway", "uuid": "REAL_UUID", "value": "ok"}
        redacted = _redact_path_response("/gateway", resp)
        assert redacted["uuid"] == "**REDACTED**"
        assert redacted["value"] == "ok"

    def test_redacts_serial_number(self):
        resp = {"serialNumber": "12345", "firmware": "1.2.3"}
        redacted = _redact_path_response("/gateway", resp)
        assert redacted["serialNumber"] == "**REDACTED**"
        assert redacted["firmware"] == "1.2.3"

    def test_redacts_serial_in_value_for_identifying_paths(self):
        # Real POINTTAPI responses are {"id": ..., "value": ...} — there is no
        # top-level "uuid" key, so the key-based checks never fire. The serial
        # rides in "value" and must be matched on the path.
        resp = {"id": "/gateway/uuid", "type": "stringValue", "value": "SERIAL123"}
        redacted = _redact_path_response("/gateway/uuid", resp)
        assert redacted["value"] == "**REDACTED**"
        assert redacted["type"] == "stringValue"

    def test_redacts_value_case_insensitively(self):
        for path in ("/gateway/serialNumber", "/gateway/macAddress", "/GATEWAY/UUID"):
            redacted = _redact_path_response(path, {"id": path, "value": "SERIAL123"})
            assert redacted["value"] == "**REDACTED**", path

    def test_redacts_owner_details(self):
        # Path shapes from a real 1.5.2 dump posted on #29: the account
        # holder's details sit under "value" and slipped past the serial checks.
        for path, value in {
            "/gateway/user/name": "Jane Doe",
            "/gateway/user/email": "jane@example.org",
            "/gateway/user/address": [{"address": "Street 1", "zip": "1234"}],
            "/gateway/installer/phone": "012345",
            "/gateway/identificationKey": "KEY123",
            "/system/location/coordinates": "52.37,4.89",
        }.items():
            redacted = _redact_path_response(path, {"id": path, "value": value})
            assert redacted["value"] == "**REDACTED**", path
        # The prefix must stop at a segment boundary.
        for path in ("/gateway/userMode", "/gateway/versionFirmware"):
            assert _redact_path_response(path, {"id": path, "value": "x"})["value"] == "x"

    def test_ordinary_path_value_survives(self):
        resp = {"id": "/system/sensors/outdoor_t1", "value": 12.5}
        assert _redact_path_response(resp["id"], resp)["value"] == 12.5

    def test_non_dict_passthrough(self):
        assert _redact_path_response("/path", "plain string") == "plain string"
        assert _redact_path_response("/path", 42) == 42

    def test_original_not_mutated(self):
        original = {"uuid": "SECRET", "value": 1}
        _redact_path_response("/p", original)
        assert original["uuid"] == "SECRET"


# ── async_get_config_entry_diagnostics ───────────────────────────────────────


class TestAsyncGetDiagnostics:
    @pytest.mark.asyncio
    async def test_pointtapi_entry_includes_coordinator_data(self):
        entry = MagicMock()
        entry.data = {
            "http_xmpp": "pointtapi",
            "uuid": "SERIAL123",
            "address": "SERIAL123",
            "device_id": "SERIAL123",
            "access_token": "SECRET_TOKEN",
            "refresh_token": "SECRET_RT",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }

        coordinator = MagicMock()
        coordinator.data = {
            "/gateway": {"id": "/gateway", "uuid": "REAL_UUID", "value": "ok"},
            "/system/sensors": {"id": "/system/sensors", "value": 42},
            "/gateway/uuid": {"id": "/gateway/uuid", "value": "SERIAL123"},
        }

        runtime_data = MagicMock()
        runtime_data.coordinator = coordinator

        entry.runtime_data = runtime_data

        hass = MagicMock()

        diag = await async_get_config_entry_diagnostics(hass, entry)

        # Config entry secrets should be redacted
        assert diag["config_entry"]["access_token"] == "**REDACTED**"
        assert diag["config_entry"]["refresh_token"] == "**REDACTED**"

        # ...and so should the appliance serial, which POINTTAPI stores under
        # all three of these keys. Diagnostics get pasted into public issues.
        assert diag["config_entry"]["uuid"] == "**REDACTED**"
        assert diag["config_entry"]["address"] == "**REDACTED**"
        assert diag["config_entry"]["device_id"] == "**REDACTED**"

        # Coordinator data should be present with uuid redacted
        assert "/gateway" in diag["coordinator_data"]
        assert diag["coordinator_data"]["/gateway"]["uuid"] == "**REDACTED**"
        assert diag["coordinator_data"]["/system/sensors"]["value"] == 42
        assert diag["coordinator_data"]["/gateway/uuid"]["value"] == "**REDACTED**"

    @pytest.mark.asyncio
    async def test_non_pointtapi_entry(self):
        entry = MagicMock()
        entry.data = {
            "http_xmpp": "XMPP",
            "uuid": "456",
            "access_token": "tok",
        }

        hass = MagicMock()
        hass.data = {"bosch": {}}

        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert "note" in diag
        assert "coordinator_data" not in diag

    @pytest.mark.asyncio
    async def test_no_coordinator_data(self):
        entry = MagicMock()
        entry.data = {
            "http_xmpp": "pointtapi",
            "uuid": "789",
            "access_token": "tok",
        }

        entry.runtime_data = None

        hass = MagicMock()

        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["coordinator_data"] is None


# ── TO_REDACT_CONFIG ─────────────────────────────────────────────────────────


class TestRedactConfig:
    def test_covers_sensitive_keys(self):
        assert "access_token" in TO_REDACT_CONFIG
        assert "refresh_token" in TO_REDACT_CONFIG
        assert "password" in TO_REDACT_CONFIG
        assert "access_key" in TO_REDACT_CONFIG
        assert "expires_at" in TO_REDACT_CONFIG

    def test_covers_appliance_identity_keys(self):
        # config_flow._async_create_pointtapi_entry writes the serial to all three.
        assert "uuid" in TO_REDACT_CONFIG
        assert "address" in TO_REDACT_CONFIG
        assert "device_id" in TO_REDACT_CONFIG
