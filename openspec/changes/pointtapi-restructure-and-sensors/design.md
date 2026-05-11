## Context

The POINTTAPI path has a mature coordinator + entity pattern (see v0.30.1):

- `PoinTTAPIDataUpdateCoordinator` polls every root in `POINTTAPI_COORDINATOR_ROOTS` plus references each 60 s, populates `coordinator.data: dict[str, dict]` keyed by API path.
- `BoschPoinTTAPISensorEntityDescription` (frozen dataclass) drives entity creation via `_pointtapi_sensor_descriptions()`. Each entity reads `coordinator.data[description.key]["value"]` (or runs an optional `value_fn`).
- Device routing today is *per-entity ad-hoc*: in each `__init__`, an `if path.startswith("/zones"): ...elif "/solarCircuits": ...else: ...` chain decides which `DeviceInfo` to attach. Most paths fall through to the gateway catch-all `(DOMAIN, uuid)` named "POINTTAPI". The Number, Select, Switch, and Climate/WaterHeater entities each repeat their own variant of this logic.
- The `binary_sensor` platform exists for legacy XMPP/HTTP entries via dispatcher signals. POINTTAPI entries currently short-circuit to `async_add_entities([])` — no binary-sensor infrastructure for the cloud path.
- The Solar device `(DOMAIN, f"{uuid}_solar")` is created unconditionally because `/solarCircuits/sc1` is unconditionally polled. Households without solar see four `unavailable` ghost entities.

The UX audit's key findings drive this design:
- **Catch-all device is hostile.** "Is my burner running?" requires scanning 35 unrelated entities.
- **Doubled `solar_solar_*` prefix is user-hostile, not cosmetic** — it leaks into automations, voice assistants, logs.
- **Non-solar households deserve no Solar device** — the four ghost entities erode trust.
- **Several entities are mis-routed today** — outdoor temp and indoor humidity belong with the zone, gas usage belongs with the boiler, heating-circuit numbers belong with the zone.
- **Multi-zone systems silently break** — routing hard-codes `zn1`/`hc1`.

This change does the structural fix once, and lands the four new entities (DHW detail + burner state) on the correct devices from day one.

## Goals / Non-Goals

**Goals:**
- A 4-or-5 device partition keyed to physical objects: Gateway, Boiler, Hot Water Tank, Heating Zone, Solar (conditional).
- A *single* device-routing function that every entity init calls — no per-class chains.
- Conditional Solar device creation gated on the first coordinator refresh.
- One-shot entity-ID migration that preserves user automations.
- New DHW + burner entities land on the right devices in their first appearance.
- Multi-zone capability (zn2, zn3, etc.) lands automatically by treating the zone id as a parameter.

**Non-Goals:**
- No HA `update` platform for firmware (deferred per audit).
- No deeper Bosch API surface (no new GETs, no new PUTs).
- No options-flow controls for which entities to expose.
- No coordinator changes — pagination + token refresh + 504 resilience all carry over unchanged from v0.30.1.
- No solar-specific Energy Dashboard scaffolding beyond what `sensor.solar_total_gain` already provides.

## Decisions

### 1. Single `_resolve_device_info(uuid, path, kind=None)` function over per-class chains

Add a module-level helper in `pointtapi_entities.py`:

```python
def _resolve_device_info(uuid: str, path: str, *, kind: str | None = None) -> DeviceInfo:
    # path-based routing
    # /solarCircuits/* → Solar
    # /heatSources/*  + /system/appliance/*  + /energy/* → Boiler
    # /dhwCircuits/* → Hot Water Tank
    # /zones/* + /heatingCircuits/* + /system/sensors/* + /heatingCircuits/hc1/* (numbers/selects) → Heating Zone
    # /gateway/* + /firmware/* + PIR sensitivity / notification light / auto firmware update → EasyControl Gateway
    # everything else → EasyControl Gateway (safe default)
```

