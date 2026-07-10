"""Tests for pointtapi_oauth.ensure_valid_token (the pre-request auto-refresh).

Complements test_pointtapi_oauth_helpers.py — that file covers the pure helpers
and the happy/unhappy paths of exchange_code_for_tokens / refresh_access_token.
This file locks in ensure_valid_token's transient-vs-hard-failure branch plus the
remaining uncovered refresh_access_token error edges (5xx, network, empty body).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bosch.const import ACCESS_TOKEN
from custom_components.bosch.pointtapi_oauth import (
    ensure_valid_token,
    refresh_access_token,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed


# ── Helpers ──────────────────────────────────────────────────────────────────


def _async_ctx(resp):
    """Create an async context manager that yields resp (matches session.post)."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _iso(**delta):
    """ISO timestamp offset from now, e.g. _iso(hours=1) or _iso(seconds=-10)."""
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _entry(**overrides):
    """A ConfigEntry-like object with a mutable .data dict (plus an unrelated key)."""
    data = {
        "uuid": "101506113",  # unrelated key that must survive the update
        ACCESS_TOKEN: "old_at",
        "refresh_token": "old_rt",
        "expires_at": _iso(hours=1),
    }
    data.update(overrides)
    return SimpleNamespace(data=data)


def _session_returning(resp):
    session = AsyncMock()
    session.post = MagicMock(return_value=_async_ctx(resp))
    return session


def _resp(status, json_body=None):
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_body or {})
    resp.text = AsyncMock(return_value="body")
    return resp


# ── ensure_valid_token ───────────────────────────────────────────────────────


class TestEnsureValidToken:
    @pytest.mark.asyncio
    async def test_valid_token_returns_existing_no_refresh(self, mock_hass):
        """Not expired → return existing token, never touch session or entry."""
        entry = _entry(expires_at=_iso(hours=1))
        session = AsyncMock()

        token = await ensure_valid_token(mock_hass, entry, session)

        assert token == "old_at"
        session.post.assert_not_called()
        mock_hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_refresh_token_raises_auth_failed(self, mock_hass):
        entry = _entry(refresh_token="")
        with pytest.raises(ConfigEntryAuthFailed):
            await ensure_valid_token(mock_hass, entry, AsyncMock())
        mock_hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_refreshes_and_updates_entry(self, mock_hass):
        """Expired → refresh, persist new tokens (old keys preserved), return new AT."""
        entry = _entry(expires_at=_iso(hours=-1))
        session = _session_returning(_resp(200, {
            "access_token": "new_at",
            "refresh_token": "new_rt",
            "expires_in": 3600,
        }))

        token = await ensure_valid_token(mock_hass, entry, session)

        assert token == "new_at"
        mock_hass.config_entries.async_update_entry.assert_called_once()
        call = mock_hass.config_entries.async_update_entry.call_args
        assert call.args[0] is entry
        new_data = call.kwargs["data"]
        assert new_data[ACCESS_TOKEN] == "new_at"
        assert new_data["refresh_token"] == "new_rt"
        assert new_data["uuid"] == "101506113"  # unrelated key survived

    @pytest.mark.asyncio
    async def test_transient_failure_soft_expired_keeps_existing(self, mock_hass):
        """5xx during refresh but token not hard-expired → reuse it, no raise/update."""
        # Within default 300s margin (so refresh is attempted) but still in the
        # future (so is_token_expired(margin=0) is False → keep using it).
        entry = _entry(expires_at=_iso(seconds=120))
        session = _session_returning(_resp(503))

        token = await ensure_valid_token(mock_hass, entry, session)

        assert token == "old_at"
        mock_hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_transient_failure_hard_expired_reraises(self, mock_hass):
        """5xx during refresh AND token hard-expired → propagate UpdateFailed."""
        entry = _entry(expires_at=_iso(seconds=-10))
        session = _session_returning(_resp(503))

        with pytest.raises(UpdateFailed):
            await ensure_valid_token(mock_hass, entry, session)
        mock_hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_failure_propagates(self, mock_hass):
        """Genuine 401 during refresh → ConfigEntryAuthFailed bubbles up (not swallowed)."""
        entry = _entry(expires_at=_iso(seconds=-10))
        session = _session_returning(_resp(401))

        with pytest.raises(ConfigEntryAuthFailed):
            await ensure_valid_token(mock_hass, entry, session)
        mock_hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_soft_expired_but_no_access_token_reraises(self, mock_hass):
        """Transient fail, token in margin but no stored AT → cannot reuse, reraise."""
        entry = _entry(expires_at=_iso(seconds=120), **{ACCESS_TOKEN: ""})
        session = _session_returning(_resp(503))

        with pytest.raises(UpdateFailed):
            await ensure_valid_token(mock_hass, entry, session)


# ── refresh_access_token — remaining error edges ─────────────────────────────


class TestRefreshAccessTokenEdges:
    @pytest.mark.asyncio
    async def test_5xx_raises_update_failed(self):
        session = _session_returning(_resp(503))
        with pytest.raises(UpdateFailed):
            await refresh_access_token(session, "rt")

    @pytest.mark.asyncio
    async def test_network_error_raises_update_failed(self):
        session = AsyncMock()
        session.post = MagicMock(side_effect=TimeoutError("timed out"))
        with pytest.raises(UpdateFailed):
            await refresh_access_token(session, "rt")

    @pytest.mark.asyncio
    async def test_missing_access_token_raises_auth_failed(self):
        session = _session_returning(_resp(200, {"expires_in": 3600}))
        with pytest.raises(ConfigEntryAuthFailed):
            await refresh_access_token(session, "rt")
