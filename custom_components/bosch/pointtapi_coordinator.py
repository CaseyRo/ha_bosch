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
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

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
# Hourly history does not need to be fetched with every 60-second state poll.
HISTORY_HOURLY_REFRESH_INTERVAL = 30 * 60
# Configuration, diagnostics, energy and device inventories change less often
# than temperatures and operating modes.
SLOW_RESOURCE_REFRESH_INTERVAL = 5 * 60
SLOW_RESOURCE_PREFIXES = (
    "/gateway",
    "/energy",
    "/solarCircuits",
    "/devices",
    "/programs",
    "/system/appliance",
)
FAST_DEVICE_RESOURCE_MARKERS = (
    "/devices/list",
    "/etrv/",
    "/thermostat/",
)
# Re-run the discovery reference walk at most this often so resources that
# appear later (e.g. solar enabled by an installer) get picked up.
REDISCOVERY_INTERVAL = 24 * 3600
# Throttle the bulk-failure WARNING to once per hour; repeats log at DEBUG.
BULK_WARN_INTERVAL = 3600
DISCOVERY_OPTIONAL_TIMEOUT = 8


async def _get_discovery_path(
    client: PoinTTAPIClient, path: str, *, timeout: float = DISCOVERY_OPTIONAL_TIMEOUT
) -> Any:
    """Fetch a discovery path without letting an optional resource stall startup."""
    try:
        async with asyncio.timeout(timeout):
            return await client.get(path)
    except TimeoutError:
        _LOGGER.warning(
            "POINTTAPI discovery path %s timed out after %ss; skipping it for this refresh",
            path,
            timeout,
        )
        return None


def _is_slow_resource(path: str) -> bool:
    """Return whether a resource can use the slower polling cadence."""
    if path.startswith("/devices/") and any(
        marker in path for marker in FAST_DEVICE_RESOURCE_MARKERS
    ):
        return False
    return path == "/notifications" or path.startswith(SLOW_RESOURCE_PREFIXES)


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


async def _discover_roots(
    client: PoinTTAPIClient, root: str, fallback: str
) -> list[str]:
    """Return reference roots from a listing, or its static fallback."""
    try:
        resp = await _get_discovery_path(client, root)
        if isinstance(resp, dict):
            roots = [
                r[ID_KEY]
                for r in (resp.get(REFERENCES_KEY) or [])
                if isinstance(r, dict) and r.get(ID_KEY)
            ]
            if roots:
                return roots
    except ConfigEntryAuthFailed:
        _LOGGER.debug("POINTTAPI 401/403 on %s, using %s", root, fallback)
    except Exception as err:
        _LOGGER.debug(
            "POINTTAPI %s listing unavailable (%s), using %s", root, err, fallback
        )
    return [fallback]


async def _zone_roots(client: PoinTTAPIClient) -> list[str]:
    """Return one walk root per zone, with a zn1 fallback."""
    return await _discover_roots(client, "/zones", "/zones/zn1")


async def _program_roots(client: PoinTTAPIClient) -> list[str]:
    """Return one walk root per listed program."""
    return await _discover_roots(client, "/programs", "/programs")


async def _device_roots(client: PoinTTAPIClient) -> list[str]:
    """Return one walk root per listed device."""
    return await _discover_roots(client, "/devices", "/devices")


