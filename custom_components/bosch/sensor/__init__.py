"""Support for Bosch Thermostat Sensor."""

from bosch_thermostat_client.const import (
    ECUS_RECORDING,
    RECORDING,
    REGULAR,
    SENSOR,
    SENSORS,
)
from bosch_thermostat_client.const.easycontrol import ENERGY
from homeassistant.helpers.dispatcher import async_dispatcher_send

from ..const import CIRCUITS, CONF_PROTOCOL, DOMAIN, POINTTAPI, SIGNAL_BOSCH, UUID
from ..pointtapi_entities import (
    BoschPoinTTAPISensorEntity,
    _pointtapi_sensor_descriptions,
)
from ..pointtapi_statistics import async_backfill_gas_history
from .bosch import BoschSensor
from .circuit import CircuitSensor
from .energy import EcusRecordingSensors, EnergySensor, EnergySensors
from .notifications import NotificationSensor
from .recording import RecordingSensor

SensorClass = {
    RECORDING: RecordingSensor,
    ENERGY: EnergySensor,
    ECUS_RECORDING: EnergySensor,
    REGULAR: BoschSensor,
    "notification": NotificationSensor,
}
SensorKinds = {
    RECORDING: RECORDING,
    ENERGY: RECORDING,
    ECUS_RECORDING: RECORDING,
    REGULAR: SENSOR,
    "notification": SENSOR,
}


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Bosch Thermostat from a config entry."""
    rt_data = config_entry.runtime_data
    if config_entry.data.get(CONF_PROTOCOL) == POINTTAPI:
        coordinator = rt_data.coordinator
        if coordinator:
            uuid = config_entry.data.get(UUID)
            # Conditional solar: skip the four solar-circuit descriptions if the
            # first coordinator refresh returned no usable /solarCircuits/sc1 data.
            # This stops non-solar households from seeing four ghost entities.
            solar_data = (coordinator.data or {}).get("/solarCircuits/sc1") or {}
            solar_has_refs = bool(solar_data.get("references"))
            descriptions = [
                desc for desc in _pointtapi_sensor_descriptions()
                if solar_has_refs or not desc.key.startswith("/solarCircuits")
            ]
            entities = [
                BoschPoinTTAPISensorEntity(
                    coordinator,
                    config_entry.entry_id,
                    uuid,
                    desc,
                )
                for desc in descriptions
            ]
            async_add_entities(entities)

            # Backfill gas history once after first coordinator update
            backfill_key = f"{DOMAIN}_gas_backfill_{config_entry.entry_id}"
            if backfill_key not in hass.data:
                hass.data[backfill_key] = True
                import logging
                _LOGGER = logging.getLogger(__name__)

                async def _do_backfill(_now=None):
                    _LOGGER.info("Gas history backfill: starting")
                    try:
                        if not coordinator.data:
                            await coordinator.async_request_refresh()
                        if coordinator.data:
                            await async_backfill_gas_history(
                                hass, coordinator.data, "sensor.pointtapi"
                            )
                        else:
                            _LOGGER.warning("Gas history backfill: no coordinator data available")
                    except Exception as err:
                        _LOGGER.warning("Gas history backfill failed: %s", err, exc_info=True)

                # Schedule after a short delay to let recorder initialize
                from homeassistant.helpers.event import async_call_later
                async_call_later(hass, 60, _do_backfill)
        else:
            async_add_entities([])
        return True
    uuid = config_entry.data[UUID]
    gateway = rt_data.gateway
    enabled_sensors = config_entry.data.get(SENSORS, [])

    new_stats_api = config_entry.options.get("new_stats_api", False)
    rt_data.sensor = []
    rt_data.recording = []

    def get_sensors(sensor):
        if sensor.kind in (RECORDING, REGULAR, "notification"):
            kwargs = (
                {
                    "new_stats_api": new_stats_api,
                }
                if sensor.kind == RECORDING
                else {}
            )
            return (
                SensorKinds[sensor.kind],
                [
                    SensorClass[sensor.kind](
                        hass=hass,
                        uuid=uuid,
                        bosch_object=sensor,
                        gateway=gateway,
                        name=sensor.name,
                        attr_uri=sensor.attr_id,
                        is_enabled=sensor.attr_id in enabled_sensors,
                        **kwargs
                    )
                ],
            )
        elif sensor.kind == ENERGY:
            return (
                SensorKinds[sensor.kind],
                [
                    SensorClass[sensor.kind](
                        hass=hass,
                        uuid=uuid,
                        bosch_object=sensor,
                        gateway=gateway,
                        sensor_attributes=energy,
                        attr_uri=sensor.attr_id,
                        new_stats_api=new_stats_api,
                        is_enabled=sensor.attr_id in enabled_sensors,
                    )
                    for energy in EnergySensors
                ],
            )
        elif sensor.kind == ECUS_RECORDING:
            return (
                SensorKinds[sensor.kind],
                [
                    SensorClass[sensor.kind](
                        hass=hass,
                        uuid=uuid,
                        bosch_object=sensor,
                        gateway=gateway,
                        sensor_attributes=energy,
                        attr_uri=sensor.attr_id,
                        new_stats_api=new_stats_api,
                        is_enabled=sensor.attr_id in enabled_sensors,
                    )
                    for energy in EcusRecordingSensors
                ],
            )
        return (None, None)

    target_map = {SENSOR: rt_data.sensor, RECORDING: rt_data.recording}
    for bosch_sensor in gateway.sensors:
        (target, sensors) = get_sensors(bosch_sensor)
        if not target:
            continue
        for sensor_entity in sensors:
            target_map[target].append(sensor_entity)

    for circ_type in CIRCUITS:
        circuits = gateway.get_circuits(circ_type)
        for circuit in circuits:
            for sensor in circuit.sensors:
                rt_data.sensor.append(
                    CircuitSensor(
                        hass=hass,
                        uuid=uuid,
                        bosch_object=sensor,
                        gateway=gateway,
                        name=sensor.name,
                        attr_uri=sensor.attr_id,
                        domain_name=circuit.name,
                        circuit_type=circ_type,
                        is_enabled=sensor.attr_id in enabled_sensors,
                    )
                )
    async_add_entities(rt_data.sensor)
    async_add_entities(rt_data.recording)
    async_dispatcher_send(hass, SIGNAL_BOSCH)
    return True
