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
            "uuid": "123",
            "access_token": "SECRET_TOKEN",
            "refresh_token": "SECRET_RT",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }

        coordinator = MagicMock()
        coordinator.data = {
            "/gateway": {"id": "/gateway", "uuid": "REAL_UUID", "value": "ok"},
            "/system/sensors": {"id": "/system/sensors", "value": 42},
        }

        hass = MagicMock()
        hass.data = {"bosch": {"123": {"coordinator": coordinator}}}

        diag = await async_get_config_entry_diagnostics(hass, entry)

        # Config entry secrets should be redacted
        assert diag["config_entry"]["access_token"] == "**REDACTED**"
        assert diag["config_entry"]["refresh_token"] == "**REDACTED**"

        # Coordinator data should be present with uuid redacted
        assert "/gateway" in diag["coordinator_data"]
        assert diag["coordinator_data"]["/gateway"]["uuid"] == "**REDACTED**"
        assert diag["coordinator_data"]["/system/sensors"]["value"] == 42

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

        hass = MagicMock()
        hass.data = {"bosch": {"789": {}}}

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