async def _fetch_paths(
    client: PoinTTAPIClient, *, include_history_hourly: bool = True
) -> dict[str, Any]:
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
    roots = list(dict.fromkeys(roots))
    seen_references: set[str] = set()
    for root in roots:
        if root == "/energy/historyHourly" and not include_history_hourly:
            continue
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
            root_timeout = 30 if root == "/gateway" else DISCOVERY_OPTIONAL_TIMEOUT
            resp = await _get_discovery_path(client, root, timeout=root_timeout)
            if not isinstance(resp, dict):
                continue
            data[root] = resp
            refs = resp.get(REFERENCES_KEY) or []
            for ref in refs:
                ref_id = ref.get(ID_KEY) if isinstance(ref, dict) else None
                if not ref_id or ref_id in seen_references:
                    continue
                seen_references.add(ref_id)
                try:
                    sub = await _get_discovery_path(client, ref_id)
                    if isinstance(sub, dict):
                        data[ref_id] = sub
                        # Fetch nested refEnum leaves such as
                        # device -> etrv -> childLock -> enabled.
                        if sub.get("type") == "refEnum":
                            for r2 in sub.get(REFERENCES_KEY) or []:
                                r2_id = r2.get(ID_KEY) if isinstance(r2, dict) else None
                                if not r2_id or r2_id in data:
                                    continue
                                try:
                                    sub2 = await _get_discovery_path(client, r2_id)
                                    if isinstance(sub2, dict):
                                        data[r2_id] = sub2
                                        if sub2.get("type") == "refEnum":
                                            for r3 in sub2.get(REFERENCES_KEY) or []:
                                                r3_id = r3.get(ID_KEY) if isinstance(r3, dict) else None
                                                if not r3_id or r3_id in data:
                                                    continue
                                                try:
                                                    leaf = await _get_discovery_path(client, r3_id)
                                                    if isinstance(leaf, dict):
                                                        data[r3_id] = leaf
                                                except ConfigEntryAuthFailed:
                                                    _LOGGER.debug("POINTTAPI 401/403 on ref %s, skipping", r3_id)
                                                except Exception:
                                                    continue
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
        # Lock for serializing boost zone updates across rapid toggles.
        self._boost_lock = asyncio.Lock()
        self._boost_selected_zones: set[int] | None = None
        # Tracks an in-flight HA-triggered boost session. The boost switch sets
        # this on turn-on and clears it on turn-off; the boost_remaining_time
        # sensor reads it to derive a synthetic countdown.
        # Typed as Any here to avoid a circular import with pointtapi_entities.
        self.boost_session: Any = None
        self._auto_off_cancels: dict[int, Any] = {}
        # Native-boost probe verdict cache (set by the boost switch's probe
        # ladder; surfaced in diagnostics). None = not yet probed.
        self.boost_probe_result: dict[str, Any] | None = None
        # Bulk polling state: path set discovered by the reference walk,
        # monotonic timestamps for rediscovery and warning throttling.
        self._bulk_paths: list[str] = []
        self._last_discovery: float = 0.0
        self._bulk_warned_at: float | None = None
        self._history_hourly_data: dict[str, Any] | None = None
        self._last_history_hourly_fetch: float = 0.0
        self._slow_bulk_paths: list[str] = []
        self._fast_bulk_paths: list[str] = []
        self._slow_data: dict[str, Any] = {}
        self._last_slow_fetch: float = 0.0

    @property
    def client(self) -> PoinTTAPIClient:
        """Return the POINTTAPI client for PUT calls from entities."""
        return self._client

    async def _confirm_native_active(self) -> bool:
        """A native write counts only if the device reports boost active."""
        from .pointtapi_entities import _val

        await self.async_refresh()
        data = self.data or {}
        if _val(data, "/heatingCircuits/hc1/boostMode") == "on":
            return True
        rem = _val(data, "/heatingCircuits/hc1/boostRemainingTime")
        return isinstance(rem, (int, float)) and rem > 0

    async def _probe_native_boost(
        self, boost_temp: float, duration_h: float, zones: list[int]
    ) -> str:
        """Run the probe ladder once; cache and return the working route."""
        from .pointtapi_entities import (
            ROUTE_DIRECT,
            ROUTE_FALLBACK,
            ROUTE_SHORTCUT,
            _val,
        )

        rungs: list[dict[str, Any]] = []
        try:
            if _val(
                self.data or {}, "/heatingCircuits/hc1/boostMode"
            ) == "on":
                await self.client.put(
                    "/heatingCircuits/hc1/boostMode", "off"
                )
            await self.client.put(
                "/heatingCircuits/hc1/boostShortcut",
                [{
                    "mode": "on",
                    "temperature": float(boost_temp),
                    "duration": int(duration_h),
                    "zones": zones,
                }],
            )
            active = await self._confirm_native_active()
            rungs.append({"rung": ROUTE_SHORTCUT, "put": "accepted", "active": active})
            _LOGGER.debug("Boost probe rung boostShortcut: accepted, active=%s", active)
            if active:
                self.boost_probe_result = {
                    "route": ROUTE_SHORTCUT, "rungs": rungs,
                }
                return ROUTE_SHORTCUT
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            rungs.append({"rung": ROUTE_SHORTCUT, "error": str(err)})
            _LOGGER.debug("Boost probe rung boostShortcut failed: %s", err)
        try:
            await self.client.put(
                "/heatingCircuits/hc1/boostZones", [{"zones": zones}]
            )
            await self.client.put("/heatingCircuits/hc1/boostMode", "on")
            active = await self._confirm_native_active()
            rungs.append({"rung": ROUTE_DIRECT, "put": "accepted", "active": active})
            _LOGGER.debug("Boost probe rung boostMode: accepted, active=%s", active)
            if active:
                self.boost_probe_result = {
                    "route": ROUTE_DIRECT, "rungs": rungs,
                }
                return ROUTE_DIRECT
            await self.client.put("/heatingCircuits/hc1/boostMode", "off")
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            rungs.append({"rung": ROUTE_DIRECT, "error": str(err)})
            _LOGGER.debug("Boost probe rung boostMode failed: %s", err)

        self.boost_probe_result = {
            "route": ROUTE_FALLBACK, "rungs": rungs,
        }
        _LOGGER.info("Native boost unavailable, using manual-mode workaround")
        return ROUTE_FALLBACK

    async def _native_boost_on(
        self, route: str, boost_temp: float, duration_h: float, zones: list[int]
    ) -> bool:
        """Activate boost via the cached native route. True when confirmed."""
        from .pointtapi_entities import ROUTE_SHORTCUT, _val

        try:
            if route == ROUTE_SHORTCUT:
                if _val(
                    self.data or {}, "/heatingCircuits/hc1/boostMode"
                ) == "on":
                    await self.client.put(
                        "/heatingCircuits/hc1/boostMode", "off"
                    )
                await self.client.put(
                    "/heatingCircuits/hc1/boostShortcut",
                    [{
                        "mode": "on",
                        "temperature": float(boost_temp),
                        "duration": int(duration_h),
                        "zones": zones,
                    }],
                )
            else:
                await self.client.put(
                    "/heatingCircuits/hc1/boostZones", [{"zones": zones}]
                )
                await self.client.put(
                    "/heatingCircuits/hc1/boostMode", "on"
                )
            return await self._confirm_native_active()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning("Native boost ON via %s failed: %s", route, err)
            return False

    async def _native_boost_off(self, route: str, zones: list[int]) -> bool:
        """Update native Boost selection without touching zone user modes."""
        from .pointtapi_entities import ROUTE_SHORTCUT, _val

        try:
            if route == ROUTE_SHORTCUT:
                data = self.data or {}
                await self.client.put(
                    "/heatingCircuits/hc1/boostShortcut",
                    [{
                        "mode": "on" if zones else "off",
                        "temperature": float(
                            _val(data, "/heatingCircuits/hc1/boostTemperature") or 26.0
                        ),
                        "duration": int(
                            float(_val(data, "/heatingCircuits/hc1/boostDuration") or 2.0)
                        ),
                        "zones": zones,
                    }],
                )
            else:
                if zones:
                    await self.client.put(
                        "/heatingCircuits/hc1/boostZones", [{"zones": zones}]
                    )
                    await self.client.put(
                        "/heatingCircuits/hc1/boostMode", "on"
                    )
                else:
                    await self.client.put(
                        "/heatingCircuits/hc1/boostMode", "off"
                    )
            return True
        except ConfigEntryAuthFailed:
            if route == ROUTE_SHORTCUT:
                try:
                    if zones:
                        await self.client.put(
                            "/heatingCircuits/hc1/boostZones", [{"zones": zones}]
                        )
                        await self.client.put(
                            "/heatingCircuits/hc1/boostMode", "on"
                        )
                    else:
                        await self.client.put(
                            "/heatingCircuits/hc1/boostMode", "off"
                        )
                    return True
                except ConfigEntryAuthFailed:
                    pass
            raise
        except Exception as err:
            _LOGGER.warning("Native boost OFF via %s failed: %s", route, err)
            return False

    async def _refresh_boost_state(self, data: dict[str, Any]) -> dict[str, Any]:
        """Read the live native Boost state before changing its selection."""
        fresh = dict(data)
        for path in (
            "/heatingCircuits/hc1/boostMode",
            "/heatingCircuits/hc1/boostZones",
        ):
            response = await self.client.get(path)
            if isinstance(response, dict):
                fresh[path] = response
        self.data = fresh
        return fresh

    async def async_set_zone_boost(self, zone_id: int, enable: bool) -> None:
        """Turn boost on or off for a specified zone, serialized with an asyncio.Lock."""
        from .pointtapi_entities import (
            ROUTE_FALLBACK,
            ROUTE_SHORTCUT,
            BoostSession,
            _boost_zone_values,
            _path_writable,
            _val,
        )

        async with self._boost_lock:
            data = self.data or {}
            data = await self._refresh_boost_state(data)
            if enable and not (
                _path_writable(data, "/heatingCircuits/hc1/boostShortcut")
                and zone_id in _boost_zone_values(data, "allowedZones")
            ):
                raise HomeAssistantError("Boost is unavailable for this zone")

            boost_temp = _val(data, "/heatingCircuits/hc1/boostTemperature") or 26.0
            duration_h = float(
                _val(data, "/heatingCircuits/hc1/boostDuration") or 2.0
            )

            if self._boost_selected_zones is not None:
                base_zones = set(self._boost_selected_zones)
            else:
                base_zones = _boost_zone_values(data, "zones")

            if enable:
                active_zones = base_zones if _val(
                    data, "/heatingCircuits/hc1/boostMode"
                ) == "on" else set()
                target_zones = sorted(active_zones | {zone_id})
                probe = self.boost_probe_result
                try:
                    if probe is None:
                        route = await self._probe_native_boost(
                            boost_temp, duration_h, target_zones
                        )
                        native_ok = route != ROUTE_FALLBACK
                    elif probe.get("route") != ROUTE_FALLBACK:
                        route = probe["route"]
                        native_ok = await self._native_boost_on(
                            route, boost_temp, duration_h, target_zones
                        )
                    else:
                        native_ok = False
                except ConfigEntryAuthFailed:
                    raise
                except Exception as err:
                    _LOGGER.warning("Native boost attempt errored: %s", err)
                    native_ok = False

                if native_ok:
                    self.boost_session = None
                    _LOGGER.info(
                        "POINTTAPI native boost ON at %.1f°C for %.0f h (zones %s)",
                        float(boost_temp),
                        duration_h,
                        target_zones,
                    )
                    self._boost_selected_zones = set(target_zones)
                    await self.async_request_refresh()
                    self._boost_selected_zones = _boost_zone_values(
                        self.data or {}, "zones"
                    )
                    return

                # Fallback: manual mode workaround
                try:
                    zone_path = f"/zones/zn{zone_id}"
                    current_mode = _val(data, f"{zone_path}/userMode") or "clock"
                    if not hasattr(self, "_fallback_pre_boost_modes"):
                        self._fallback_pre_boost_modes: dict[int, str] = {}
                    self._fallback_pre_boost_modes[zone_id] = current_mode
                    await self.client.put(f"{zone_path}/userMode", "manual")
                    await self.client.put(
                        f"{zone_path}/manualTemperatureHeating", float(boost_temp)
                    )
                    self.boost_session = BoostSession(
                        started_at=dt_util.utcnow(),
                        duration_hours=duration_h,
                    )
                    if zone_id in self._auto_off_cancels:
                        self._auto_off_cancels.pop(zone_id)()

                    def _auto_off_cb(_now):
                        self._auto_off_cancels.pop(zone_id, None)
                        self.hass.async_create_task(
                            self.async_set_zone_boost(zone_id, False)
                        )

                    self._auto_off_cancels[zone_id] = async_call_later(
                        self.hass,
                        duration_h * 3600.0,
                        _auto_off_cb,
                    )
                    _LOGGER.info(
                        "POINTTAPI boost ON (fallback): zone=%s manual at %.1f°C",
                        zone_id,
                        float(boost_temp),
                    )
                    self._boost_selected_zones = set(target_zones)
                    await self.async_request_refresh()
                    self._boost_selected_zones = _boost_zone_values(
                        self.data or {}, "zones"
                    )
                except ConfigEntryAuthFailed:
                    raise
                except Exception as err:
                    await self.async_request_refresh()
                    raise HomeAssistantError(
                        f"POINTTAPI boost turn_on failed: {err}"
                    ) from err
            else:
                target_zones = sorted(base_zones - {zone_id})
                probe = self.boost_probe_result
                route = None
                if probe is not None and probe.get("route") != ROUTE_FALLBACK:
                    route = probe.get("route")
                elif (
                    _val(data, "/heatingCircuits/hc1/boostMode") == "on"
                    and _path_writable(data, "/heatingCircuits/hc1/boostShortcut")
                ):
                    route = ROUTE_SHORTCUT

                if route is not None and self.boost_session is None:
                    if await self._native_boost_off(route, target_zones):
                        self._boost_selected_zones = set(target_zones)
                        await self.async_request_refresh()
                        self._boost_selected_zones = _boost_zone_values(
                            self.data or {}, "zones"
                        )
                        return

                # Fallback disable
                if zone_id in self._auto_off_cancels:
                    self._auto_off_cancels.pop(zone_id)()
                self.boost_session = None
                try:
                    zone_path = f"/zones/zn{zone_id}"
                    restore_mode = (
                        getattr(self, "_fallback_pre_boost_modes", {}).pop(
                            zone_id, None
                        )
                        or "clock"
                    )
                    await self.client.put(
                        f"{zone_path}/userMode", restore_mode
                    )
                    self._boost_selected_zones = set(target_zones)
                    await self.async_request_refresh()
                    self._boost_selected_zones = _boost_zone_values(
                        self.data or {}, "zones"
                    )
                except ConfigEntryAuthFailed:
                    raise
                except Exception as err:
                    await self.async_request_refresh()
                    raise HomeAssistantError(
                        f"POINTTAPI boost turn_off failed: {err}"
                    ) from err

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
            # Keep startup focused on current device state. Historical hourly
            # energy data is fetched by the next regular poll.
            data = await _fetch_paths(
                self._client, include_history_hourly=False
            )
            # The paginated historyHourly resource stays on sequential GETs
            # (bulk resourcePaths carry no query strings).
            self._bulk_paths = [p for p in data if p != HISTORY_HOURLY_PATH]
            self._slow_bulk_paths = [p for p in self._bulk_paths if _is_slow_resource(p)]
            self._fast_bulk_paths = [p for p in self._bulk_paths if not _is_slow_resource(p)]
            self._slow_data = {
                p: data[p] for p in self._slow_bulk_paths if p in data
            }
            self._last_slow_fetch = now
            self._last_discovery = now
            history = data.get(HISTORY_HOURLY_PATH)
            if isinstance(history, dict):
                self._history_hourly_data = history
                self._last_history_hourly_fetch = now
            return data

        slow_due = (
            not self._slow_data
            or now - self._last_slow_fetch >= SLOW_RESOURCE_REFRESH_INTERVAL
        )
        bulk_paths = self._fast_bulk_paths + (
            self._slow_bulk_paths if slow_due else []
        )
        if not bulk_paths:
            data = {}
        else:
            try:
                data = await self._client.bulk(bulk_paths)
            except ConfigEntryAuthFailed:
                raise
            except Exception as err:
                self._log_bulk_failure(err)
                return await _fetch_paths(self._client)
        if not data and bulk_paths:
            # An all-paths-failed envelope would wipe entity state; treat as
            # a wholesale failure instead.
            self._log_bulk_failure("empty bulk result")
            return await _fetch_paths(self._client)
        if slow_due:
            self._slow_data.update(
                {p: data[p] for p in self._slow_bulk_paths if p in data}
            )
            self._last_slow_fetch = now
        data = {**self._slow_data, **data}
        _LOGGER.debug(
            "POINTTAPI bulk steady state: %d/%d paths returned",
            len(data), len(self._bulk_paths),
        )

        if (
            self._history_hourly_data is None
            or now - self._last_history_hourly_fetch
            >= HISTORY_HOURLY_REFRESH_INTERVAL
        ):
            try:
                merged = await _fetch_history_hourly_all(self._client)
                if isinstance(merged, dict):
                    self._history_hourly_data = merged
                    self._last_history_hourly_fetch = now
            except ConfigEntryAuthFailed:
                _LOGGER.debug("POINTTAPI 401/403 on %s, keeping cached data", HISTORY_HOURLY_PATH)
            except Exception as err:
                _LOGGER.debug(
                    "POINTTAPI optional path %s not available: %s",
                    HISTORY_HOURLY_PATH, err,
                )
        if self._history_hourly_data is not None:
            data[HISTORY_HOURLY_PATH] = self._history_hourly_data
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
