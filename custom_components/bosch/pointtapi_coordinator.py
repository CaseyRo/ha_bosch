"""DataUpdateCoordinator for Bosch POINTTAPI: single poll, path-keyed payload.

Steady-state polling uses the bulk endpoint (one POST per 30 paths) with the
v0.33 sequential reference walk kept as both discovery mechanism and fallback.
Bulk endpoint behavior observed by serbanb11/homecom_alt and verified against
a live RRC2 gateway on 2026-06-05 — see docs/pointtapi-api.md.
"""
from __future__ import annotations

import asyncio
import logging
import time
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
    "/zones",  # expanded to one walk root per discovered zone in _fetch_paths
    "/energy",
    "/energy/history",
    "/energy/historyHourly",
    "/heatSources",
    "/solarCircuits/sc1",
    # Alerts list (type errorList). Optional-path tolerance applies; the
    # live CT200 serves it (verified 2026-06-05, see boost-probe-notes.md).
    "/notifications",
    # Away mode leaf — not reachable via the /system/sensors or
    # /system/appliance reference walks (writeable: 1, verified 2026-06-05).
    "/system/awayMode/enabled",
    "/programs",
    "/devices",
]
REFERENCES_KEY = "references"
ID_KEY = "id"

HISTORY_HOURLY_PATH = "/energy/historyHourly"
# Re-run the discovery reference walk at most this often so resources that
# appear later (e.g. solar enabled by an installer) get picked up.
REDISCOVERY_INTERVAL = 24 * 3600
# Throttle the bulk-failure WARNING to once per hour; repeats log at DEBUG.
BULK_WARN_INTERVAL = 3600


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


async def _zone_roots(client: PoinTTAPIClient) -> list[str]:
    """GET /zones and return one walk root per zone ("/zones/zn1", ...).

    Multi-zone gateways (ETRVs paired to rooms) list every zone here; walking
    each one as a root gives it the same fetch depth zn1 always had. Falls
    back to ["/zones/zn1"] when the listing is missing or fails, preserving
    single-zone behavior.
    """
    try:
        resp = await client.get("/zones")
        if isinstance(resp, dict):
            roots = [
                r[ID_KEY]
                for r in (resp.get(REFERENCES_KEY) or [])
                if isinstance(r, dict) and r.get(ID_KEY)
            ]
            if roots:
                return roots
    except ConfigEntryAuthFailed:
        _LOGGER.debug("POINTTAPI 401/403 on /zones, assuming single zone")
    except Exception as err:
        _LOGGER.debug(
            "POINTTAPI /zones listing unavailable (%s), assuming single zone", err
        )
    return ["/zones/zn1"]


async def _program_roots(client: PoinTTAPIClient) -> list[str]:
    """GET /programs and return one walk root per listed program.

    Mirrors zone-root expansion: use the listing references as source-of-truth
    and fall back to the top-level /programs root when discovery is missing or
    unavailable.
    """
    try:
        resp = await client.get("/programs")
        if isinstance(resp, dict):
            roots = [
                r[ID_KEY]
                for r in (resp.get(REFERENCES_KEY) or [])
                if isinstance(r, dict) and r.get(ID_KEY)
            ]
            if roots:
                return roots
    except ConfigEntryAuthFailed:
        _LOGGER.debug("POINTTAPI 401/403 on /programs, using /programs root")
    except Exception as err:
        _LOGGER.debug(
            "POINTTAPI /programs listing unavailable (%s), using /programs root", err
        )
    return ["/programs"]


async def _device_roots(client: PoinTTAPIClient) -> list[str]:
    """GET /devices and return one walk root per listed device.

    Mirrors zone/program root expansion and falls back to the top-level
    /devices root when discovery is missing or unavailable.
    """
    try:
        resp = await client.get("/devices")
        if isinstance(resp, dict):
            roots = [
                r[ID_KEY]
                for r in (resp.get(REFERENCES_KEY) or [])
                if isinstance(r, dict) and r.get(ID_KEY)
            ]
            if roots:
                return roots
    except ConfigEntryAuthFailed:
        _LOGGER.debug("POINTTAPI 401/403 on /devices, using /devices root")
    except Exception as err:
        _LOGGER.debug(
            "POINTTAPI /devices listing unavailable (%s), using /devices root", err
        )
    return ["/devices"]


