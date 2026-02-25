"""Tests for pointtapi_client.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bosch.pointtapi_client import PoinTTAPIClient, POINTTAPI_BASE_URL
from homeassistant.exceptions import ConfigEntryAuthFailed


# ── URL construction ─────────────────────────────────────────────────────────


class TestURLConstruction:
    def _client(self, device_id="101506113"):
        return PoinTTAPIClient(device_id, AsyncMock(), AsyncMock(return_value="tok"))

    def test_base_url_includes_device_id(self):
        c = self._client("999")
        assert "999" in c._base
        assert c._base.startswith(POINTTAPI_BASE_URL)

    def test_url_joins_path(self):
        c = self._client("123")
        url = c._url("/gateway/DateTime")
        assert url.endswith("gateway/DateTime")
        assert "123" in url

    def test_url_strips_leading_slash(self):
        c = self._client("123")
        url1 = c._url("/gateway")
        url2 = c._url("gateway")
        assert url1 == url2


# ── GET ──────────────────────────────────────────────────────────────────────


class TestGet:
    @pytest.mark.asyncio
    async def test_get_returns_json(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content_type = "application/json"
        mock_resp.json = AsyncMock(return_value={"id": "/gateway", "value": "ok"})

        session = AsyncMock()
        session.get = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="tok"))
        result = await client.get("/gateway")
        assert result == {"id": "/gateway", "value": "ok"}

    @pytest.mark.asyncio
    async def test_get_401_raises_auth_failed(self):
        mock_resp = AsyncMock()
        mock_resp.status = 401

        session = AsyncMock()
        session.get = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="tok"))

        with pytest.raises(ConfigEntryAuthFailed):
            await client.get("/gateway")

    @pytest.mark.asyncio
    async def test_get_403_raises_auth_failed(self):
        mock_resp = AsyncMock()
        mock_resp.status = 403

        session = AsyncMock()
        session.get = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="tok"))

        with pytest.raises(ConfigEntryAuthFailed):
            await client.get("/some/path")

    @pytest.mark.asyncio
    async def test_get_500_raises_runtime_error(self):
        mock_resp = AsyncMock()
        mock_resp.status = 500

        session = AsyncMock()
        session.get = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="tok"))
        with pytest.raises(RuntimeError, match="500"):
            await client.get("/gateway")

    @pytest.mark.asyncio
    async def test_get_text_fallback(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content_type = "text/plain"
        mock_resp.text = AsyncMock(return_value="plain text")

        session = AsyncMock()
        session.get = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="tok"))
        result = await client.get("/gateway")
        assert result == "plain text"

    @pytest.mark.asyncio
    async def test_get_uses_bearer_token(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content_type = "application/json"
        mock_resp.json = AsyncMock(return_value={})

        session = AsyncMock()
        session.get = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="my_token"))
        await client.get("/gateway")

        call_kwargs = session.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers["Authorization"] == "Bearer my_token"


# ── PUT ──────────────────────────────────────────────────────────────────────


class TestPut:
    @pytest.mark.asyncio
    async def test_put_200_returns_true(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200

        session = AsyncMock()
        session.put = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="tok"))
        assert await client.put("/some/path", 21.5) is True

    @pytest.mark.asyncio
    async def test_put_204_returns_true(self):
        mock_resp = AsyncMock()
        mock_resp.status = 204

        session = AsyncMock()
        session.put = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="tok"))
        assert await client.put("/some/path", "auto") is True

    @pytest.mark.asyncio
    async def test_put_401_raises_auth_failed(self):
        mock_resp = AsyncMock()
        mock_resp.status = 401

        session = AsyncMock()
        session.put = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="tok"))

        with pytest.raises(ConfigEntryAuthFailed):
            await client.put("/path", "value")

    @pytest.mark.asyncio
    async def test_put_500_raises_runtime_error(self):
        mock_resp = AsyncMock()
        mock_resp.status = 500

        session = AsyncMock()
        session.put = MagicMock(return_value=_async_ctx(mock_resp))

        client = PoinTTAPIClient("123", session, AsyncMock(return_value="tok"))
        with pytest.raises(RuntimeError, match="500"):
            await client.put("/path", "value")


# ── close ────────────────────────────────────────────────────────────────────


class TestClose:
    @pytest.mark.asyncio
    async def test_close_is_noop(self):
        client = PoinTTAPIClient("123", AsyncMock(), AsyncMock(return_value="tok"))
        await client.close()  # should not raise
        await client.close(force=True)  # should not raise


# ── Helper ───────────────────────────────────────────────────────────────────


def _async_ctx(resp):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx
