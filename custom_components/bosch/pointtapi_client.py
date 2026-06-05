"""Minimal POINTTAPI HTTP client for Bosch cloud JSON API.

Uses the same base URL as the deric connector. Token is obtained via
ensure_valid_token (entry-based); 401/403 raise ConfigEntryAuthFailed.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urljoin

import aiohttp

from homeassistant.exceptions import ConfigEntryAuthFailed

_LOGGER = logging.getLogger(__name__)

POINTTAPI_API_ROOT = "https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/"
POINTTAPI_BASE_URL = f"{POINTTAPI_API_ROOT}gateways/"
POINTTAPI_BULK_URL = f"{POINTTAPI_API_ROOT}bulk"
APP_JSON = "application/json"

# The bulk endpoint accepts at most 30 resource paths per request.
# Wire format (envelope, path format, limits) observed and documented by
# serbanb11/homecom_alt (https://github.com/serbanb11/homecom_alt) — see
# docs/pointtapi-api.md. Verified against a live RRC2/CT200 on 2026-06-05.
MAX_BULK_PATHS = 30


async def async_list_gateways(session, token: str) -> list[dict]:
    """GET the account-level gateway list: [{"deviceId": ..., "deviceType": ...}, ...].

    Account route (no gateway id, no /resource) using the
    pointt.gateway.list scope our token already requests. Endpoint
    observed by serbanb11/homecom_alt; verified live 2026-06-05.
    Module-level so the config flow can call it before a device is chosen.
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(
        POINTTAPI_BASE_URL, headers=headers,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        if resp.status in (401, 403):
            raise ConfigEntryAuthFailed(
                f"POINTTAPI gateways list: HTTP {resp.status}"
            ) from None
        if resp.status != 200:
            raise RuntimeError(f"POINTTAPI gateways list failed: {resp.status}")
        data = await resp.json()
    if not isinstance(data, list):
        raise RuntimeError("POINTTAPI gateways list: unexpected payload shape")
    return data


class PoinTTAPIClient:
    """Thin client for Bosch POINTTAPI: GET/PUT with Bearer token."""

    def __init__(self, device_id: str, session, token_callback):
        """Initialize client.

        Args:
            device_id: Gateway device ID (serial without dashes).
            session: aiohttp ClientSession.
            token_callback: Async callable() -> str returning valid access token.
        """
        self._device_id = device_id
        self._session = session
        self._token_callback = token_callback
        self._base = f"{POINTTAPI_BASE_URL}{device_id}/resource/"

    def _url(self, uri: str) -> str:
        return urljoin(self._base, uri.lstrip("/"))

    async def get(self, uri: str):
        """GET a path; returns JSON or dict. Raises ConfigEntryAuthFailed on 401/403."""
        token = await self._token_callback()
        url = self._url(uri)
        headers = {"Authorization": f"Bearer {token}"}
        async with self._session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status in (401, 403):
                _LOGGER.debug("POINTTAPI auth failed on GET %s: HTTP %s", uri, resp.status)
                raise ConfigEntryAuthFailed(
                    f"POINTTAPI GET {uri}: HTTP {resp.status}"
                ) from None
            if resp.status != 200:
                raise RuntimeError(f"POINTTAPI GET {uri} failed: {resp.status}")
            if resp.content_type and APP_JSON in resp.content_type:
                return await resp.json()
            return await resp.text()

    async def put(self, uri: str, value) -> bool:
        """PUT value to path. Raises ConfigEntryAuthFailed on 401/403."""
        token = await self._token_callback()
        url = self._url(uri)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": APP_JSON}
        body = json.dumps({"value": value})
        async with self._session.put(url, headers=headers, data=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status in (401, 403):
                _LOGGER.warning("POINTTAPI auth failed on PUT %s: HTTP %s", uri, resp.status)
                raise ConfigEntryAuthFailed(
                    f"POINTTAPI PUT {uri}: HTTP {resp.status}"
                ) from None
            if resp.status not in (200, 204):
                body_text = await resp.text()
                _LOGGER.debug("POINTTAPI PUT %s HTTP %s body: %s", uri, resp.status, body_text[:500])
                raise RuntimeError(f"POINTTAPI PUT {uri} failed: {resp.status}")
            return True

    async def bulk(self, paths: list[str]) -> dict:
        """Fetch many resource paths in one or more bulk POSTs; returns {path: payload}.

        Paths use the same format as get() (leading slash, no /resource
        prefix — the bulk route 403s per-path when the prefix is included).
        Chunks at MAX_BULK_PATHS per request, chunks issued sequentially.
        Per-path failures inside a 200 envelope are skipped with a debug log;
        an unparseable envelope raises RuntimeError so callers can fall back
        to sequential GETs. Raises ConfigEntryAuthFailed on 401/403 like get().
        """
        result: dict = {}
        for i in range(0, len(paths), MAX_BULK_PATHS):
            result.update(await self._bulk_single(paths[i : i + MAX_BULK_PATHS]))
        return result

    async def _bulk_single(self, paths: list[str]) -> dict:
        """Issue one bulk POST for up to MAX_BULK_PATHS paths."""
        token = await self._token_callback()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": APP_JSON}
        body = json.dumps([{"gatewayId": self._device_id, "resourcePaths": list(paths)}])
        async with self._session.post(
            POINTTAPI_BULK_URL, headers=headers, data=body,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status in (401, 403):
                _LOGGER.debug("POINTTAPI auth failed on bulk POST: HTTP %s", resp.status)
                raise ConfigEntryAuthFailed(
                    f"POINTTAPI bulk: HTTP {resp.status}"
                ) from None
            if resp.status != 200:
                raise RuntimeError(f"POINTTAPI bulk failed: {resp.status}")
            envelope = await resp.json()
        out: dict = {}
        try:
            entries = envelope[0]["resourcePaths"]
            for entry in entries:
                path = entry["resourcePath"]
                if entry.get("serverStatus") != 200:
                    _LOGGER.debug(
                        "POINTTAPI bulk path %s serverStatus %s, skipping",
                        path, entry.get("serverStatus"),
                    )
                    continue
                gw = entry.get("gatewayResponse") or {}
                if gw.get("status") != 200:
                    _LOGGER.debug(
                        "POINTTAPI bulk path %s gateway status %s, skipping",
                        path, gw.get("status"),
                    )
                    continue
                out[path] = gw.get("payload")
        except (KeyError, IndexError, TypeError) as err:
            raise RuntimeError(f"POINTTAPI bulk: unexpected envelope: {err}") from err
        return out

    async def list_gateways(self) -> list[dict]:
        """GET the account-level gateway list: [{"deviceId": ..., "deviceType": ...}, ...]."""
        token = await self._token_callback()
        return await async_list_gateways(self._session, token)

    async def close(self, force: bool = False) -> None:
        """No-op for compatibility with BoschGatewayEntry.async_reset."""
        pass
