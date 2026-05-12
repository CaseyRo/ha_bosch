## 1. Coordinator state surface

- [x] 1.1 Add `boost_session: BoostSession | None = None` attribute to `PoinTTAPIDataUpdateCoordinator.__init__` in `custom_components/bosch/pointtapi_coordinator.py`.
- [x] 1.2 Import `BoostSession` lazily inside `__init__` (or use `Any` typing) to avoid a circular import with `pointtapi_entities.py`.

## 2. BoostSession dataclass

- [x] 2.1 Define `@dataclass(frozen=False)` `BoostSession` in `custom_components/bosch/pointtapi_entities.py` with fields `started_at: datetime` and `duration_hours: float`, plus a `remaining_minutes` property computed as `max(0.0, ((started_at + timedelta(hours=duration_hours)) - dt_util.utcnow()).total_seconds() / 60.0)`.

## 3. Boost switch auto-off

- [x] 3.1 Add `_auto_off_cancel: Callable[[], None] | None = None` to `BoschPoinTTAPIBoostSwitchEntity.__init__`.
- [x] 3.2 In `async_turn_on`, after the userMode/manualTemperatureHeating PUTs succeed:
  - Read `/heatingCircuits/hc1/boostDuration` from coordinator data (float, default 2.0)
  - Set `self.coordinator.boost_session = BoostSession(started_at=dt_util.utcnow(), duration_hours=duration_h)`
  - Schedule `self._auto_off_cancel = async_call_later(self.hass, duration_h * 3600.0, self._auto_off_callback)`
- [x] 3.3 Add `async def _auto_off_callback(self, _now)` that logs the auto-off, sets `self._auto_off_cancel = None` (already fired), and calls `await self.async_turn_off()`.
- [x] 3.4 In `async_turn_off` prologue: if `self._auto_off_cancel is not None`, call it (cancel) and set to None. Then `self.coordinator.boost_session = None`. Keep the existing userMode-restore logic intact.
- [x] 3.5 Import `async_call_later` from `homeassistant.helpers.event` and `dt_util` from `homeassistant.util.dt` (already imported, verify).

## 4. Synthetic remaining-time sensor

- [x] 4.1 Locate the existing `boost_remaining_time` description in `_pointtapi_sensor_descriptions()`. Add `value_fn=_boost_remaining_minutes`.
- [x] 4.2 Define `_boost_remaining_minutes(data: dict) -> float | None` at module scope: returns `data["__boost_session__"].remaining_minutes` when present, else `_val(data, "/heatingCircuits/hc1/boostRemainingTime")`.
- [x] 4.3 In `BoschPoinTTAPISensorEntity._handle_coordinator_update`, before invoking `desc.value_fn(data)`, inject the synthetic key:
  - `session = getattr(self.coordinator, "boost_session", None)`
  - `data = {**data, "__boost_session__": session} if session is not None else data`
- [x] 4.4 Verify the description's `native_unit_of_measurement` stays `UnitOfTime.MINUTES` and `device_class` stays `SensorDeviceClass.DURATION` (the new value is in minutes, matching).

## 5. Lint + smoke tests

- [x] 5.1 `uvx ruff check custom_components/bosch` passes.
- [x] 5.2 Add tests at `unittests/test_pointtapi_boost.py`:
  - `BoostSession(started_at=utcnow(), duration_hours=2.0).remaining_minutes ≈ 120.0`
  - `BoostSession(started_at=utcnow() - timedelta(hours=1), duration_hours=2.0).remaining_minutes ≈ 60.0`
  - `BoostSession(started_at=utcnow() - timedelta(hours=3), duration_hours=2.0).remaining_minutes == 0.0`
  - `_boost_remaining_minutes({"__boost_session__": session})` matches the session's remaining
  - `_boost_remaining_minutes({"/heatingCircuits/hc1/boostRemainingTime": {"value": 42.5}})` returns 42.5

## 6. Live verification on user's HA box

- [x] 6.1 Bump `manifest.json` to `0.33.0`.
- [x] 6.2 `bash ./sync-to-ha.sh` and `docker restart homeassistant`.
- [x] 6.3 The current "stuck" boost session (started 2026-05-12 10:11) is gone after restart per the documented behavior — confirm `coordinator.boost_session is None` and `switch.pointtapi_boost == off`.
- [x] 6.4 Turn boost on via HA service call: `hass.services.call("switch", "turn_on", target={"entity_id": "switch.pointtapi_boost"})`. Confirm:
  - `switch.pointtapi_boost == "on"`
  - `sensor.pointtapi_boost_remaining_time` shows a positive value close to `boost_duration * 60` minutes
  - The value decreases on subsequent polls
- [x] 6.5 Wait ~3 minutes, confirm the remaining-time sensor is roughly 3 minutes lower than at 6.4.
- [x] 6.6 Manually turn boost off via service call. Confirm `boost_remaining_time` returns to `0.0` and the auto-off timer no longer fires (no log line about auto-off later in the day).

## 7. Release

- [ ] 7.1 Commit `v0.33.0: boost auto-off timer + synthetic remaining-time countdown`.
- [ ] 7.2 Tag `v0.33.0`, push master + tag.
- [ ] 7.3 `gh release create v0.33.0 --latest` with notes explaining the workaround story + the auto-off + the synthetic countdown.
- [ ] 7.4 Confirm CI green.

## 8. Archive

- [ ] 8.1 Sync `pointtapi-boost-behavior` to `openspec/specs/`.
- [ ] 8.2 Move change folder to `openspec/changes/archive/YYYY-MM-DD-boost-auto-off-and-countdown/`.
- [ ] 8.3 Push the archive commit.
