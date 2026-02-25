"""Tests for pointtapi_oauth.py pure-logic helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bosch.pointtapi_oauth import (
    build_auth_url,
    exchange_code_for_tokens,
    extract_code_from_callback_url,
    is_token_expired,
    refresh_access_token,
)
from homeassistant.exceptions import ConfigEntryAuthFailed


# ── extract_code_from_callback_url ───────────────────────────────────────────


class TestExtractCode:
    def test_valid_callback_url(self):
        url = "com.bosch.tt.dashtt.pointt://app/login?code=ABC123&state=xyz"
        assert extract_code_from_callback_url(url) == "ABC123"

    def test_url_encoded_code(self):
        url = "com.bosch.tt.dashtt.pointt://app/login?code=A%20B%20C&state=xyz"
        assert extract_code_from_callback_url(url) == "A B C"

    def test_no_code_param(self):
        url = "com.bosch.tt.dashtt.pointt://app/login?state=xyz"
        assert extract_code_from_callback_url(url) is None

    def test_empty_string(self):
        assert extract_code_from_callback_url("") is None

    def test_none_input(self):
        assert extract_code_from_callback_url(None) is None

    def test_whitespace_stripped(self):
        url = "  com.bosch.tt.dashtt.pointt://app/login?code=XYZ  "
        assert extract_code_from_callback_url(url) == "XYZ"

    def test_long_real_code(self):
        code = "3E7A9F2B1C4D5E6F7A8B9C0D1E2F3A4B5C6D7E8F"
        url = f"com.bosch.tt.dashtt.pointt://app/login?code={code}&state=s"
        assert extract_code_from_callback_url(url) == code


# ── is_token_expired ─────────────────────────────────────────────────────────


class TestIsTokenExpired:
    def test_none_expires_at(self):
        assert is_token_expired(None) is True

    def test_empty_string(self):
        assert is_token_expired("") is True

    def test_invalid_format(self):
        assert is_token_expired("not-a-date") is True

    def test_future_token_not_expired(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert is_token_expired(future) is False

    def test_past_token_expired(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert is_token_expired(past) is True

    def test_within_margin_is_expired(self):
        # 4 minutes from now, default margin is 5 minutes -> expired
        near = (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat()
        assert is_token_expired(near, margin_seconds=300) is True

    def test_outside_margin_not_expired(self):
        # 10 minutes from now, margin 5 minutes -> not expired
        later = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        assert is_token_expired(later, margin_seconds=300) is False

    def test_custom_margin(self):
        near = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        assert is_token_expired(near, margin_seconds=60) is True
        assert is_token_expired(near, margin_seconds=10) is False


# ── build_auth_url ───────────────────────────────────────────────────────────


class TestBuildAuthUrl:
    def test_returns_singlekey_url(self):
        url = build_auth_url()
        assert url.startswith("https://singlekey-id.com/auth/")

    def test_contains_client_id(self):
        url = build_auth_url()
        assert "762162C0-FA2D-4540-AE66-6489F189FADC" in url

    def test_contains_code_challenge(self):
        url = build_auth_url()
        assert "code_challenge" in url

    def test_contains_redirect_uri(self):
        url = build_auth_url()
        assert "redirect_uri" in url

    def test_is_deterministic(self):
        assert build_auth_url() == build_auth_url()


# ── exchange_code_for_tokens ─────────────────────────────────────────────────


class TestExchangeCodeForTokens:
    @pytest.mark.asyncio
    async def test_successful_exchange(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "access_token": "at_123",
            "refresh_token": "rt_456",
            "expires_in": 3600,
        })

        session = AsyncMock()
        session.post = MagicMock(return_value=_async_ctx(mock_resp))

        tokens = await exchange_code_for_tokens(session, "test_code")
        assert tokens["access_token"] == "at_123"
        assert tokens["refresh_token"] == "rt_456"
        assert "expires_at" in tokens

    @pytest.mark.asyncio
    async def test_failed_exchange_raises(self):
        mock_resp = AsyncMock()
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value="bad request")

        session = AsyncMock()
        session.post = MagicMock(return_value=_async_ctx(mock_resp))

        with pytest.raises(ConfigEntryAuthFailed):
            await exchange_code_for_tokens(session, "bad_code")

    @pytest.mark.asyncio
    async def test_missing_tokens_raises(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"id_token": "only_this"})

        session = AsyncMock()
        session.post = MagicMock(return_value=_async_ctx(mock_resp))

        with pytest.raises(ConfigEntryAuthFailed):
            await exchange_code_for_tokens(session, "code")


# ── refresh_access_token ─────────────────────────────────────────────────────


class TestRefreshAccessToken:
    @pytest.mark.asyncio
    async def test_successful_refresh(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "access_token": "new_at",
            "refresh_token": "new_rt",
            "expires_in": 7200,
        })

        session = AsyncMock()
        session.post = MagicMock(return_value=_async_ctx(mock_resp))

        tokens = await refresh_access_token(session, "old_rt")
        assert tokens["access_token"] == "new_at"
        assert tokens["refresh_token"] == "new_rt"

    @pytest.mark.asyncio
    async def test_refresh_preserves_old_rt_if_missing(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "access_token": "new_at",
            "expires_in": 3600,
        })

        session = AsyncMock()
        session.post = MagicMock(return_value=_async_ctx(mock_resp))

        tokens = await refresh_access_token(session, "kept_rt")
        assert tokens["refresh_token"] == "kept_rt"

    @pytest.mark.asyncio
    async def test_401_raises_auth_failed(self):
        mock_resp = AsyncMock()
        mock_resp.status = 401
        mock_resp.text = AsyncMock(return_value="unauthorized")

        session = AsyncMock()
        session.post = MagicMock(return_value=_async_ctx(mock_resp))

        with pytest.raises(ConfigEntryAuthFailed):
            await refresh_access_token(session, "expired_rt")

    @pytest.mark.asyncio
    async def test_no_code_verifier_in_refresh(self):
        """Refresh request must NOT include code_verifier (PKCE is auth-code only)."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
        })

        session = AsyncMock()
        session.post = MagicMock(return_value=_async_ctx(mock_resp))

        await refresh_access_token(session, "rt")
        call_kwargs = session.post.call_args
        posted_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data", {})
        assert "code_verifier" not in posted_data


# ── Helper ───────────────────────────────────────────────────────────────────


def _async_ctx(resp):
    """Create an async context manager that yields resp."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx
