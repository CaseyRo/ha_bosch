#!/usr/bin/env python3
"""Read-only probe of boost + comfort-control resources via local XMPP.

Investigation for openspec change `pointtapi-bulk-discovery-and-controls`
(task 1.1): fetch full detail (type/writeable/value/enums) for the
never-probed boost resources and the new comfort-control paths.

Run with:
  uv run --with bosch-thermostat-client==0.28.2 python probe_boost_resources.py
"""
import asyncio
import json
import logging
import sys
from datetime import datetime

logging.basicConfig(level=logging.WARNING)

# Same connection credentials as explore_easycontrol.py
SERIALS = [("no dashes", "101506113"), ("with dashes", "101-506-113")]
ACCESS_TOKEN = "2YgL-zeab-ezZw-zrwN"
PASSWORD = "amstelbier"

# Read-only probe set: boost ladder inputs + comfort controls + curiosities
PROBE_PATHS = [
    "/heatingCircuits/hc1/boostShortcut",
    "/heatingCircuits/hc1/boostZones",
    "/heatingCircuits/hc1/boostMode",
    "/heatingCircuits/hc1/boostDuration",
    "/heatingCircuits/hc1/boostRemainingTime",
    "/heatingCircuits/hc1/buildingHeatup",
    "/heatingCircuits/hc1/seasonOptMode",
    "/heatingCircuits/hc1/setpointOptimization",
    "/heatingCircuits/hc1/minOutdoorTemp",
    "/heatingCircuits/hc1/operatingSeason",
    "/heatingCircuits/hc1/type",
    "/heatingCircuits/hc1/typeRoomControl",
    "/heatingCircuits/hc1/heatCurveMax",
    "/heatingCircuits/hc1/heatCurveMin",
    "/system/awayMode/enabled",
    "/notifications",
    "/dhwCircuits/dhw1/extraDhw",
    "/dhwCircuits/dhw1/extraDhwDuration",
    "/dhwCircuits/dhw1/thermalDisinfect/time",
    "/dhwCircuits/dhw1/thermalDisinfect/weekDay",
    "/dhwCircuits/dhw1/thermalDisinfect/lastResult",
    "/devices/list",
]


async def main():
    import bosch_thermostat_client
    from bosch_thermostat_client.const import XMPP
    from bosch_thermostat_client.const.easycontrol import EASYCONTROL

    BoschGateway = bosch_thermostat_client.gateway_chooser(device_type=EASYCONTROL)
    gateway = None
    for label, serial in SERIALS:
        gw = BoschGateway(
            host=serial,
            access_token=ACCESS_TOKEN,
            session_type=XMPP,
            password=PASSWORD,
            session=asyncio.get_event_loop(),
        )
        try:
            uuid = await gw.check_connection()
            if uuid:
                gateway = gw
                print(f"Connected ({label}). UUID: {uuid}", file=sys.stderr)
                break
        except Exception as e:
            print(f"  Failed ({label}): {type(e).__name__}: {e}", file=sys.stderr)
        await gw.close(force=True)

    if not gateway:
        print("ERROR: connection failed", file=sys.stderr)
        sys.exit(1)

    results = {"timestamp": datetime.now().isoformat(), "probes": {}}
    try:
        for path in PROBE_PATHS:
            try:
                resp = await asyncio.wait_for(gateway.raw_query(path), timeout=15)
                results["probes"][path] = resp
            except Exception as e:
                results["probes"][path] = {"_error": f"{type(e).__name__}: {e}"}
    finally:
        await gateway.close(force=True)

    out = f"boost_probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved {out}", file=sys.stderr)
    print(json.dumps(results["probes"], indent=1))


if __name__ == "__main__":
    asyncio.run(main())
