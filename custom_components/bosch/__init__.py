"""Platform to control a Bosch IP thermostats units."""
from __future__ import annotations

import asyncio
import builtins
import logging
import random
from collections.abc import Awaitable
from datetime import timedelta
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from bosch_thermostat_client.const import (
    DHW,
    HC,
    HTTP,
    NUMBER,
    RECORDING,
    SC,
    SELECT,
    SENSOR,
    XMPP,
    ZN,
)
from bosch_thermostat_client.const.easycontrol import DV
from bosch_thermostat_client.exceptions import (
    DeviceException,
    EncryptionException,
    FirmwareException,
    UnknownDevice,
)
from bosch_thermostat_client.version import __version__ as LIBVERSION

# Patch bosch_thermostat_client: remove debug print() in get_sensor_class that
# causes RecursionError in Home Assistant (stdout wrapped by colorama).
def _patch_bosch_sensor_print():
    import bosch_thermostat_client.sensors.sensors as _sensors_mod
    _orig = _sensors_mod.get_sensor_class

    def _get_sensor_class_no_print(device_type, sensor_type):
        _old_print = builtins.print
        builtins.print = lambda *a, **k: None
        try:
            return _orig(device_type, sensor_type)
        finally:
            builtins.print = _old_print

    _sensors_mod.get_sensor_class = _get_sensor_class_no_print


_patch_bosch_sensor_print()

from homeassistant.components.persistent_notification import (
    async_create as async_create_persistent_notification,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ADDRESS,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_utc_time,
    async_track_time_interval,
)
from homeassistant.helpers.json import save_json
from homeassistant.helpers.network import get_url
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util
from homeassistant.util.json import load_json

from .switch import SWITCH

from .pointtapi_client import PoinTTAPIClient
from .pointtapi_coordinator import PoinTTAPIDataUpdateCoordinator
from .pointtapi_oauth import ensure_valid_token

from .const import (
    ACCESS_KEY,
    ACCESS_TOKEN,
    BINARY_SENSOR,
    BOSCH_GATEWAY_ENTRY,
    CLIMATE,
    CONF_DEVICE_TYPE,
    CONF_PROTOCOL,
    DOMAIN,
    FIRMWARE_SCAN_INTERVAL,
    FW_INTERVAL,
    GATEWAY,
    INTERVAL,
    NOTIFICATION_ID,
    POINTTAPI,
    RECORDING_INTERVAL,
    SCAN_INTERVAL,
    SIGNAL_BINARY_SENSOR_UPDATE_BOSCH,
    SIGNAL_BOSCH,
    SIGNAL_CLIMATE_UPDATE_BOSCH,
    SIGNAL_DHW_UPDATE_BOSCH,
    SIGNAL_NUMBER,
    SIGNAL_SELECT,
    SIGNAL_SENSOR_UPDATE_BOSCH,
    SIGNAL_SOLAR_UPDATE_BOSCH,
    SIGNAL_SWITCH,
    SOLAR,
    UUID,
    WATER_HEATER,
)
from .services import (
    async_register_debug_service,
    async_register_services,
    async_remove_services,
)

SIGNALS = {
    CLIMATE: SIGNAL_CLIMATE_UPDATE_BOSCH,
    WATER_HEATER: SIGNAL_DHW_UPDATE_BOSCH,
    SENSOR: SIGNAL_SENSOR_UPDATE_BOSCH,
    BINARY_SENSOR: SIGNAL_BINARY_SENSOR_UPDATE_BOSCH,
    SOLAR: SIGNAL_SOLAR_UPDATE_BOSCH,
    SWITCH: SIGNAL_SWITCH,
    SELECT: SIGNAL_SELECT,
    NUMBER: SIGNAL_NUMBER,
}

SUPPORTED_PLATFORMS = {
    HC: [CLIMATE],
    DHW: [WATER_HEATER],
    SWITCH: [SWITCH],
    SELECT: [SELECT],
    NUMBER: [NUMBER],
    SC: [SENSOR],
    SENSOR: [SENSOR, BINARY_SENSOR],
    ZN: [CLIMATE],
    DV: [SENSOR],
    RECORDING: [SENSOR],
}


