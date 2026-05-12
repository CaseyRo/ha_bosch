## Context

The boost surface today, after the v0.30.0 workaround landed and v0.31.0 reshuffled devices:

- `switch.pointtapi_boost` (entity class `BoschPoinTTAPIBoostSwitchEntity` in `pointtapi_entities.py:870-1010`) — implements the workaround. `async_turn_on` reads `/heatingCircuits/hc1/boostTemperature` from coordinator data, remembers the current `zones/zn1/userMode`, and PUTs `userMode=manual` + `manualTemperatureHeating={boost_temp}` to Bosch. `async_turn_off` PUTs the remembered `userMode` back. There's a `_boost_set_by_us` flag to prevent the coordinator's next poll from clobbering `_is_on` between the PUT and the API's eventual-consistency catch-up.
- `sensor.pointtapi_boost_remaining_time` (a description in the `_pointtapi_sensor_descriptions()` tuple, no `value_fn`) — reads `/heatingCircuits/hc1/boostRemainingTime` via the default path-based value lookup. Since the workaround never reaches Bosch's boost machinery, this is always 0.
- `number.pointtapi_boost_duration` and `number.pointtapi_boost_temperature` — read/write Bosch's `/heatingCircuits/hc1/boostDuration` and `/boostTemperature`. They store the user's intent on Bosch's side; the workaround uses `boostTemperature` (good) but ignores `boostDuration` (the bug this change fixes).

`PoinTTAPIDataUpdateCoordinator` (`pointtapi_coordinator.py`) is a standard `DataUpdateCoordinator` with a `client: PoinTTAPIClient` attribute. No state lives on it today beyond the client and the polled data dict.

HA's `async_call_later(hass, delay_seconds, action)` returns a cancel callable that runs the action after `delay_seconds`. Cancelling is by calling the returned callable.

## Goals / Non-Goals

**Goals:**
- Boost switch auto-flips off after `boostDuration` hours when triggered from HA.
- Remaining-time sensor counts down meaningfully during an HA-triggered boost.
- Cancellation works: manual `async_turn_off` cancels the pending auto-off so it doesn't fire stale.
- No regression to existing behavior: switch still toggles correctly, zone restoration still works, no new error paths.

**Non-Goals:**
- No persistence of the boost timer across HA restarts. (Single missed auto-off after a restart is acceptable.)
- No coordination with EasyControl-app-triggered boosts. If a user starts boost in the app *and* in HA, the app's session and our session are independent — our local timer doesn't know about the app's.
- No new entities, no entity_id renames, no translation changes.
- No Bosch-side boost endpoint (still 403). The workaround stays as the implementation.
- No backfill of historical boost sessions for the recorder. Long-term statistics on the remaining-time sensor will see a jagged transition from "always 0" to "real countdown" — acceptable.

## Decisions

### 1. State location: a `BoostSession` dataclass on the coordinator

