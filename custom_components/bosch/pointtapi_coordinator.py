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
    "/dhwCircuits/dhw1/operationMode",
    "/system/sensors",
    "/system/appliance",
    "/zones/zn1",
    "/energy",
    "/energy/history",
    "/energy/historyHourly",
    "/heatSources",
    "/solarCircuits/sc1",
]
REFERENCES_KEY = "references"
ID_KEY = "id"


async def _fetch_history_hourly_all(client: PoinTTAPIClient) -> dict[str, Any] | None:
    """Walk /energy/historyHourly pagination forward to collect every entry.

    The API returns 15 entries per page plus a `next` cursor inside the
    first element of `value`. The first page typically holds the OLDEST
    history (often weeks behind), so we have to follow `next` to reach
    today. Returns the original response shape with the entries flattened
    across all pages, or None if the first fetch failed.
    """
    first = await client.get("/energy/historyHourly")
    if not isinstance(first, dict):
        return None
    val = first.get("value") if isinstance(first, dict) else None
    if not isinstance(val, list) or not val or not isinstance(val[0], dict):
        return first  # nothing to walk
    all_entries: list[dict[str, Any]] = list(val[0].get("entries") or [])
    nxt = val[0].get("next")
    seen_cursors: set[Any] = {nxt}
    # Walk forward, capped to avoid runaway loops if the API misbehaves.
    for _ in range(20):
        if nxt is None:
            break
        try:
            page = await client.get(f"/energy/historyHourly?next={nxt}")
        except Exception as err:
            _LOGGER.debug("historyHourly pagination stopped at next=%s: %s", nxt, err)
            break
        pv = page.get("value") if isinstance(page, dict) else None
        if not isinstance(pv, list) or not pv or not isinstance(pv[0], dict):
            break
        all_entries.extend(pv[0].get("entries") or [])
        nxt = pv[0].get("next")
        if nxt in seen_cursors:
            break
        seen_cursors.add(nxt)
    # Stuff the flattened list back into the same shape sensors expect.
    first["value"] = [{"entries": all_entries, "next": None}]
    return first


async def _fetch_paths(client: PoinTTAPIClient) -> dict[str, Any]:
    """Fetch root paths and one level of references; return path -> response dict.

    Only /gateway auth failures are treated as real token problems (re-raised as
    ConfigEntryAuthFailed). All other paths: 403/401 is logged and skipped, since
    some sub-resources may be forbidden without the token being invalid.
    """
    data: dict[str, Any] = {}
    for root in POINTTAPI_COORDINATOR_ROOTS:
        if root == "/energy/historyHourly":
            try:
                merged = await _fetch_history_hourly_all(client)
                if isinstance(merged, dict):
                    data[root] = merged
            except ConfigEntryAuthFailed:
                _LOGGER.debug("POINTTAPI 401/403 on %s, skipping", root)
            except Exception as err:
                _LOGGER.debug("POINTTAPI optional path %s not available: %s", root, err)
            continue
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
        # Tracks an in-flight HA-triggered boost session. The boost switch sets
        # this on turn-on and clears it on turn-off; the boost_remaining_time
        # sensor reads it to derive a synthetic countdown.
        # Typed as Any here to avoid a circular import with pointtapi_entities.
        self.boost_session: Any = None

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