Switch, Number, Select, BinarySensor, Sensor, Climate, WaterHeater all delegate device-info construction to this function. The legacy `if/elif` chains in each `__init__` go away.

**Why:** Per the audit, the current dispersal of routing logic is the reason `heatingCircuits/hc1/maxSupplyTemperature` (a number entity) silently lands on the gateway catch-all even though it's plainly a zone configuration. Centralizing routing makes the partition reviewable in one place and the bug class disappears.

**Alternatives considered:** (a) Per-platform routing tables — rejected: still duplicates the path → device mapping. (b) Inline routing on each description — rejected: makes adding entities verbose and lets routing drift between platforms.

### 2. Device-id schema

| Device | identifier | display name |
|---|---|---|
| Gateway | `(DOMAIN, uuid)` | `EasyControl Gateway` |
| Boiler | `(DOMAIN, f"{uuid}_boiler")` | `Boiler` |
| Hot Water Tank | `(DOMAIN, f"{uuid}_dhw")` | `Hot Water Tank` |
| Heating Zone *id* | `(DOMAIN, f"{uuid}_zone_{zone_id}")` | `Heating Zone {zone_id}` (today `zn1` → `Heating Zone zn1`; we strip the API prefix for `zn1`-only systems and call it just `Heating Zone`) |
| Solar | `(DOMAIN, f"{uuid}_solar")` | `Solar` |

All non-gateway devices set `via_device=(DOMAIN, uuid)` so HA's device tree shows them nested under the gateway.

