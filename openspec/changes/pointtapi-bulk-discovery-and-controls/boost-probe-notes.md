# Boost & comfort-control probe findings (task 1.1)

Probed 2026-06-05 via local XMPP (`probe_boost_resources.py`, read-only,
`bosch-thermostat-client==0.28.2`). Full dump: `boost_probe_20260605_*.json` (repo root).

## The headline: `boostShortcut` is the native boost trigger

```
/heatingCircuits/hc1/boostShortcut
  type: boostShortcutStruct    writeable: 1    used/available: true
  value: [ { "mode": "off", "temperature": 21.0, "duration": 1,
             "zones": [1], "allowedZones": [1] } ]
```

One writable struct carrying the complete boost command — mode, temperature,
duration (hours), and **integer** zone ids (`1`, not `"zn1"`). The struct's
`temperature`/`duration` are independent of the `/boostTemperature` (26.0) and
`/boostDuration` (2.0) resources — the EasyControl app's boost button almost
certainly PUTs this struct in one shot. The "on" enum for `mode` is unconfirmed
(current value `off`); ladder rung 1 should try `"on"` first.

Supporting resources:

```
/heatingCircuits/hc1/boostZones   boostZoneStruct  writeable: 1
  value: [ { "zones": [1], "allowedZones": [1] } ]
/heatingCircuits/hc1/boostMode    stringValue      writeable: 1   value: "off"
```

`boostMode` **is writeable at the device level** — the historical 403 on
`PUT boostMode` is a cloud-route ACL, not a device restriction. This keeps the
bulk-write rung and a direct-PUT retry worth probing.

### Resulting probe ladder (updates design.md D4)

1. `PUT /heatingCircuits/hc1/boostShortcut` with
   `[{"mode": "on", "temperature": <boostTemperature>, "duration": <boostDuration>, "zones": [1]}]`
   (struct PUT body shape — full array element — to be confirmed against a 400/415 response)
2. `PUT /heatingCircuits/hc1/boostZones` (current struct) + `PUT boostMode = "on"` (direct route retry)
3. Same writes via the bulk endpoint (write ACL may differ from the direct route)
4. Fallback: v0.33 manual-mode workaround

## Comfort controls — all confirmed on-device

| Path | Type | Writeable | Observed | Spec constraint check |
|---|---|---|---|---|
| `/system/awayMode/enabled` | stringValue | 1 | `"false"` | ✓ "true"/"false" strings |
| `/dhwCircuits/dhw1/extraDhw` | stringValue | 1 | `"off"` | ✓ on/off |
| `/dhwCircuits/dhw1/extraDhwDuration` | floatValue | 1 | 15.0 | ✓ 15–2880 min, step 15 |
| `/dhwCircuits/dhw1/thermalDisinfect/time` | floatValue | 1 | 60.0 | ✓ 0–1439 min, step 1 |
| `/dhwCircuits/dhw1/thermalDisinfect/weekDay` | stringValue | 1 | `"Mo"` | ✓ |
| `/dhwCircuits/dhw1/thermalDisinfect/lastResult` | stringValue | 0 | `"done"` | ✓ read-only sensor |
| `/notifications` | **errorList** | 0 | `"value": []` | ⚠ key is `value` (not `values`) over XMPP — read both keys defensively; homecom_alt saw `values` on the cloud route |

Note: `extraDhw`/`extraDhwDuration` report `used/available: "false"` on this
install (instant hot-water system, `hotWaterSystem: instant` per issue-78 dump of
the same hardware class) — entities must tolerate `available: "false"` gracefully.

## Bonus discoveries (future-change candidates, not in scope)

```
/heatingCircuits/hc1/buildingHeatup        stringValue  writeable:1  "normal"
/heatingCircuits/hc1/seasonOptMode         stringValue  writeable:1  "always_heating" (allowedValues: [always_heating])
/heatingCircuits/hc1/setpointOptimization  stringValue  writeable:1  "off"
/heatingCircuits/hc1/minOutdoorTemp        floatValue   writeable:0  -10.0 (range -10..-3)
/heatingCircuits/hc1/heatCurveMax          floatValue   writeable:1  45.0 (40..90)
/heatingCircuits/hc1/heatCurveMin          floatValue   writeable:1  20.0 (20..90)
/heatingCircuits/hc1/type                  stringValue  writeable:1  "convector"
/heatingCircuits/hc1/typeRoomControl       stringValue  writeable:1  "radiator"
/devices/list — single entry: name base64("EasyControl"), zone 1, battery "unknown", signal 0
```

`/devices/list` confirms the deferred per-room RF feature has little value on
this install (one thermostat, no battery/signal data reported).

## Cloud-route probe results (2026-06-05, user-authorized, run on the HA host)

Read probes with the live HA-stored token (dashapp scope) — **all passed**:

1. ✅ **Gateway discovery**: `GET /pointt-api/api/v1/gateways/` → `200`
   `[{"deviceId": "101506113", "deviceType": "rrc2"}]`. No human-readable name
   field — the config-flow picker shows id + deviceType only.
2. ✅ **Bulk read on RRC2**: `POST /bulk` with 5 paths → `200`, envelope exactly
   as homecom_alt documented (`[0].resourcePaths[].{resourcePath, serverStatus,
   gatewayResponse{status, payload}}`). All 5 payloads byte-identical to the
   direct-GET responses. D1/D2 fully validated for our device.
3. ✅ **Cloud reads of boost resources**: `boostShortcut`, `boostZones`,
   `boostMode` all `200` via cloud GET, payloads identical to XMPP — meaning
   the reference walk already places them in `coordinator.data` today.
4. ✅ Cloud `/notifications` also uses the `value` key (same as XMPP) — the
   `values` key homecom_alt reads likely applies to other device types; the
   both-keys defensive read in the spec stands.

### Write-ACL probe (2026-06-05, user-consented no-op writes)

PUT-ing back the exact current values (`mode: "off"`, zones unchanged — zero
device-state change, verified by follow-up GETs):

| Direct cloud PUT | Status |
|---|---|
| `/heatingCircuits/hc1/boostMode` `{"value": "off"}` | **204** ✅ |
| `/heatingCircuits/hc1/boostShortcut` `{"value": [{"mode": "off", "temperature": 21.0, "duration": 1, "zones": [1]}]}` | **204** ✅ |
| `/heatingCircuits/hc1/boostZones` `{"value": [{"zones": [1]}]}` | **204** ✅ |

**The historical 403 on `PUT boostMode` no longer reproduces — Bosch relaxed
the cloud ACL.** The v0.33 local-timer workaround exists purely for an ACL that
is gone. Implications for the implementation:

- The probe ladder stays (resilience against the ACL tightening again), but
  rung 1 (`boostShortcut` one-shot struct) is now *expected* to succeed.
- The struct PUT body shape `{"value": [{...}]}` is confirmed accepted (204).
- Remaining micro-unknown: the `mode` "on" enum and actual activation semantics
  — a 204 proves acceptance, not boost behavior. Confirmed at the first real
  toggle (implementation logs + diagnostics capture the outcome).
- The bulk-write rung is likely unnecessary; keep it in the ladder but expect
  it never to be reached.