Add to `pointtapi_entities.py` (since `BoostSession` is consumed by both the switch and the sensor's `value_fn`):

```python
@dataclass
class BoostSession:
    started_at: datetime  # UTC
    duration_hours: float

    @property
    def remaining_minutes(self) -> float:
        end = self.started_at + timedelta(hours=self.duration_hours)
        return max(0.0, (end - dt_util.utcnow()).total_seconds() / 60.0)
```

Add to `PoinTTAPIDataUpdateCoordinator` (`pointtapi_coordinator.py`):

```python
self.boost_session: BoostSession | None = None
```

Set by the switch on `async_turn_on`. Cleared by the switch on `async_turn_off` (manual *or* auto). Read by the sensor's `value_fn`.

**Why on the coordinator:** the switch and sensor both have a reference to `self.coordinator`. Putting the session there is the lowest-ceremony shared state. No `hass.data` pollution, no entity-id-based lookup, no platform-coupling.

**Alternatives considered:** (a) `hass.data[DOMAIN][entry_id]["boost_session"]` — works but is more typing and obscures the lifecycle. (b) An entity attribute on the switch + a sensor that looks up the switch by entity_id — fragile (entity_id can be renamed by the user). (c) A separate `BoostManager` singleton — over-engineered for a 30-line behavior.

### 2. Sensor reads session via injection into the data dict

The existing `BoschPoinTTAPISensorEntity._handle_coordinator_update` does:

```python
data = self.coordinator.data or {}
if desc.value_fn is not None:
    self._native_value = desc.value_fn(data)
```

The `value_fn` only sees `data`, not the coordinator. To give the boost sensor access to the session without breaking the signature, inject the session into the dict before calling `value_fn`:

```python
data = self.coordinator.data or {}
# Inject ephemeral runtime state under a synthetic key for value_fn consumers.
session = getattr(self.coordinator, "boost_session", None)
data_with_state = {**data, "__boost_session__": session} if session is not None else data
if desc.value_fn is not None:
    self._native_value = desc.value_fn(data_with_state)
```

The synthetic key uses `__double_underscore__` prefix to mark it as internal; real Bosch paths all start with `/`.

The boost sensor's `value_fn` becomes:

```python
def _boost_remaining_minutes(data):
    session = data.get("__boost_session__")
    if session is not None:
        return session.remaining_minutes
    # No HA-triggered session — fall back to Bosch's real value (may be nonzero
    # if user triggered boost from the EasyControl app; in our workaround it's 0)
    return _val(data, "/heatingCircuits/hc1/boostRemainingTime")
```

**Alternatives considered:** (a) Change `value_fn` signature to accept the entity or coordinator — bigger refactor, touches every existing description. (b) Subclass the sensor entity for boost specifically — adds a class for one behavior. The dict-injection is the smallest change.

### 3. Auto-off uses `async_call_later`, with a cancel handle stored on the switch entity

```python
self._auto_off_cancel: Callable[[], None] | None = None

async def async_turn_on(self, **kwargs):
    duration_h = float(_val(self.coordinator.data or {}, "/heatingCircuits/hc1/boostDuration") or 2.0)
    boost_temp = _val(self.coordinator.data or {}, "/heatingCircuits/hc1/boostTemperature") or 26.0
    self._pre_boost_mode = _val(self.coordinator.data or {}, "/zones/zn1/userMode") or "clock"
    await self.coordinator.client.put("/zones/zn1/userMode", "manual")
    await self.coordinator.client.put("/zones/zn1/manualTemperatureHeating", float(boost_temp))
    # Schedule auto-off
    self.coordinator.boost_session = BoostSession(
        started_at=dt_util.utcnow(),
        duration_hours=duration_h,
    )
    self._auto_off_cancel = async_call_later(
        self.hass,
        duration_h * 3600.0,
        self._auto_off_callback,
    )
    self._boost_set_by_us = True
    self._is_on = True
    self.async_write_ha_state()
    await self.coordinator.async_request_refresh()

async def _auto_off_callback(self, _now):
    _LOGGER.info("POINTTAPI boost auto-off after %.1f hours", self.coordinator.boost_session.duration_hours if self.coordinator.boost_session else 0)
    self._auto_off_cancel = None  # already fired, no cancel needed
    await self.async_turn_off()

async def async_turn_off(self, **kwargs):
    if self._auto_off_cancel is not None:
        self._auto_off_cancel()
        self._auto_off_cancel = None
    self.coordinator.boost_session = None
    # ...rest of existing turn_off body (restore userMode etc.)
```

`async_call_later` returns the cancel handle. Calling it twice is safe (HA's cancel handlers are idempotent on already-fired timers).

**Edge case: rapid toggle.** If the user toggles off + on quickly, `async_turn_off` cancels the pending timer, then `async_turn_on` creates a new one. No leak.

**Edge case: auto-off fires after manual off.** Can't happen — manual off cancels the handle. If somehow a fire-and-cancel race did happen, `async_turn_off` is idempotent on `_is_on=False` (the existing implementation handles repeated off calls).

### 4. Duration source = current `boostDuration` value at turn-on time, not at turn-off time

The duration is captured ONCE when the switch is turned on. If the user changes `number.pointtapi_boost_duration` mid-boost, the active session keeps its original duration. They'd need to toggle the switch off+on to apply the new duration.

**Why:** simpler. The alternative (re-arming the timer when duration changes) requires watching the number entity for changes, which adds machinery for an unlikely use case.

### 5. Restart behavior: drop the timer, leave the zone where it is

On HA restart:
- The switch entity is re-created from scratch — `_auto_off_cancel = None`, `coordinator.boost_session = None`.
- Bosch's state still reflects zone=manual + temperatureManual=26 °C (our writes from before).
- The switch's `_handle_coordinator_update` will detect zone in manual at boost-ish temperature and the `_boost_set_by_us` flag is False, so it reads the live `/heatingCircuits/hc1/boostMode` value (which is `"off"` since Bosch never knew) → `_is_on = False`.
- So after restart, the switch reads "off" while the zone is still warm at 26 °C. The user has to either notice and turn it off via HA (which restores the prior userMode) or wait for the next clock-mode setpoint change to override the manual setpoint.

**Documented as a known limitation.** A future change could persist the session via `hass.helpers.storage.Store` to survive restarts, but the complexity isn't worth it for v0.33.0.

### 6. UTC for `started_at`

`dt_util.utcnow()` rather than `datetime.now()`. Makes the math timezone-safe and matches HA convention.

## Risks / Trade-offs

- **Risk: `async_call_later` doesn't fire if HA is paused or the event loop is blocked at the scheduled time.** → HA's scheduler is reliable in normal operation; pathological cases (`asyncio.sleep` hangs, etc.) would leave the boost on, but the user can still toggle manually. Acceptable.
- **Risk: zone display lags after auto-off.** Same eventual-consistency concern as the manual turn-off path. The existing `_boost_set_by_us` mechanism already covers this (sets `_is_on` immediately, waits for coordinator to catch up).
- **Risk: synthetic countdown disagrees with Bosch's value.** Possible if user triggered boost in the EasyControl app then opened HA. Our code prefers the local session; if no session exists, falls back to Bosch's value. Both paths can't be active simultaneously (a local session means we triggered it ourselves; if the app started it, we wouldn't have a session).
- **Trade-off: 2-hour default if `boostDuration` is missing.** Same default as the v0.30.0 workaround for `boostTemperature`. Could choose 1.0, but Bosch's UI default is 2.0 and matches the current `number` entity's stored value.
- **Trade-off: `BoostSession` is a runtime singleton per entry — not multi-zone-safe.** Today the integration is hard-coded to `zn1`/`hc1`, so this is fine. The v0.31.0 multi-zone work would, when wired up, need one session per zone. Out of scope here.

## Migration Plan

- **Deploy:** ship as v0.33.0. HACS picks it up.
- **First-restart behavior:** if a user has a boost active (zone in manual at boost_temp) from before the upgrade, the integration sees switch=off (Bosch says no boost) — same as today's restart behavior. No regression.
- **Rollback:** revert to v0.32.0. Sensor reverts to reading Bosch's permanent zero. Switch reverts to no-auto-off. Nothing breaks; users lose the new behavior.

## Open Questions

- *Closed:* should we persist the session across restarts? — No, simpler to drop it.
- *Closed:* should auto-off cancellation suppress the restore-userMode PUT? — No, that's the correct off behavior. Cancel only the timer; let off do its job.
- *Remaining:* should the EasyControl-app-triggered boost case attempt to start a synthetic countdown using Bosch's reported `boostRemainingTime` value (mirroring the timer)? — Not in this change. If users want it, follow-up.