async def _fetch_paths(client: PoinTTAPIClient) -> dict[str, Any]:
    """Fetch root paths and one level of references; return path -> response dict.

    Only /gateway auth failures are treated as real token problems (re-raised as
    ConfigEntryAuthFailed). All other paths: 403/401 is logged and skipped, since
    some sub-resources may be forbidden without the token being invalid.
    """
    data: dict[str, Any] = {}
    roots: list[str] = []
    for r in POINTTAPI_COORDINATOR_ROOTS:
        if r == "/zones":
            roots.extend(await _zone_roots(client))
            continue
        if r == "/programs":
            roots.extend(await _program_roots(client))
            continue
        if r == "/devices":
            roots.extend(await _device_roots(client))
            continue
        roots.append(r)
    for root in roots:
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
        # Native-boost probe verdict cache (set by the boost switch's probe
        # ladder; surfaced in diagnostics). None = not yet probed.
        self.boost_probe_result: dict[str, Any] | None = None
        # Bulk polling state: path set discovered by the reference walk,
        # monotonic timestamps for rediscovery and warning throttling.
        self._bulk_paths: list[str] = []
        self._last_discovery: float = 0.0
        self._bulk_warned_at: float | None = None

    @property
    def client(self) -> PoinTTAPIClient:
        """Return the POINTTAPI client for PUT calls from entities."""
        return self._client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch path-keyed payload; raise ConfigEntryAuthFailed on 401/403, UpdateFailed on connection error."""
        try:
            async with asyncio.timeout(120):
                return await self._fetch()
        except ConfigEntryAuthFailed:
            raise
        except UpdateFailed:
            raise
        except TimeoutError as err:
            raise UpdateFailed("POINTTAPI update timed out") from err
        except Exception as err:
            _LOGGER.warning("POINTTAPI coordinator update failed: %s", err)
            raise UpdateFailed(f"POINTTAPI update failed: {err}") from err

    async def _fetch(self) -> dict[str, Any]:
        """Discovery walk (first refresh / every 24h) or bulk steady state.

        The data shape ({path: response}) is identical on both routes, so
        entities never see the difference. Any wholesale bulk failure falls
        back to the sequential walk for the cycle — v0.33 behavior.
        """
        now = time.monotonic()
        if not self._bulk_paths or now - self._last_discovery >= REDISCOVERY_INTERVAL:
            data = await _fetch_paths(self._client)
            # The paginated historyHourly resource stays on sequential GETs
            # (bulk resourcePaths carry no query strings).
            self._bulk_paths = [p for p in data if p != HISTORY_HOURLY_PATH]
            self._last_discovery = now
            return data

        try:
            data = await self._client.bulk(self._bulk_paths)
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            self._log_bulk_failure(err)
            return await _fetch_paths(self._client)
        if not data:
            # An all-paths-failed envelope would wipe entity state; treat as
            # a wholesale failure instead.
            self._log_bulk_failure("empty bulk result")
            return await _fetch_paths(self._client)
        _LOGGER.debug(
            "POINTTAPI bulk steady state: %d/%d paths returned",
            len(data), len(self._bulk_paths),
        )

        if HISTORY_HOURLY_PATH in POINTTAPI_COORDINATOR_ROOTS:
            try:
                merged = await _fetch_history_hourly_all(self._client)
                if isinstance(merged, dict):
                    data[HISTORY_HOURLY_PATH] = merged
            except ConfigEntryAuthFailed:
                _LOGGER.debug("POINTTAPI 401/403 on %s, skipping", HISTORY_HOURLY_PATH)
            except Exception as err:
                _LOGGER.debug(
                    "POINTTAPI optional path %s not available: %s",
                    HISTORY_HOURLY_PATH, err,
                )
        return data

    def _log_bulk_failure(self, err: Any) -> None:
        """WARNING at most once per BULK_WARN_INTERVAL, DEBUG otherwise."""
        now = time.monotonic()
        if self._bulk_warned_at is None or now - self._bulk_warned_at >= BULK_WARN_INTERVAL:
            self._bulk_warned_at = now
            _LOGGER.warning(
                "POINTTAPI bulk fetch failed (%s); falling back to sequential GETs", err
            )
        else:
            _LOGGER.debug(
                "POINTTAPI bulk fetch failed (%s); falling back to sequential GETs", err
            )
