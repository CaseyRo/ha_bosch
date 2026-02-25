"""Minimal POINTTAPI HTTP client for Bosch cloud JSON API.

Uses the same base URL as the deric connector. Token is obtained via
ensure_valid_token (entry-based); 401/403 raise ConfigEntryAuthFailed.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urljoin

from homeassistant.exceptions import ConfigEntryAuthFailed

_LOGGER = logging.getLogger(__name__)

POINTTAPI_BASE_URL = "https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways/"
APP_JSON = "application/json"


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
        async with self._session.get(url, headers=headers, timeout=30) as resp:
            if resp.status in (401, 403):
                _LOGGER.warning("POINTTAPI auth failed: %s", resp.status)
                raise ConfigEntryAuthFailed(
                    "Token expired or revoked. Please re-authenticate."
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
        async with self._session.put(url, headers=headers, data=body, timeout=30) as resp:
            if resp.status in (401, 403):
                _LOGGER.warning("POINTTAPI auth failed on PUT: %s", resp.status)
                raise ConfigEntryAuthFailed(
                    "Token expired or revoked. Please re-authenticate."
                ) from None
            if resp.status not in (200, 204):
                raise RuntimeError(f"POINTTAPI PUT {uri} failed: {resp.status}")
            return True

    async def close(self, force: bool = False) -> None:
        """No-op for compatibility with BoschGatewayEntry.async_reset."""
        pass
