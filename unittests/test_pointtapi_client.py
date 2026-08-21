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


# ── bulk ─────────────────────────────────────────────────────────────────────


def _bulk_envelope(paths, gateway_id="123", server_status=200, gw_status=200):
    """Build a valid bulk response envelope for the given paths."""
    return [{
        "gatewayId": gateway_id,
        "resourcePaths": [
            {
                "resourcePath": p,
                "serverStatus": server_status,
                "gatewayResponse": {
                    "status": gw_status,
                    "payload": {"id": p, "value": f"v-{p}"},
                },
            }
            for p in paths
        ],
    }]


class TestBulk:
    def _client_with_post(self, responses):
        """Client whose session.post returns the given mock responses in order."""
        session = AsyncMock()
        session.post = MagicMock(side_effect=[_async_ctx(r) for r in responses])
        return PoinTTAPIClient("123", session, AsyncMock(return_value="tok")), session

    def _resp(self, status=200, envelope=None):
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(return_value=envelope)
        return resp

    @pytest.mark.asyncio
    async def test_bulk_45_paths_chunks_into_two_posts(self):
        paths = [f"/p/{i}" for i in range(45)]
        r1 = self._resp(envelope=_bulk_envelope(paths[:30]))
        r2 = self._resp(envelope=_bulk_envelope(paths[30:]))
        client, session = self._client_with_post([r1, r2])

        result = await client.bulk(paths)

        assert session.post.call_count == 2
        assert len(result) == 45
        assert result["/p/0"]["value"] == "v-/p/0"
        assert result["/p/44"]["value"] == "v-/p/44"

    @pytest.mark.asyncio
    async def test_bulk_resolves_token_once_for_multiple_chunks(self):
        paths = [f"/p/{i}" for i in range(45)]
        r1 = self._resp(envelope=_bulk_envelope(paths[:30]))
        r2 = self._resp(envelope=_bulk_envelope(paths[30:]))
        session = AsyncMock()
        session.post = MagicMock(side_effect=[_async_ctx(r1), _async_ctx(r2)])
        token_callback = AsyncMock(return_value="tok")
        client = PoinTTAPIClient("123", session, token_callback)

        await client.bulk(paths)

        token_callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_body_contains_gateway_id_and_paths(self):
        r = self._resp(envelope=_bulk_envelope(["/a"]))
        client, session = self._client_with_post([r])

        await client.bulk(["/a"])

        import json as _json
        body = _json.loads(session.post.call_args.kwargs.get("data")
                           or session.post.call_args[1]["data"])
        assert body == [{"gatewayId": "123", "resourcePaths": ["/a"]}]

    @pytest.mark.asyncio
    async def test_bulk_per_path_403_inside_200_is_skipped(self):
        envelope = _bulk_envelope(["/ok"])
        envelope[0]["resourcePaths"].append({
            "resourcePath": "/forbidden",
            "serverStatus": 403,
            "gatewayResponse": None,
        })
        client, _ = self._client_with_post([self._resp(envelope=envelope)])

        result = await client.bulk(["/ok", "/forbidden"])

        assert "/ok" in result
        assert "/forbidden" not in result

    @pytest.mark.asyncio
    async def test_bulk_gateway_status_failure_is_skipped(self):
        envelope = _bulk_envelope(["/ok"])
        envelope[0]["resourcePaths"].append({
            "resourcePath": "/broken",
            "serverStatus": 200,
            "gatewayResponse": {"status": 500, "payload": None},
        })
        client, _ = self._client_with_post([self._resp(envelope=envelope)])

        result = await client.bulk(["/ok", "/broken"])

        assert "/ok" in result
        assert "/broken" not in result

    @pytest.mark.asyncio
    async def test_bulk_unparseable_envelope_raises_runtime_error(self):
        client, _ = self._client_with_post([self._resp(envelope={"not": "a list"})])
        with pytest.raises(RuntimeError, match="envelope"):
            await client.bulk(["/a"])

    @pytest.mark.asyncio
    async def test_bulk_401_raises_auth_failed(self):
        client, _ = self._client_with_post([self._resp(status=401)])
        with pytest.raises(ConfigEntryAuthFailed):
            await client.bulk(["/a"])

    @pytest.mark.asyncio
    async def test_bulk_500_raises_runtime_error(self):
        client, _ = self._client_with_post([self._resp(status=500)])
        with pytest.raises(RuntimeError, match="500"):
            await client.bulk(["/a"])


# ── list_gateways ────────────────────────────────────────────────────────────


class TestListGateways:
    def _client_with_get(self, resp):
        session = AsyncMock()
        session.get = MagicMock(return_value=_async_ctx(resp))
        return PoinTTAPIClient("123", session, AsyncMock(return_value="tok")), session

    @pytest.mark.asyncio
    async def test_returns_gateway_list(self):
        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value=[{"deviceId": "101506113", "deviceType": "rrc2"}])
        client, session = self._client_with_get(resp)

        result = await client.list_gateways()

        assert result == [{"deviceId": "101506113", "deviceType": "rrc2"}]
        url = session.get.call_args[0][0]
        assert url.endswith("/gateways/")

    @pytest.mark.asyncio
    async def test_401_raises_auth_failed(self):
        resp = AsyncMock()
        resp.status = 401
        client, _ = self._client_with_get(resp)
        with pytest.raises(ConfigEntryAuthFailed):
            await client.list_gateways()

    @pytest.mark.asyncio
    async def test_non_list_payload_raises_runtime_error(self):
        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"unexpected": "shape"})
        client, _ = self._client_with_get(resp)
        with pytest.raises(RuntimeError, match="shape"):
            await client.list_gateways()


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
