#!/usr/bin/env python3
"""Test EasyControl XMPP connection with bosch_thermostat_client.

Run with PyPI release:
  uv run --with bosch-thermostat-client==0.28.2 python test_easycontrol_connection.py

Run with dev branch (latest from GitHub):
  uv run --with 'bosch-thermostat-client @ git+https://github.com/bosch-thermostat/bosch-thermostat-client-python.git@dev' python test_easycontrol_connection.py
"""
import asyncio
import logging
import sys

# Enable debug logging to see what's happening
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
# Reduce noise from slixmpp stringprep
logging.getLogger("slixmpp.stringprep").setLevel(logging.WARNING)

SERIAL = "101-506-113"
SERIAL_NO_DASHES = "101506113"  # try without dashes if auth fails
ACCESS_TOKEN = "2YgL-zeab-ezZw-zrwN"
# If you set a password in the Bosch/Buderus app, set it here (required for auth)
PASSWORD = None


async def main():
    import bosch_thermostat_client
    from bosch_thermostat_client.const import XMPP
    from bosch_thermostat_client.const.easycontrol import EASYCONTROL

    # Try XMPP: serial with dashes first, then without
    print("\n=== Trying XMPP ===")
    for label, serial in [("with dashes", SERIAL), ("no dashes", SERIAL_NO_DASHES)]:
        print("Library version:", bosch_thermostat_client.version)
        print("Connecting: EasyControl, XMPP")
        print("Serial ({}): {}".format(label, serial))
        print("Access token: (hidden)")
        print("Password set:", PASSWORD is not None)
        print("-" * 50)

        BoschGateway = bosch_thermostat_client.gateway_chooser(device_type=EASYCONTROL)
        gateway = BoschGateway(
            host=serial,
            access_token=ACCESS_TOKEN,
            session_type=XMPP,
            password=PASSWORD,
            session=asyncio.get_event_loop(),
        )

        try:
            uuid = await gateway.check_connection()
            if uuid:
                print("SUCCESS: Connected. UUID:", uuid)
                await gateway.close(force=True)
                return
            else:
                print("Connection returned no UUID (may still have connected)")
        except Exception as e:
            print("ERROR ({}):".format(label), type(e).__name__, str(e), file=sys.stderr)
        await gateway.close(force=True)

    print(
        "\nBoth serial formats failed. Try in HA with serial WITHOUT dashes: 101506113",
        file=sys.stderr,
    )
    print(
        "If you set a password in the Bosch/Buderus app, set PASSWORD in this script.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
