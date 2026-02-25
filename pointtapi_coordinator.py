"""DataUpdateCoordinator for Bosch POINTTAPI: single poll, path-keyed payload."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .pointtapi_client import PoinTTAPIClient

_LOGGER = logging.getLogger(__name__)

# Paths we fetch for coordinator.data (path -> response dict).
# One level of references is fetched for each root.
POINTTAPI_COORDINATOR_ROOTS = [
    "/gateway",
    "/heatingCircuits/hc1",
    "/dhwCircuits/dhw1",
    "/system/sensors",
    "/system/appliance",
    "/zones/zn1",
    "/energy",
]
REFERENCES_KEY = "references"
ID_KEY = "id"


async def _fetch_paths(client: PoinTTAPIClient) -> dict[str, Any]:
    """Fetch root paths and one level of references; return path -> response dict.

    Only /gateway auth failures are treated as real token problems (re-raised as
    ConfigEntryAuthFailed). All other paths: 403/401 is logged and skipped, since
    some sub-resources may be forbidden without the token being invalid.
    """
    data: dict[str, Any] = {}
    for root in POINTTAPI_COORDINATOR_ROOTS:
        try:
            resp = await client.get(root)
            if not isinstance(resp, dict):
                continue
            data[root] = resp
            refs = resp.get(REFERENCES_KEY) or []
            for ref in refs:
                ref_id = ref.get(ID_KEY) if isinstance(ref, dict) else None
                if not ref_id:
                    continue
                try:
                    sub = await client.get(ref_id)
                    if isinstance(sub, dict):
                        data[ref_id] = sub
                        # Fetch one more level for refEnum (e.g. temperatureLevels -> temperatureLevels/high)
                        if sub.get("type") == "refEnum":
                            for r2 in sub.get(REFERENCES_KEY) or []:
                                r2_id = r2.get(ID_KEY) if isinstance(r2, dict) else None
                                if not r2_id or r2_id in data:
                                    continue
                                try:
                                    sub2 = await client.get(r2_id)
                                    if isinstance(sub2, dict):
                                        data[r2_id] = sub2
                                except ConfigEntryAuthFailed:
                                    _LOGGER.debug("POINTTAPI 401/403 on ref %s, skipping", r2_id)
                                except Exception:
                                    continue
                except ConfigEntryAuthFailed:
                    _LOGGER.debug("POINTTAPI 401/403 on ref %s, skipping", ref_id)
                except Exception:  # skip single path failure
                    continue
        except ConfigEntryAuthFailed:
            if root == "/gateway":
                raise  # Token is genuinely bad
            _LOGGER.debug("POINTTAPI 401/403 on root %s, skipping", root)
        except Exception as err:
            if root == "/gateway":
                _LOGGER.warning("POINTTAPI gateway fetch failed: %s", err)
                raise UpdateFailed(f"POINTTAPI fetch failed: {err}") from err
            _LOGGER.debug("POINTTAPI optional path %s not available, skipping: %s", root, err)
    return data


class PoinTTAPIDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for POINTTAPI: one poll, path-keyed data; 401/403 -> ConfigEntryAuthFailed."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PoinTTAPIClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Bosch POINTTAPI",
            config_entry=entry,
            update_interval=timedelta(seconds=60),
            always_update=False,
        )
        self._client = client

    @property
    def client(self) -> PoinTTAPIClient:
        """Return the POINTTAPI client for PUT calls from entities."""
        return self._client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch path-keyed payload; raise ConfigEntryAuthFailed on 401/403, UpdateFailed on connection error."""
        try:
            async with asyncio.timeout(120):
                return await _fetch_paths(self._client)
        except ConfigEntryAuthFailed:
            raise
        except UpdateFailed:
            raise
        except TimeoutError as err:
            raise UpdateFailed("POINTTAPI update timed out") from err
        except Exception as err:
            _LOGGER.warning("POINTTAPI coordinator update failed: %s", err)
            raise UpdateFailed(f"POINTTAPI update failed: {err}") from err
