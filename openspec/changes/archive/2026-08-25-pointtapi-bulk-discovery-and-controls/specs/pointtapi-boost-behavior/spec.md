## ADDED Requirements

### Requirement: Boost turn-on attempts native activation before the manual-mode fallback

When `switch.pointtapi_boost.async_turn_on` is called and no probe result is cached yet, the integration SHALL attempt native boost activation via a staged probe ladder, stopping at the first success: (1) direct `PUT /heatingCircuits/hc1/boostShortcut` with the probe-confirmed struct `[{"mode": "on", "temperature": <boostTemperature>, "duration": <boostDuration>, "zones": [<integer zone ids>]}]` (per `boost-probe-notes.md`: type `boostShortcutStruct`, `writeable: 1`, integer zone ids — the app's native one-shot boost command); (2) direct `PUT /heatingCircuits/hc1/boostZones` (current struct) followed by `PUT /heatingCircuits/hc1/boostMode = "on"` (`boostMode` is device-writeable; the historical 403 ACL no longer reproduces — direct PUTs returned 204 in the consented write probe of 2026-06-05). A bulk-write rung was considered and dropped: no community project has observed the bulk WRITE wire format, and with the direct route confirmed open, guessing write formats against a live heating system is unjustified. Probe writes SHALL be restricted to `/heatingCircuits/hc1/boost*` paths only. Native activation SHALL be considered successful only when a subsequent coordinator refresh reports `/heatingCircuits/hc1/boostMode == "on"` or `/heatingCircuits/hc1/boostRemainingTime > 0`. On native success no local auto-off timer SHALL be scheduled and `coordinator.boost_session` SHALL remain `None` (Bosch's server-side machinery owns duration and countdown). If every rung fails, the integration SHALL fall back to the manual-mode workaround and cache that outcome.

#### Scenario: Native boost works via boostShortcut

- **WHEN** the user turns boost on and rung 1's `boostShortcut` struct PUT succeeds with the next refresh showing `boostMode == "on"` or `boostRemainingTime > 0`
- **THEN** the switch SHALL report `on`, no `async_call_later` timer SHALL exist, `coordinator.boost_session` SHALL be `None`, and the cached probe result SHALL record `boostShortcut` as the working route — rung 2 SHALL NOT be attempted

#### Scenario: All probes fail

- **WHEN** every rung returns 403 or the state check never confirms activation
- **THEN** the integration SHALL execute the manual-mode workaround (manual mode + boost temperature + local timer) and the cached probe result SHALL record `fallback`

### Requirement: Native boost probe result is cached and surfaced in diagnostics

The probe outcome (working route or `fallback`, plus per-rung request/response summaries) SHALL be cached on the coordinator for the lifetime of the config entry — subsequent boost toggles use the cached route directly without re-probing — and included in the integration's diagnostics output. Probe requests and responses SHALL be logged at DEBUG.

#### Scenario: Second boost toggle skips probing

- **WHEN** a probe previously identified `boostShortcut` as the working route and the user toggles boost again
- **THEN** turn-on SHALL issue only the `boostShortcut` write — no 403-doomed rung-1/rung-2 attempts

#### Scenario: Diagnostics show the probe verdict

- **WHEN** the user downloads diagnostics after a boost has been attempted
- **THEN** the dump SHALL contain the probe verdict and per-rung outcomes, sufficient to report upstream findings

## MODIFIED Requirements

### Requirement: Boost workaround puts zone into manual mode at boost_temperature

When native boost is unavailable (probe result `fallback`), and `switch.pointtapi_boost.async_turn_on` is called, the integration SHALL PUT `/zones/zn1/userMode = "manual"` followed by `/zones/zn1/manualTemperatureHeating = <boost_temperature>` to the Bosch API, where `<boost_temperature>` is the current value of `/heatingCircuits/hc1/boostTemperature` (default 26.0 if absent). The previous `/zones/zn1/userMode` value SHALL be remembered on the entity so it can be restored on turn-off. When native boost is available, this workaround SHALL NOT execute.

#### Scenario: Turn boost on from clock mode (fallback mode)

- **WHEN** the probe result is `fallback`, zone is in `userMode == "clock"`, and the user turns the boost switch on
- **THEN** the integration SHALL PUT `userMode = "manual"` and `manualTemperatureHeating = boost_temperature`; the entity's `_pre_boost_mode` SHALL record `"clock"`

#### Scenario: Native mode leaves zone mode untouched

- **WHEN** the probe result is a native route and the user turns the boost switch on
- **THEN** the integration SHALL NOT write `/zones/zn1/userMode` or `/zones/zn1/manualTemperatureHeating`

### Requirement: Boost switch schedules automatic shut-off after boost_duration

When operating in fallback (workaround) mode and `async_turn_on` succeeds, the integration SHALL schedule a callback via `async_call_later(hass, duration_seconds, _auto_off_callback)` where `duration_seconds = float(/heatingCircuits/hc1/boostDuration) * 3600` (default 2.0 hours if absent). The cancel handle returned by `async_call_later` SHALL be retained on the switch entity. When the timer fires, the switch SHALL invoke its own `async_turn_off`. When operating in native mode, no local timer SHALL be scheduled — auto-off is owned by the device, observed through `boostMode`/`boostRemainingTime` in coordinator data.

#### Scenario: Boost runs to completion (fallback mode)