**Why this id schema:** the gateway keeps the bare `uuid` for backward compatibility (existing automations referencing the gateway device id don't break). All child devices get descriptive suffixes (`_boiler`, `_dhw`, `_zone_zn1`, `_solar`) that are easy to spot in `core.device_registry` JSON and unlikely to collide with future additions.

**Alternatives considered:** (a) Hash-prefix child IDs — rejected: not human-readable. (b) Reuse `_solar` style without `_dhw`/`_boiler` (keep some on gateway) — rejected: defeats the partition.

### 3. Path → device mapping (the actual rules)

| Path prefix or keyword | Device |
|---|---|
| `/gateway/` (wifi, firmware, update) | Gateway |
| Notification light switch, auto-firmware switch, PIR sensitivity select | Gateway |
| `/heatSources/` | Boiler |
| `/system/appliance/` (errors, codes, system pressure) | Boiler |
| `/energy/` (gas usage) | Boiler |
| Annual gas goal number | Boiler |
| `/dhwCircuits/` | Hot Water Tank |
| Thermal disinfect switch | Hot Water Tank |
| `/zones/` | Heating Zone (by zone id) |
| `/heatingCircuits/` | Heating Zone (by parallel id) |
| Outdoor temperature, indoor humidity sensors | Heating Zone |
| `/solarCircuits/` | Solar |

The mapping is a small lookup table inside `_resolve_device_info`. Adding a new device class in the future is a one-line table edit.

### 4. Conditional Solar — first-poll gate

In `sensor/__init__.py`'s `async_setup_entry`, after `await coordinator.async_config_entry_first_refresh()` completes, check whether `coordinator.data.get("/solarCircuits/sc1")` is a populated dict with at least one of the four expected refs. If not, skip adding the four solar sensor descriptions. The Solar device is never created.

For installs that gain solar hardware *later*, this requires a reload of the config entry. The config_flow's options handler already triggers a reload on options changes; we can also detect "solar appeared" in the coordinator's update loop and emit a one-time "consider reloading" notification, but that's beyond MVP scope.

**Why first-poll-gate:** the simplest possible test that matches the audit's "don't create what doesn't exist" recommendation, with no ongoing complexity.

**Alternatives considered:** (a) Always create the device, hide it when empty — rejected: HA's device registry doesn't hide unconditionally created devices. (b) Late-add: poll, then defer device creation to a follow-up task — rejected: complicates first-poll consistency.

### 5. Entity-ID migration via `async_migrate_entry`

Bump `ConfigEntry.version` from 1 (current default) to 2. In `async_migrate_entry`:

```python
async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version >= 2:
        return True
    if entry.data.get(CONF_PROTOCOL) != POINTTAPI:
        hass.config_entries.async_update_entry(entry, version=2)
        return True
    registry = er.async_get(hass)
    renames = {
        # solar prefix cleanup
        f"sensor.solar_solar_collector_temperature": "sensor.solar_collector_temperature",
        f"sensor.solar_solar_storage_temperature": "sensor.solar_storage_temperature",
        f"sensor.solar_solar_pump_modulation": "sensor.solar_pump_modulation",
        f"sensor.solar_total_solar_gain": "sensor.solar_total_gain",
        # water_heater rename
        f"water_heater.water_heater": "water_heater.hot_water_tank",
    }
    for old_id, new_id in renames.items():
        if registry.async_get(old_id) and not registry.async_get(new_id):
            registry.async_update_entity(old_id, new_entity_id=new_id)
    hass.config_entries.async_update_entry(entry, version=2)
    return True
```

Idempotent. Runs once per entry. Existing automations referencing `sensor.solar_solar_*` get a free rewrite (HA's entity registry remap covers `automation.yaml`, scripts, scenes, scenes-with-conditions, and template sensors that reference the registered entity_id — but does NOT migrate hand-written Lovelace YAML strings or REST automation payloads).

**Why on-restart migration:** the user only pays the disruption once. Without it, existing users would have to manually rename in their automations after a normal HACS update, which the audit specifically flagged as "lost trust." The downside (Lovelace YAML not auto-fixed) is documented in the release notes.

**Alternatives considered:** (a) Leave old entity IDs alone, only new installs get new IDs — rejected: creates a permanent split in the user population and leaves the `solar_solar_*` ugliness for anyone who upgrades. (b) Migrate everything (including device IDs, not just entity IDs) — overkill; HA tolerates device-id changes via `via_device` reattachment.

### 6. Device-class assignments for new binary sensors

- `binary_sensor.hot_water_tank_heating` → `BinarySensorDeviceClass.HEAT`
- `binary_sensor.boiler_flame` → `BinarySensorDeviceClass.RUNNING`

Same rationale as before: HEAT for "heat is being applied to the tank right now", RUNNING for "the burner is currently running" (consistent with how HA treats compressor/pump indicators).

### 7. Translation key naming

| New entity_id | translation_key |
|---|---|
| `sensor.hot_water_tank_actual_temperature` | `dhw_actual_temperature` |
| `binary_sensor.hot_water_tank_heating` | `dhw_heating` |
| `binary_sensor.boiler_flame` | `burner_flame` |
| `sensor.boiler_ignition_starts` | `boiler_ignition_starts` |
| Renamed: `sensor.solar_collector_temperature` | `collector_temperature` (was `solar_collector_temperature`) |
| Renamed: `sensor.solar_storage_temperature` | `storage_temperature` (was `solar_storage_temperature`) |
| Renamed: `sensor.solar_pump_modulation` | `pump_modulation` (was `solar_pump_modulation`) |
| Renamed: `sensor.solar_total_gain` | `total_gain` (was `solar_total_gain`) |

Note: the *translation_key* in `strings.json` doesn't drive the entity_id — it drives the *display name*. The entity_id is built from `{device_slug}_{translation_key}`. So dropping the `solar_` prefix from the key, combined with the device-name "Solar", yields the clean `sensor.solar_collector_temperature`. This is the audit's prescribed fix.

### 8. Default boolean resolver for new binary sensors

`BoschPoinTTAPIBinarySensorEntityDescription` includes an optional `value_fn: Callable[[dict], bool | None] | None = None`. For descriptions without `value_fn`, the default resolver normalizes `coordinator.data[description.key]["value"]` to `True`/`False`/`None`:

```python
v = (raw or "").strip().lower() if isinstance(raw, str) else raw
if v == "on": return True
if v == "off": return False
return None
```

`None` lets HA render the entity as `unknown` rather than fabricating `False` on a malformed payload.

## Risks / Trade-offs

- **Risk: Lovelace YAML not auto-migrated.** Users with hand-written cards referencing `sensor.solar_solar_*` will see broken cards after the migration. → **Mitigation:** prominent release notes + a one-line "rename your Lovelace cards" callout in the GitHub release body. The migration covers HA-native automation/script/scene config; the Lovelace gap is widely understood in the HA community.
- **Risk: Migration fails partway through.** If `async_migrate_entry` raises mid-rename, some entities would be migrated and others not. → **Mitigation:** the function is idempotent — re-running picks up where it left off. We also wrap each rename in a try/except to log + continue, and only flip `entry.version` to 2 after all renames are attempted.
- **Trade-off: device-id changes break automations that reference the *device* by ID.** Most users don't reference devices by ID, but power users might. The gateway device ID is preserved (`(DOMAIN, uuid)` unchanged); only the sub-devices get new identifiers. → **Mitigation:** documented in release notes. The likelihood is low and the fix is mechanical.
- **Trade-off: The migration assumes specific old entity_id slugs.** If a user has manually renamed `sensor.solar_solar_collector_temperature` to `sensor.my_collector_temp`, the migration won't find the old ID and won't rewrite. → That's the correct behavior — we don't want to overwrite user-chosen IDs. Users who renamed get the same fate as before (their IDs work, their YAML still works).
- **Risk: Multi-zone routing untested.** No production install with zn2/zn3 exists for this codebase yet. The new routing should work but is unverified live. → **Mitigation:** treat zone routing as a parameter from the start (don't hard-code `zn1`), include a unit-style assertion that synthetic `zn2`/`zn3` paths route correctly.
- **Risk: First-poll gate misses installs where solar appears later.** If the user adds a solar collector to their Bosch account after the integration is set up, the Solar device won't appear until they reload the config entry. → **Mitigation:** acceptable for v0.31.0; document the workaround (reload integration). A future change could watch for `/solarCircuits/sc1` going from empty → populated and emit a notification.

## Migration Plan

- **Deploy:** ship as v0.31.0. HACS users see the prompt; existing installs auto-migrate on next HA restart.
- **First-restart behavior:** `async_migrate_entry` runs, renames the legacy entity IDs in the registry, bumps `entry.version=2`. All entities reappear at their new IDs with full history preserved (HA's registry rename retains state history).
- **Solar conditional:** systems without solar see their previously-existing Solar device + 4 ghost entities **persist** as orphans (HA doesn't auto-clean removed devices). We add a cleanup step in the migration: explicitly remove the Solar device and its entities from the registry if no solar data was returned in the first refresh.
- **Rollback:** revert to v0.30.1. The new entity IDs persist; the old code creates new entities at the original IDs again, which won't have history. Users would have to manually clean up. **Document this as one-way migration.**
- **Communication:** release notes prominently list (a) the new device tree, (b) the entity_id renames, (c) the Lovelace-card gotcha, (d) what to do if you have a custom DHW or solar-driven automation.

## Open Questions

- *Closed during audit:* keep DHW + Boiler as separate devices (per audit, they are physically distinct).
- *Closed during audit:* don't ship the HA `update` platform entity yet — out of scope.
- *Remaining, low-priority:* should we expose a `binary_sensor.boiler_refill_needed` from `/heatSources/refillNeeded`? Data is there, audit didn't flag it. **Decision: defer to a follow-up change to keep this PR focused.**
- *Remaining, low-priority:* multi-zone display name — when only `zn1` exists, "Heating Zone zn1" vs "Heating Zone"? Auditor preferred the latter; tasks include both options as a deferred polish decision.
