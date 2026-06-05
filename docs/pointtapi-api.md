# PointT API reference (as used by this integration)

The Bosch PointT API is the **unofficial, observed** cloud API behind the
EasyControl and HomeCom Easy mobile apps. Bosch can change it at any time —
which is why every adoption in this integration keeps a fallback path.

This document records what we use, how we learned it, and what we verified
against a live EasyControl CT200 (deviceType `rrc2`) on **2026-06-05**.

**Sources & credits**
- [serbanb11/homecom_alt](https://github.com/serbanb11/homecom_alt) — bulk
  endpoint wire format, gateway listing, RRC2 endpoint set
- [serbanb11/bosch-homecom-hass#78](https://github.com/serbanb11/bosch-homecom-hass/issues/78)
  — @joddye2's live CT200 resource dumps (types, `writeable` flags)
- [BassXT/buderus](https://github.com/BassXT/buderus) — PointT groundwork for
  MX300/K30
- Our own probes: `probe_boost_resources.py` (XMPP, read-only) and consented
  cloud probes; findings in
  `openspec/changes/pointtapi-bulk-discovery-and-controls/boost-probe-notes.md`
  (archived with the change)

## Base URLs

```
API root:      https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/
Resource base: {root}gateways/{deviceId}/resource/
Bulk:          {root}bulk
Gateways list: {root}gateways/
```

Auth: `Authorization: Bearer <access_token>` — OAuth2 + PKCE against
`singlekey-id.com`, client id `762162C0-FA2D-4540-AE66-6489F189FADC` (the
HomeCom Easy app's public client). Scope `pointt.gateway.list` enables the
gateway listing; `pointt.gateway.resource.dashapp` the resource routes.

## Account-level gateway listing

```
GET {root}gateways/        → 200
[{"deviceId": "1015xxxxx", "deviceType": "rrc2"}]
```

No human-readable name field. Used by the config flow for gateway
auto-discovery (verified live). `deviceType` values seen in the ecosystem:
`rrc2` (EasyControl/CT200), `rac`, `k30`, `k40`, `icom`, `wddw2`,
`commodule`, `watersoftener`.

## Bulk endpoint

`POST {root}bulk` — batch **reads**; ≤30 resource paths per request.

```jsonc
// Request
[{"gatewayId": "<deviceId>", "resourcePaths": ["/gateway", "/zones/zn1", ...]}]
// Paths WITHOUT the "/resource" prefix — including it yields per-path
// serverStatus 403 with a null gatewayResponse (homecom_alt's observation,
// reproduced).

// Response
[{
  "gatewayId": "<deviceId>",
  "resourcePaths": [{
    "resourcePath": "/gateway",
    "serverStatus": 200,            // cloud-side status
    "gatewayResponse": {
      "status": 200,                // device-side status
      "payload": { ... }            // identical to the direct-GET body
    }
  }, ...]
}]
```

A path's payload is valid only when **both** statuses are 200. Verified on
RRC2: payloads byte-identical to direct GETs. Bulk **writes** have never been
observed in the wild — we deliberately do not guess the format.

Rate-limit note (homecom_alt): concurrency >3 against the API runs into
internal queues/limits. Our coordinator issues bulk chunks sequentially.

## Resource paths used by this integration (RRC2)

All verified on a live CT200. `W` = `writeable: 1`.

### Polled roots (reference walk discovers one to two levels below each)

```
/gateway                  /heatingCircuits/hc1      /dhwCircuits/dhw1
/dhwCircuits/dhw1/operationMode    /system/sensors  /system/appliance
/zones/zn1                /energy                   /energy/history
/energy/historyHourly (paginated — ?next= cursor, stays on sequential GETs)
/heatSources              /solarCircuits/sc1        /notifications
/system/awayMode/enabled (leaf root — not reachable via other walks)
```

### Boost (native, v1.0.0)

| Path | Type | W | Notes |
|---|---|---|---|
| `/heatingCircuits/hc1/boostShortcut` | boostShortcutStruct | W | `[{mode, temperature, duration, zones:[int], allowedZones}]` — the app's one-shot boost command; probe ladder rung 1 |
| `/heatingCircuits/hc1/boostZones` | boostZoneStruct | W | `[{zones:[int], allowedZones:[int]}]` — integer zone ids, not `"zn1"` |
| `/heatingCircuits/hc1/boostMode` | stringValue | W | `on`/`off`. Direct cloud PUT returns 204 (the historical 403 ACL was lifted by Bosch) |
| `/heatingCircuits/hc1/boostTemperature` | floatValue | W | 5–30 °C, step 0.5 |
| `/heatingCircuits/hc1/boostDuration` | floatValue | W | 1–8 h, step 1 |
| `/heatingCircuits/hc1/boostRemainingTime` | floatValue | – | 0–480 min — real countdown under native boost |

### Comfort controls (v1.0.0)

| Path | Type | W | Notes |
|---|---|---|---|
| `/system/awayMode/enabled` | stringValue | W | `"true"`/`"false"` |
| `/dhwCircuits/dhw1/extraDhw` | stringValue | W | `"on"`/`"off"`; may report `available: "false"` on instant-DHW systems while still serving values |
| `/dhwCircuits/dhw1/extraDhwDuration` | floatValue | W | 15–2880 min, step 15 |
| `/dhwCircuits/dhw1/thermalDisinfect/state` | stringValue | W | existing switch |
| `/dhwCircuits/dhw1/thermalDisinfect/time` | floatValue | W | minute-of-day 0–1439 |
| `/dhwCircuits/dhw1/thermalDisinfect/weekDay` | stringValue | W | `Mo`/`Tu`/`We`/`Th`/`Fr`/`Sa`/`Su` |
| `/dhwCircuits/dhw1/thermalDisinfect/lastResult` | stringValue | – | e.g. `done` |
| `/notifications` | errorList | – | entries under `value` on RRC2 (`values` seen on other device types — read both) |

### Known-but-unused (future candidates, all verified present on CT200)

```
/heatingCircuits/hc1/buildingHeatup        stringValue  W  "normal"
/heatingCircuits/hc1/seasonOptMode         stringValue  W  allowedValues: [always_heating]
/heatingCircuits/hc1/setpointOptimization  stringValue  W  "off"
/heatingCircuits/hc1/heatCurveMax          floatValue   W  40–90 °C
/heatingCircuits/hc1/heatCurveMin          floatValue   W  20–90 °C
/heatingCircuits/hc1/minOutdoorTemp        floatValue   –  -10..-3 °C
/heatingCircuits/hc1/type                  stringValue  W  "convector"
/heatingCircuits/hc1/typeRoomControl       stringValue  W  "radiator"
/devices/list                              deviceArray  –  paired RF devices (name base64, zone, battery, signal)
/energy/electricity/*  /energy/currency  /energy/gas/{price,type,unit}
```

## Error semantics

- `401`/`403` on any route → token problem → integration raises
  `ConfigEntryAuthFailed` → HA reauth flow
- Per-path failures inside a bulk 200 envelope → skip the path that cycle
- Bulk route failing wholesale → coordinator falls back to sequential GETs
  for the cycle (v0.33 behavior); WARNING throttled to once per hour
- PUT acceptance is `204` (sometimes `200`); a 204 is **not** proof of
  behavior — the boost ladder confirms activation against the next refresh