- **WHEN** the probe result is `fallback`, the user turns boost on at time T with `boostDuration == 2.0`
- **AND** the user does NOT manually turn it off
- **THEN** at time T + 2 hours the auto-off callback SHALL fire, calling `async_turn_off`, which restores the prior userMode and clears the session

#### Scenario: Duration source captured at turn-on time (fallback mode)

- **WHEN** the probe result is `fallback` and the user turns boost on with `boostDuration == 2.0`, then changes `number.pointtapi_boost_duration` to 4.0 ten minutes later
- **THEN** the active session SHALL still auto-off at the original T + 2 h. The duration change applies only to the NEXT boost.

#### Scenario: Native boost expires server-side

- **WHEN** the probe result is a native route and a native boost was started
- **THEN** no local timer SHALL exist, and when a later refresh reports `boostMode == "off"` (and `boostRemainingTime == 0`) the switch SHALL report `off` without any HA-side write

### Requirement: Manual turn-off cancels the pending auto-off

When `async_turn_off` is called in fallback mode (whether by the user or by the auto-off callback itself), the integration SHALL cancel any pending `async_call_later` handle by invoking it, clear the entity's `_auto_off_cancel` to None, clear `coordinator.boost_session` to None, and PUT the previously-remembered `userMode` back to `/zones/zn1/userMode`. When called in native mode, the integration SHALL instead deactivate via the probed route (e.g. `PUT boostMode = "off"` or the boostShortcut off-value) and SHALL NOT touch `/zones/zn1/userMode`.

#### Scenario: User manually turns boost off mid-session (fallback mode)

- **WHEN** the probe result is `fallback`, the user turns boost on at T, then turns it off at T + 30 minutes
- **THEN** the auto-off timer scheduled for T + 2 h SHALL be cancelled (it does NOT fire later), the session SHALL be cleared, and the zone SHALL be returned to its pre-boost userMode

#### Scenario: Rapid toggle

- **WHEN** the user turns boost off and immediately back on
- **THEN** the off path SHALL cancel its timer (fallback) or issue the native off-write (native), then the on path SHALL start cleanly — no leaked handles in either mode

#### Scenario: User turns native boost off

- **WHEN** the probe result is a native route and the user turns the boost switch off mid-boost
- **THEN** the integration SHALL write the native deactivation and request a refresh; the zone's `userMode` SHALL NOT be written by HA

### Requirement: Synthetic remaining-time sensor reads from BoostSession when present

`sensor.pointtapi_boost_remaining_time`'s `value_fn` SHALL prefer `coordinator.boost_session.remaining_minutes` when a session exists (fallback-mode boost), AND otherwise report `/heatingCircuits/hc1/boostRemainingTime` — which under native boost is Bosch's real server-side countdown, and with no boost active is 0.

#### Scenario: Fallback-mode boost active

- **WHEN** the boost switch is on in fallback mode (session populated)
- **THEN** the sensor's state SHALL be the session's remaining minutes — a positive float that decreases between polls

#### Scenario: Native boost active

- **WHEN** a native boost is active (no session, Bosch reports `boostRemainingTime == 87`)
- **THEN** the sensor's state SHALL be 87 — the device-reported countdown, no synthesis

#### Scenario: No active boost

- **WHEN** the boost switch is off (no session, Bosch reports 0)
- **THEN** the sensor's state SHALL be 0.0

#### Scenario: Sensor uses dict-injection to receive session

- **WHEN** `BoschPoinTTAPISensorEntity._handle_coordinator_update` runs for this entity
- **THEN** before invoking the `value_fn`, the integration SHALL inject the current `coordinator.boost_session` into the data dict under the synthetic key `"__boost_session__"` so the function signature `value_fn(data)` continues to work without coordinator coupling

### Requirement: Restart drops the timer (documented limitation)

In fallback mode: if Home Assistant restarts while a boost is active, the in-memory timer and `boost_session` SHALL be lost. The integration SHALL NOT persist the session via `hass.helpers.storage.Store` in this change. On restart, the switch entity SHALL be re-created with `_is_on` derived from Bosch's `/heatingCircuits/hc1/boostMode`, so a fallback-mode boost will appear off even if the zone is still in manual at boost temperature; the user can resume by manually turning the switch off (which restores the prior userMode). In native mode this limitation SHALL NOT apply: after a restart the switch derives its state from the device-reported `boostMode` and the boost continues server-side unaffected. The probe-result cache is in-memory and SHALL be re-established by the first post-restart boost toggle.

#### Scenario: HA restart mid-boost (fallback mode)

- **WHEN** a fallback-mode boost was active at T - 30 min and HA restarts at T
- **AND** at T + 1 min the integration's first coordinator refresh completes
- **THEN** `switch.pointtapi_boost.is_on == False` (because Bosch's boostMode = off)
- **AND** `coordinator.boost_session == None`
- **AND** no auto-off timer is scheduled
- **AND** the zone is still in `userMode == "manual"` at `manualTemperatureHeating == boost_temperature` (Bosch's state survives the restart)

#### Scenario: HA restart mid-boost (native mode)

- **WHEN** a native boost was active and HA restarts
- **THEN** after the first refresh the switch SHALL report `on` (device reports `boostMode == "on"`), the remaining-time sensor SHALL show the device countdown, and the boost SHALL end server-side at its scheduled time with no HA involvement
