## Why

The boost switch in v0.30.0+ is a workaround for `/heatingCircuits/hc1/boostMode` returning 403 under the POINTTAPI cloud scope: turning boost ON puts the zone into manual mode at `boostTemperature`. That part works. But the workaround has two missing halves that the real Bosch boost would handle:

1. **No auto-off.** The Bosch app's boost auto-stops after the configured `boostDuration` (e.g. 2 hours). Our switch just leaves the zone in manual mode forever until something else toggles it off. A user (me, today, 2026-05-12 ~10:11) turned boost on expecting the usual ~2 h behavior; an hour later the zone is still at 26 °C with no automatic shut-off in sight. The configured `boostDuration` value just sits there ignored.
2. **No countdown.** `sensor.pointtapi_boost_remaining_time` reads Bosch's `/heatingCircuits/hc1/boostRemainingTime`, which stays at `0.0` because Bosch never registered an actual boost (the workaround never reached Bosch's boost endpoint). So the sensor is permanently zero whether boost is active or not — useless for "when does this stop?" automations or dashboard cards.

Both halves of the fix are local-state-only: an in-memory timer for auto-off and a derived sensor reading from that timer. No new API calls, no new Bosch interaction.

## What Changes

- **Boost switch auto-off (NEW behavior).** When `BoschPoinTTAPIBoostSwitchEntity.async_turn_on` fires, the switch reads the current `/heatingCircuits/hc1/boostDuration` value from coordinator data (hours, default 2.0), records a `BoostSession(started_at=now, duration_hours=N)` on the coordinator, and schedules an `async_call_later` callback to call `async_turn_off` after `N * 3600` seconds. When `async_turn_off` is called manually, the pending callback is cancelled and the session cleared. Result: boost behaves like Bosch's real boost — switches off automatically after the configured duration unless the user explicitly turns it off first.
- **Synthetic countdown (MODIFIED behavior).** `sensor.pointtapi_boost_remaining_time` keeps its entity_id and translation_key, but its `value_fn` now prefers the coordinator's `boost_session.remaining_minutes` when present (i.e. an HA-triggered boost is active). Falls back to Bosch's `/heatingCircuits/hc1/boostRemainingTime` value when no local session exists — so a boost triggered from the EasyControl app still works (Bosch's value will be nonzero in that case if their endpoint reports it).
- **Restart behavior** (documented limitation): the auto-off timer is in-memory only. If HA restarts while boost is active, the timer is lost. The zone stays at boost_temperature in manual mode until a manual toggle. We do NOT attempt to restore the timer from persisted state in this change — keeps the change small, and a single missed auto-off on restart is recoverable.
- **No new entities.** The remaining-time sensor continues to exist, just with smarter sourcing. The switch's entity_id, translation_key, and unique_id are unchanged.
- **No breaking changes**, no migrations.

## Capabilities

### New Capabilities
- `pointtapi-boost-behavior`: Encodes the full boost workaround as a behavior contract — `turn_on` puts zone in manual at `boostTemperature`, schedules in-memory auto-off after `boostDuration` hours, exposes synthetic remaining-time. `turn_off` restores zone to pre-boost mode and cancels the timer. Restart drops the timer (documented limitation).

### Modified Capabilities
<!-- none — the existing pointtapi-device-partition / pointtapi-binary-sensors / etc. capabilities are untouched. The boost behavior was previously implicit in code with no spec; this change is the first time it's contracted. -->

## Impact

- **Code:**
  - `custom_components/bosch/pointtapi_coordinator.py` — add `boost_session: BoostSession | None = None` attribute on `PoinTTAPIDataUpdateCoordinator`.
  - `custom_components/bosch/pointtapi_entities.py` — add `BoostSession` dataclass; modify `BoschPoinTTAPIBoostSwitchEntity.__init__` / `async_turn_on` / `async_turn_off` to manage the session + `async_call_later` handle; modify the `boost_remaining_time` description's `value_fn` to read the synthetic countdown; inject `coordinator.boost_session` into the data dict the value_fn receives.
  - `custom_components/bosch/manifest.json` — version bump to `0.33.0`.
  - No translation changes required (entity names/keys unchanged).
- **APIs:** no new GETs, no new PUTs.
- **Dependencies:** none added (uses `homeassistant.helpers.event.async_call_later` and `homeassistant.util.dt`, both already in HA).
- **HA Dashboard:** users with a Lovelace card showing `sensor.pointtapi_boost_remaining_time` immediately get a working countdown when they trigger boost from HA. No card changes needed.
- **Compatibility:** purely additive; no entity_ids changed, no migrations required. Rolls back cleanly to v0.32.0 (the only loss is the synthetic countdown — Bosch's value reappears).
- **Release target:** v0.33.0.
