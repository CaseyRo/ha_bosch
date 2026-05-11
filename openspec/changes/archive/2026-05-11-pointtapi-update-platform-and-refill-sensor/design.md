## Context

v0.31.0 left two follow-up items the UX audit flagged but deferred:

- The string-sensor approach to firmware update notifications doesn't surface in HA's native Updates panel.
- `/heatSources/refillNeeded` is a real maintenance signal that the integration polls but throws away.

This change picks both up in a single v0.32.0 release. Both consume paths already in `coordinator.data` — no new polling, no auth surface changes, no migration.

## Goals / Non-Goals

**Goals:**
- HA Update entity for the gateway firmware visible in the Updates panel.
- Binary sensor for refill-needed on the Boiler device.
- Two diagnostic timestamp sensors for last-check / last-update timestamps.
- Establish a table-driven Update platform pattern parallel to the binary-sensor one from v0.31.0.
- Generalize the on/off resolver to also accept true/false strings.

**Non-Goals:**
- No programmatic firmware install — Bosch's `/gateway/update/state` is `writeable=1` but we don't know what values are accepted, and triggering an install from a third-party integration is risky (the official EasyControl app handles this with appropriate user confirmation). The Update entity is read-only.
- No deprecation of `sensor.pointtapi_firmware_update_state` — keep it as-is for backward compat. The new Update entity is additive.
- No latest-version string display — Bosch's API doesn't expose the available version number (the relevant fields return 403). We can only surface a binary "update available" state.
- No new coordinator paths or polling cadence changes.

## Decisions

### 1. Update entity uses a synthetic `latest_version` derived from `state`

The Bosch API returns:
- `/gateway/versionFirmware` → real current version, e.g. `"05.04.00"`
- `/gateway/update/state` → `"no update"` when nothing pending; presumably other strings (e.g. `"available"`, `"installing"`) otherwise
- `/gateway/update/availableVersion` → **403** (not accessible to our client scope)

HA's Update entity needs both `installed_version` and `latest_version` to render correctly. With no real latest-version field, we map:

```
installed_version = /gateway/versionFirmware
latest_version    = installed_version       if state == "no update"
                  = installed_version + " (update available)"  otherwise
```

This makes HA's Updates panel show the entity as "up to date" or "update available" correctly. The latest_version string isn't a real version — it's a flag — but it satisfies HA's contract and renders sensibly in the UI.

**Alternatives considered:** (a) Set `latest_version = state` directly (e.g. `"available"`) — rejected: HA sorts versions for comparison; a non-version string compared to `"05.04.00"` would always show "newer" even after install. (b) Always set `latest_version = installed_version` and use a custom `update_available` flag — rejected: HA's Updates panel only picks up entities where the two versions differ. (c) Skip the Update entity entirely and just add a binary_sensor — rejected: that's worse than the current state-string sensor, not better.

### 2. Update entity has no install/skip methods

`async_install` and `async_skip` are not implemented. The Update entity is `supported_features = 0` (read-only).

**Why:** even though `/gateway/update/state` reports `writeable=1`, we don't know which values are accepted, the action is destructive (firmware flash), and the official app handles user consent. Doing this safely would need vendor docs we don't have.

**Alternatives considered:** Optimistically PUT `"install"` to `/gateway/update/state` on `async_install` — rejected: untested, could 403, could brick. Out of scope.

### 3. Timestamp value_fn strips the trailing weekday

API returns timestamps like `"2026-05-11T01:02:00+02:00 Mo"` (or `Tu`, `We`, `Th`, `Fr`, `Sa`, `Su`). The weekday is appended with a space. We parse with a `value_fn` that splits on the last space and tries `datetime.fromisoformat` on the first part. Returns `None` on parse failure (HA renders as `unknown`).

```python
def _parse_update_timestamp(data):
    raw = data.get("/gateway/update/lastCheck", {}).get("value")
    if not isinstance(raw, str):
        return None
    iso = raw.rsplit(" ", 1)[0]  # strip " Mo" / " Th" / etc.
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None
```

Same shape for `lastUpdate`.

**Why:** The weekday tail is locale-irrelevant (always 2 chars in English shorthand) and easily strippable. Trying to be clever about it (parsing the weekday separately, etc.) buys nothing.

### 4. `_resolve_on_off` extended to handle `"true"`/`"false"`