CUSTOM_DB = "custom_bosch_db.json"
SERVICE_DEBUG_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_ids})
SERVICE_INTEGRATION_SCHEMA = vol.Schema({vol.Required(UUID): int})

TASK = "task"

DATA_CONFIGS = "bosch_configs"

_LOGGER = logging.getLogger(__name__)

# Configure library logger to match component logger level
# This ensures debug logging works for both component and library
_LIBRARY_LOGGER = logging.getLogger("bosch_thermostat_client")

HOUR = timedelta(hours=1)


async def async_setup(hass: HomeAssistant, config: ConfigType):
    """Initialize the Bosch platform."""
    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Create entry for Bosch thermostat device."""
    uuid = entry.data[UUID]
    host = entry.data[CONF_ADDRESS]
    protocol = entry.data[CONF_PROTOCOL]
    device_type = entry.data[CONF_DEVICE_TYPE]
    
    _LOGGER.info(
        "Setting up Bosch component version %s for device %s (%s) at %s via %s",
        LIBVERSION,
        device_type,
        uuid,
        host,
        protocol,
    )
    
    # Sync library logger level with component logger level
    # This enables debug logging for the library when component debug is enabled
    log_level = _LOGGER.getEffectiveLevel()
    _LIBRARY_LOGGER.setLevel(log_level)
    _LOGGER.debug("Library logger level set to %s", logging.getLevelName(log_level))
    
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    gateway_entry = BoschGatewayEntry(
        hass=hass,
        uuid=uuid,
        host=host,
        protocol=protocol,
        device_type=device_type,
        access_key=entry.data[ACCESS_KEY],
        access_token=entry.data[ACCESS_TOKEN],
        entry=entry,
    )
    hass.data[DOMAIN][uuid] = {BOSCH_GATEWAY_ENTRY: gateway_entry}
    _init_status: bool = await gateway_entry.async_init()
    if not _init_status:
        _LOGGER.error("Failed to initialize Bosch gateway for UUID %s", uuid)
        return _init_status
    async_register_services(hass, entry)
    _LOGGER.debug("Bosch component setup completed successfully for UUID %s", uuid)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    _LOGGER.debug("Removing entry.")
    uuid = entry.data[UUID]
    if uuid not in hass.data[DOMAIN]:
        async_remove_services(hass, entry)
        return True
    data = hass.data[DOMAIN][uuid]

    def remove_entry(key):
        value = data.pop(key, None)
        if value:
            value()

    remove_entry(INTERVAL)
    remove_entry(FW_INTERVAL)
    remove_entry(RECORDING_INTERVAL)
    bosch = hass.data[DOMAIN].pop(uuid)
    unload_ok = await bosch[BOSCH_GATEWAY_ENTRY].async_reset()
    async_remove_services(hass, entry)
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """Reload entry if options change."""
    _LOGGER.debug("Reloading entry %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


def create_notification_firmware(hass: HomeAssistant, msg):
    """Create notification about firmware to the user."""
    async_create_persistent_notification(
        hass,
        title="Bosch info",
        message=(
            "There are problems with config of your thermostat.\n"
            f"{msg}.\n"
            "You can create issue on Github, but first\n"
            "Go to [Developer Tools/Service](/developer-tools/service) and create bosch.debug_scan.\n"
            "[BoschGithub](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component)"
        ),
        notification_id=NOTIFICATION_ID,
    )


class BoschGatewayEntry:
    """Bosch gateway entry config class."""

    def __init__(
        self, hass, uuid, host, protocol, device_type, access_key, access_token, entry
    ) -> None:
        """Init Bosch gateway entry config class."""
        self.hass = hass
        self.uuid = uuid
        self._host = host
        self._access_key = access_key
        self._access_token = access_token
        self._device_type = device_type
        self._protocol = protocol
        self.config_entry = entry
        self._debug_service_registered = False
        self.gateway = None
        self.prefs = None
        self._initial_update = False
        self._signal_registered = False
        self.supported_platforms = []
        self._update_lock = None

    @property
    def device_id(self) -> str:
        return self.config_entry.entry_id

    async def async_init(self) -> bool:
        """Init async items in entry."""
        _LOGGER.debug(
            "Initializing Bosch integration: device_type=%s, protocol=%s, host=%s",
            self._device_type,
            self._protocol,
            self._host,
        )
        self._update_lock = asyncio.Lock()

        if self._protocol == POINTTAPI:
            session = async_get_clientsession(self.hass)
            try:
                token_callback = lambda: ensure_valid_token(
                    self.hass, self.config_entry, session
                )
                self.gateway = PoinTTAPIClient(
                    self._host, session, token_callback
                )
                await self.gateway.get("/gateway/DateTime")
            except ConfigEntryAuthFailed:
                raise
            except Exception as err:
                _LOGGER.warning(
                    "POINTTAPI connection check failed: %s",
                    err,
                    exc_info=_LOGGER.isEnabledFor(logging.DEBUG),
                )
                raise ConfigEntryNotReady(
                    f"Could not reach POINTTAPI: {err}"
                ) from err
            self.supported_platforms = [CLIMATE, WATER_HEATER, "sensor", BINARY_SENSOR, NUMBER, SWITCH, "select"]
            self.hass.data[DOMAIN][self.uuid][GATEWAY] = self.gateway
            coordinator = PoinTTAPIDataUpdateCoordinator(
                self.hass, self.config_entry, self.gateway
            )
            self.hass.data[DOMAIN][self.uuid]["coordinator"] = coordinator
            await coordinator.async_config_entry_first_refresh()
            device_registry = dr.async_get(self.hass)
            device_registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, self.uuid)},
                manufacturer="Bosch",
                model="EasyControl",
                name=f"EasyControl (POINTTAPI) {self._host}",
                sw_version="",
            )
            await self.hass.config_entries.async_forward_entry_setups(
                self.config_entry,
                [p for p in self.supported_platforms if p],
            )
            _LOGGER.info(
                "POINTTAPI gateway ready: device_id=%s",
                self._host,
            )
            return True

        import bosch_thermostat_client as bosch
        BoschGateway = bosch.gateway_chooser(device_type=self._device_type)
        
        # Get session in event loop before executor call (for HTTP only)
        session = None
        if self._protocol == HTTP:
            session = async_get_clientsession(self.hass, verify_ssl=False)
            _LOGGER.debug("Created HTTP session for gateway connection")
        
        # Wrap gateway instantiation in executor to avoid blocking SSL operations
        # SSL operations (set_default_verify_paths, load_default_certs, load_verify_locations)
        # happen during gateway creation and must run in executor thread
        def _create_gateway():
            _LOGGER.debug("Creating gateway instance in executor thread")
            gateway = BoschGateway(
                session=session,
                session_type=self._protocol,
                host=self._host,
                access_key=self._access_key,
                access_token=self._access_token,
            )
            # Log XMPP endpoint for EasyControl devices
            if self._protocol == XMPP and hasattr(gateway, '_connector'):
                connector = gateway._connector
                if hasattr(connector, 'xmpp_host'):
                    _LOGGER.info(
                        "XMPP endpoint configured: host=%s, device_type=%s",
                        connector.xmpp_host,
                        self._device_type,
                    )
                elif hasattr(connector, '__class__'):
                    # Try to get from class if instance doesn't have it
                    connector_class = connector.__class__
                    if hasattr(connector_class, 'xmpp_host'):
                        _LOGGER.info(
                            "XMPP endpoint configured: host=%s, device_type=%s",
                            connector_class.xmpp_host,
                            self._device_type,
                        )
            return gateway
        
        try:
            self.gateway = await self.hass.async_add_executor_job(_create_gateway)
            _LOGGER.debug("Gateway instance created successfully")
        except Exception as err:
            _LOGGER.error(
                "Failed to create Bosch gateway: device_type=%s, protocol=%s, host=%s, error=%s",
                self._device_type,
                self._protocol,
                self._host,
                err,
                exc_info=True,
            )
            raise ConfigEntryNotReady(
                f"Failed to initialize Bosch gateway: {err}"
            ) from err

        async def close_connection(event) -> None:
            """Close connection with server."""
            _LOGGER.debug("Closing connection to Bosch")
            await self.gateway.close()

        if await self.async_init_bosch():
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, close_connection)
            async_dispatcher_connect(
                self.hass, SIGNAL_BOSCH, self.async_get_signals
            )
            device_registry = dr.async_get(self.hass)
            device_registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, self.uuid)},
                manufacturer=self.gateway.device_model,
                model=self.gateway.device_type,
                name=self.gateway.device_name,
                sw_version=self.gateway.firmware,
            )
            await self.hass.config_entries.async_forward_entry_setups(
                self.config_entry,
                [component for component in self.supported_platforms if component != SOLAR]
            )
            if GATEWAY in self.hass.data[DOMAIN][self.uuid]:
                _LOGGER.debug("Registering debug services.")
                async_register_debug_service(hass=self.hass, entry=self)
            _LOGGER.debug(
                "Bosch component registered with platforms %s.",
                self.supported_platforms,
            )
            return True
        return False

    @callback
    def async_get_signals(self) -> None:
        """Prepare update after all entities are loaded."""
        if not self._signal_registered and all(
            k in self.hass.data[DOMAIN][self.uuid] for k in self.supported_platforms
        ):
            _LOGGER.debug("Registering thermostat update interval.")
            self._signal_registered = True
            self.hass.data[DOMAIN][self.uuid][INTERVAL] = async_track_time_interval(
                self.hass, self.thermostat_refresh, SCAN_INTERVAL
            )
            self.hass.data[DOMAIN][self.uuid][FW_INTERVAL] = async_track_time_interval(
                self.hass,
                self.firmware_refresh,
                FIRMWARE_SCAN_INTERVAL,  # Firmware scan interval
            )
            async_call_later(self.hass, 1, self.thermostat_refresh)
            asyncio.run_coroutine_threadsafe(self.recording_sensors_update(),
                self.hass.loop
            )

    async def async_init_bosch(self) -> bool:
        """Initialize Bosch gateway module."""
        _LOGGER.debug(
            "Checking connection to Bosch gateway: host=%s, protocol=%s, device_type=%s",
            self._host,
            self._protocol,
            self._device_type,
        )
        try:
            await self.gateway.check_connection()
            _LOGGER.debug("Gateway connection check completed successfully")
        except (FirmwareException) as err:
            create_notification_firmware(hass=self.hass, msg=err)
            _LOGGER.error(
                "Firmware exception during connection check: host=%s, error=%s",
                self._host,
                err,
                exc_info=True,
            )
            return False
        except (UnknownDevice, EncryptionException) as err:
            _LOGGER.error(
                "Authentication/connection error: host=%s, protocol=%s, error=%s",
                self._host,
                self._protocol,
                err,
                exc_info=True,
            )
            _LOGGER.warning(
                "You might need to check your password or access token for host %s",
                self._host,
            )
            raise ConfigEntryNotReady(
                f"Cannot connect to Bosch gateway, host {self._host} with UUID: {self.uuid}"
            ) from err
        if not self.gateway.uuid:
            _LOGGER.error(
                "Gateway UUID not found after connection: host=%s",
                self._host,
            )
            raise ConfigEntryNotReady(
                f"Cannot connect to Bosch gateway, host {self._host} with UUID: {self.uuid}"
            )
        _LOGGER.debug(
            "Bosch BUS detected: type=%s, uuid=%s, device_name=%s",
            self.gateway.bus_type,
            self.gateway.uuid,
            getattr(self.gateway, "device_name", "Unknown"),
        )
        if not self.gateway.database:
            custom_db = load_json(self.hass.config.path(CUSTOM_DB), default=None)
            if custom_db:
                _LOGGER.info("Loading custom db file.")
                await self.gateway.custom_initialize(custom_db)
        if self.gateway.database:
            # Suppress debug print() in bosch_thermostat_client (get_sensor_class + Sensors.__init__)
            # which causes RecursionError in HA when stdout is wrapped by colorama.
            _old_print = builtins.print
            builtins.print = lambda *a, **k: None
            try:
                supported_bosch = await self.gateway.get_capabilities()
            finally:
                builtins.print = _old_print
            _LOGGER.debug(
                "Bosch supported capabilities retrieved: %s",
                supported_bosch,
            )
            for supported in supported_bosch:
                elements = SUPPORTED_PLATFORMS[supported]
                for element in elements:
                    if element not in self.supported_platforms:
                        self.supported_platforms.append(element)
            _LOGGER.debug(
                "Supported platforms determined: %s",
                self.supported_platforms,
            )
        self.hass.data[DOMAIN][self.uuid][GATEWAY] = self.gateway
        _LOGGER.info(
            "Bosch initialized successfully: uuid=%s, device_name=%s, platforms=%s",
            self.gateway.uuid,
            getattr(self.gateway, "device_name", "Unknown"),
            self.supported_platforms,
        )
        return True

    async def recording_sensors_update(self, now=None) -> bool | None:
        """Update of 1-hour sensors.

        It suppose to be called only once an hour
        so sensor get's average data from Bosch.
        """
        entities = self.hass.data[DOMAIN][self.uuid].get(RECORDING, [])
        if not entities:
            return
        recording_callback = self.hass.data[DOMAIN][self.uuid].pop(
            RECORDING_INTERVAL, None
        )
        if recording_callback is not None:
            recording_callback()
            recording_callback = None
        updated = False
        signals = []
        now = dt_util.now()
        for entity in entities:
            if entity.enabled:
                try:
                    _LOGGER.debug("Updating component 1-hour Sensor by %s", id(self))
                    await entity.bosch_object.update(time=now)
                    updated = True
                    if entity.signal not in signals:
                        signals.append(entity.signal)
                except DeviceException as err:
                    _LOGGER.warning(
                        "Bosch object of entity %s is no longer available. %s",
                        entity.name,
                        err,
                    )

        def rounder(t):
            matching_seconds = [0]
            matching_minutes = [6]  # 6
            matching_hours = dt_util.parse_time_expression("*", 0, 23)
            return dt_util.find_next_time_expression_time(
                t, matching_seconds, matching_minutes, matching_hours
            )

        nexti = rounder(now + timedelta(seconds=1))
        self.hass.data[DOMAIN][self.uuid][
            RECORDING_INTERVAL
        ] = async_track_point_in_utc_time(
            self.hass, self.recording_sensors_update, nexti
        )
        _LOGGER.debug("Next update of 1-hour sensors scheduled at: %s", nexti)
        if updated:
            _LOGGER.debug("Bosch 1-hour entitites updated.")
            for signal in signals:
                async_dispatcher_send(self.hass, signal)
            return True

    async def custom_put(self, path: str, value: Any) -> None:
        """Send PUT directly to gateway without parsing."""
        await self.gateway.raw_put(path=path, value=value)

    async def custom_get(self, path) -> str:
        """Fetch value from gateway."""
        async with self._update_lock:
            return await self.gateway.raw_query(path=path)

    async def component_update(self, component_type=None, event_time=None):
        """Update data from HC, DHW, ZN, Sensors, Switch."""
        if component_type in self.supported_platforms:
            updated = False
            entities = self.hass.data[DOMAIN][self.uuid][component_type]
            entity_count = len(entities)
            _LOGGER.debug(
                "Updating component type %s: uuid=%s, entity_count=%d",
                component_type,
                self.uuid,
                entity_count,
            )
            for entity in entities:
                if entity.enabled:
                    try:
                        _LOGGER.debug(
                            "Updating entity: component=%s, entity_id=%s, name=%s",
                            component_type,
                            entity.entity_id,
                            entity.name,
                        )
                        await entity.bosch_object.update()
                        updated = True
                    except DeviceException as err:
                        _LOGGER.warning(
                            "Bosch object of entity %s (%s) is no longer available: %s",
                            entity.name,
                            entity.entity_id,
                            err,
                            exc_info=_LOGGER.isEnabledFor(logging.DEBUG),
                        )
            if updated:
                _LOGGER.debug(
                    "Bosch %s entities updated successfully: uuid=%s, updated_count=%d",
                    component_type,
                    self.uuid,
                    sum(1 for e in entities if e.enabled),
                )
                async_dispatcher_send(self.hass, SIGNALS[component_type])
                return True
            else:
                _LOGGER.debug(
                    "No updates for component type %s: uuid=%s",
                    component_type,
                    self.uuid,
                )
        else:
            _LOGGER.debug(
                "Component type %s not in supported platforms: uuid=%s, supported=%s",
                component_type,
                self.uuid,
                self.supported_platforms,
            )
        return False

    async def thermostat_refresh(self, event_time=None):
        """Call Bosch to refresh information."""
        if self._update_lock.locked():
            _LOGGER.debug(
                "Update already in progress for UUID %s. Skipping this update cycle.",
                self.uuid,
            )
            return
        _LOGGER.debug(
            "Starting Bosch thermostat refresh: uuid=%s, event_time=%s",
            self.uuid,
            event_time,
        )
        async with self._update_lock:
            await self.component_update(SENSOR, event_time)
            await self.component_update(BINARY_SENSOR, event_time)
            await self.component_update(CLIMATE, event_time)
            await self.component_update(WATER_HEATER, event_time)
            await self.component_update(SWITCH, event_time)
            await self.component_update(NUMBER, event_time)
            _LOGGER.debug(
                "Completed Bosch thermostat refresh: uuid=%s",
                self.uuid,
            )

    async def firmware_refresh(self, event_time=None):
        """Call Bosch to refresh firmware info."""
        if self._update_lock.locked():
            _LOGGER.debug("Update already in progress. Not updating.")
            return
        _LOGGER.debug("Updating info about Bosch firmware.")
        try:
            async with self._update_lock:
                await self.gateway.check_firmware_validity()
        except FirmwareException as err:
            create_notification_firmware(hass=self.hass, msg=err)

    async def make_rawscan(self, filename: str) -> dict:
        """Create rawscan from service."""
        rawscan = {}
        async with self._update_lock:
            _LOGGER.info("Starting rawscan of Bosch component")
            async_create_persistent_notification(
                self.hass,
                title="Bosch scan",
                message=("Starting rawscan"),
                notification_id=NOTIFICATION_ID,
            )
            rawscan = await self.gateway.rawscan()
            try:
                save_json(filename, rawscan)
            except (FileNotFoundError, OSError) as err:
                _LOGGER.error("Can't create file. %s", err)
                if rawscan:
                    return rawscan
            url = "{}{}{}".format(
                get_url(self.hass),
                "/local/bosch_scan.json?v",
                random.randint(0, 5000),
            )
            _LOGGER.info(f"Rawscan success. Your URL: {url}")
            async_create_persistent_notification(
                self.hass,
                title="Bosch scan",
                message=(f"[{url}]({url})"),
                notification_id=NOTIFICATION_ID,
            )
        return rawscan

    async def async_reset(self) -> bool:
        """Reset this device to default state."""
        _LOGGER.debug("Unloading Bosch module.")
        _LOGGER.debug("Closing connection to gateway.")
        tasks: list[Awaitable] = [
            self.hass.config_entries.async_forward_entry_unload(
                self.config_entry, platform
            )
            for platform in self.supported_platforms
        ]
        unload_ok = await asyncio.gather(*tasks)
        await self.gateway.close(force=False)
        return all(unload_ok)
