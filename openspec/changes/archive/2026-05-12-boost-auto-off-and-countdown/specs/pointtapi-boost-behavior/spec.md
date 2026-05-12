## ADDED Requirements

### Requirement: Boost workaround puts zone into manual mode at boost_temperature

When `switch.pointtapi_boost.async_turn_on` is called, the integration SHALL PUT `/zones/zn1/userMode = "manual"` followed by `/zones/zn1/manualTemperatureHeating = <boost_temperature>` to the Bosch API, where `<boost_temperature>` is the current value of `/heatingCircuits/hc1/boostTemperature` (default 26.0 if absent). The previous `/zones/zn1/userMode` value SHALL be remembered on the entity so it can be restored on turn-off.

#### Scenario: Turn boost on from clock mode

- **WHEN** zone is in `userMode == "clock"` and the user turns the boost switch on
- **THEN** the integration SHALL PUT `userMode = "manual"` and `manualTemperatureHeating = boost_temperature`; the entity's `_pre_boost_mode` SHALL record `"clock"`

### Requirement: Boost switch schedules automatic shut-off after boost_duration

When `async_turn_on` succeeds, the integration SHALL schedule a callback via `async_call_later(hass, duration_seconds, _auto_off_callback)` where `duration_seconds = float(/heatingCircuits/hc1/boostDuration) * 3600` (default 2.0 hours if absent). The cancel handle returned by `async_call_later` SHALL be retained on the switch entity. When the timer fires, the switch SHALL invoke its own `async_turn_off`.

#### Scenario: Boost runs to completion

- **WHEN** the user turns boost on at time T, with `boostDuration == 2.0`
- **AND** the user does NOT manually turn it off
- **THEN** at time T + 2 hours the auto-off callback SHALL fire, calling `async_turn_off`, which restores the prior userMode and clears the session

#### Scenario: Duration source captured at turn-on time

- **WHEN** the user turns boost on with `boostDuration == 2.0`, then changes `number.pointtapi_boost_duration` to 4.0 ten minutes later
- **THEN** the active session SHALL still auto-off at the original T + 2 h. The duration change applies only to the NEXT boost.

### Requirement: Manual turn-off cancels the pending auto-off

When `async_turn_off` is called (whether by the user or by the auto-off callback itself), the integration SHALL cancel any pending `async_call_later` handle by invoking it, clear the entity's `_auto_off_cancel` to None, clear `coordinator.boost_session` to None, and PUT the previously-remembered `userMode` back to `/zones/zn1/userMode`.

#### Scenario: User manually turns boost off mid-session

- **WHEN** the user turns boost on at T, then turns it off at T + 30 minutes
- **THEN** the auto-off timer scheduled for T + 2 h SHALL be cancelled (it does NOT fire later), the session SHALL be cleared, and the zone SHALL be returned to its pre-boost userMode

#### Scenario: Rapid toggle

- **WHEN** the user turns boost off and immediately back on
- **THEN** the off path SHALL cancel its timer, then the on path SHALL set a fresh session and a new timer — no leaked handles

### Requirement: Coordinator carries the current BoostSession

`PoinTTAPIDataUpdateCoordinator` SHALL expose a `boost_session: BoostSession | None` attribute. The boost switch SHALL set it on turn-on (`BoostSession(started_at=dt_util.utcnow(), duration_hours=N)`) and clear it on turn-off. The session's `remaining_minutes` SHALL be computed as `max(0, ((started_at + duration_hours hours) - utcnow()).total_seconds() / 60)`.

#### Scenario: Session lifecycle

- **WHEN** the switch is `off`
- **THEN** `coordinator.boost_session SHALL be None`

#### Scenario: Active session reports decreasing remaining time

- **WHEN** the switch is `on` and the session was started 30 minutes ago with `duration_hours = 2.0`
- **THEN** `coordinator.boost_session.remaining_minutes` SHALL be approximately 90 (within 1 minute of clock skew)

### Requirement: Synthetic remaining-time sensor reads from BoostSession when present

`sensor.pointtapi_boost_remaining_time`'s `value_fn` SHALL prefer `coordinator.boost_session.remaining_minutes` when a session exists, AND fall back to `/heatingCircuits/hc1/boostRemainingTime` (the Bosch-reported value, normally `0.0` since the workaround never reaches Bosch's boost machinery) when no session exists.

#### Scenario: HA-triggered boost active

- **WHEN** the boost switch is on (session populated)
- **THEN** the sensor's state SHALL be the session's remaining minutes — a positive float that decreases between polls

#### Scenario: No active local boost

- **WHEN** the boost switch is off (no session)
- **THEN** the sensor's state SHALL be the Bosch-reported `boostRemainingTime` value (typically 0.0 under our cloud scope)

#### Scenario: Sensor uses dict-injection to receive session

- **WHEN** `BoschPoinTTAPISensorEntity._handle_coordinator_update` runs for this entity
- **THEN** before invoking the `value_fn`, the integration SHALL inject the current `coordinator.boost_session` into the data dict under the synthetic key `"__boost_session__"` so the function signature `value_fn(data)` continues to work without coordinator coupling

### Requirement: Restart drops the timer (documented limitation)

If Home Assistant restarts while a boost is active, the in-memory timer and `boost_session` SHALL be lost. The integration SHALL NOT persist the session via `hass.helpers.storage.Store` in this change. On restart, the switch entity SHALL be re-created with `_is_on` derived from Bosch's `/heatingCircuits/hc1/boostMode` (which is `"off"` under the cloud scope), so the switch will appear off even if the zone is still in manual at boost temperature. The user can resume by manually turning the switch off (which restores the prior userMode).

#### Scenario: HA restart mid-boost

- **WHEN** boost was active at T - 30 min and HA restarts at T
- **AND** at T + 1 min the integration's first coordinator refresh completes
- **THEN** `switch.pointtapi_boost.is_on == False` (because Bosch's boostMode = off)
- **AND** `coordinator.boost_session == None`
- **AND** no auto-off timer is scheduled
- **AND** the zone is still in `userMode == "manual"` at `manualTemperatureHeating == boost_temperature` (Bosch's state survives the restart)