Current resolver in `pointtapi_entities.py:_resolve_on_off` only accepts `"on"`/`"off"`. Bosch's `refillNeeded` returns `"true"`/`"false"`. Generalize:

```python
def _resolve_on_off(raw):
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in ("on", "true"):
            return True
        if v in ("off", "false"):
            return False
    return None
```

**Why:** the resolver is the central seam — fixing it once means every future POINTTAPI binary sensor handles both API dialects without needing a `value_fn`. This is the modification to the `pointtapi-binary-sensors` capability called out in the proposal.

**Alternatives considered:** add a per-description `value_fn` to `refill_needed` — rejected: spreads the same string-compare logic across descriptions. (Same reasoning that drove the original centralized resolver in v0.31.0.)

### 5. Update entity device routing

`update.easycontrol_gateway_firmware` attaches to the Gateway device `(DOMAIN, uuid)`. Routes through the existing `_resolve_device_info` helper (path `/gateway/versionFirmware` already falls through to the gateway).

The two diagnostic timestamp sensors also attach to Gateway. `binary_sensor.boiler_refill_needed` attaches to Boiler (path `/heatSources/refillNeeded` already routes there per the v0.31.0 partition rules).

No changes to `_resolve_device_info` itself.

### 6. Platform file pattern

Create `custom_components/bosch/update.py` (new file) modeled on the post-v0.31.0 `binary_sensor.py`:

```python
async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data.get(CONF_PROTOCOL) != POINTTAPI:
        async_add_entities([])
        return True
    coordinator = entry.runtime_data.coordinator
    if coordinator is None:
        async_add_entities([])
        return True
    uuid = entry.data.get(UUID)
    async_add_entities([
        BoschPoinTTAPIUpdateEntity(coordinator, entry.entry_id, uuid, desc)
        for desc in POINTTAPI_UPDATE_DESCRIPTIONS
    ])
    return True
```

No legacy XMPP/HTTP code path needed — the legacy gateway integration didn't have Update entities, so the file is POINTTAPI-only.

Manifest doesn't need an explicit platforms list change — HA auto-discovers `update.py` if it implements `async_setup_entry`.

## Risks / Trade-offs

- **Risk: the synthetic `latest_version` string confuses users who expect a real version number.** → **Mitigation:** the entity surfaces in the Updates panel correctly (up-to-date vs available); the latest_version field is normally rendered behind a click-through. We document this in the release notes ("the integration can't tell you which version is available — only that one is").
- **Risk: `/gateway/update/state` returns an unexpected value (e.g. `"installing"`, `"failed"`) that our resolver doesn't handle.** → The fallback is to treat anything other than `"no update"` as "update available," which is the safer default (over-notify rather than miss). Once we see real values in production logs we can add explicit handling.
- **Risk: timestamp parse failure on a locale change.** → API trailer is always English 2-char weekday per observation; if it ever changes, parse fails closed (returns `None`, entity shows `unknown`) — no crash.
- **Trade-off: keeping `sensor.pointtapi_firmware_update_state` alongside the new Update entity.** Some duplication in the UI, but eliminates a breaking change for users with existing automations referencing the string sensor. Acceptable cost.
- **Risk: `refillNeeded` may report `"true"` briefly during a normal refill cycle (transient).** PROBLEM device class makes HA show it as red while true — users might get notification spam. **Mitigation:** users can wrap their notification in a `for: 5m` delay condition. Don't over-engineer this — the value sticking at "true" for more than a few minutes IS the signal worth acting on.

## Migration Plan

- **Deploy:** ship as v0.32.0. HACS users pull on next refresh.
- **First-restart behavior:** new entities appear automatically. No migration logic needed (no entity_id renames in this release). Existing `sensor.pointtapi_firmware_update_state` continues unchanged.
- **Rollback:** revert to v0.31.0. New entities go to `unavailable`; users can remove them via the entity registry UI or leave them as orphans (no data loss).

## Open Questions

- *Closed:* whether to attempt `async_install` — no, too risky without vendor docs.
- *Closed:* whether to deprecate `sensor.pointtapi_firmware_update_state` — no, keep for backward compat in this release.
- *Remaining, low-priority:* should `last_update_check` use `device_class=TIMESTAMP` or `device_class=DATE`? **Decision: TIMESTAMP** (it includes time-of-day to the second). Final.
