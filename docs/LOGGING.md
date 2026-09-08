# Logging Strategy for Bosch Custom Component

## Overview

This component implements a comprehensive debug logging strategy following Home Assistant best practices. Logging is structured to provide useful information at different levels while maintaining performance.

## Logging Levels

### DEBUG
- Detailed information for troubleshooting
- Entity updates and state changes
- Gateway connection details
- Component initialization steps
- API calls and responses (when enabled)

### INFO
- Component setup and initialization
- Successful device connections
- Important state changes
- Configuration changes

### WARNING
- Non-critical errors (e.g., entity temporarily unavailable)
- Deprecated feature usage
- Configuration issues

### ERROR
- Critical errors requiring attention
- Connection failures
- Authentication errors
- Unexpected exceptions

## Enabling Debug Logging

### Via Home Assistant UI

1. Go to **Settings** → **System** → **Logs**
2. Click **Download Full Home Assistant Log**
3. Or use the **Logger** integration to configure logging levels

### Via configuration.yaml

```yaml
logger:
  default: warning
  logs:
    custom_components.bosch: debug
    bosch_thermostat_client: debug
```

### Via Developer Tools

1. Go to **Developer Tools** → **YAML**
2. Add the logger configuration above
3. Restart Home Assistant

## Logging Features

### Library Logger Synchronization

The component automatically synchronizes the `bosch_thermostat_client` library logger level with the component logger level. This ensures that when debug logging is enabled for the component, the library also logs at debug level.

### Structured Logging

All log messages use structured format with key-value pairs for easy filtering and parsing:

```python
_LOGGER.debug(
    "Updating entity: component=%s, entity_id=%s, name=%s",
    component_type,
    entity.entity_id,
    entity.name,
)
```

### Context-Rich Messages

Log messages include relevant context:
- UUID for device identification
- Entity IDs and names
- Component types
- Protocol and connection details
- Error details with exception info (when debug enabled)

### Exception Logging

Exceptions are logged with full traceback when debug logging is enabled:

```python
_LOGGER.error(
    "Error message: uuid=%s, error=%s",
    self.uuid,
    err,
    exc_info=_LOGGER.isEnabledFor(logging.DEBUG),
)
```

## Logging Categories

### Initialization
- Component setup
- Gateway creation
- Connection establishment
- Platform registration

### Updates
- Entity state updates
- Component refresh cycles
- Recording sensor updates
- Statistics updates

### Errors
- Connection failures
- Authentication errors
- Device exceptions
- Unexpected errors

### Configuration
- Config flow steps
- Entry creation
- Options updates

## Best Practices

1. **Use appropriate log levels**: DEBUG for detailed info, INFO for important events, WARNING for issues, ERROR for failures
2. **Include context**: Always include UUID, entity_id, or other identifiers
3. **Structured format**: Use key=value format for easy parsing
4. **Exception info**: Include `exc_info=True` for errors when debug is enabled
5. **Performance**: Avoid logging in tight loops or high-frequency operations unless debug is enabled

## Troubleshooting

If you're experiencing issues:

1. Enable debug logging for both `custom_components.bosch` and `bosch_thermostat_client`
2. Check logs for:
   - Connection establishment messages
   - Entity update failures
   - Authentication errors
   - Gateway initialization issues
3. Look for patterns in error messages
4. Check UUID and entity_id in logs to identify specific devices/entities

## Example Log Output

### Normal Operation (INFO level)
```
INFO: Setting up Bosch component version 0.28.2 for device EASYCONTROL (12345) at 192.168.1.100 via HTTP
INFO: Bosch initialized successfully: uuid=12345, device_name=My Thermostat, platforms=['climate', 'sensor']
```

### Debug Operation (DEBUG level)
```
DEBUG: Initializing Bosch integration: device_type=EASYCONTROL, protocol=HTTP, host=192.168.1.100
DEBUG: Created HTTP session for gateway connection
DEBUG: Creating gateway instance in executor thread
DEBUG: Gateway instance created successfully
DEBUG: Checking connection to Bosch gateway: host=192.168.1.100, protocol=HTTP, device_type=EASYCONTROL
DEBUG: Gateway connection check completed successfully
DEBUG: Bosch BUS detected: type=EMS, uuid=12345, device_name=My Thermostat
DEBUG: Updating entity: component=climate, entity_id=climate.heating_circuit_1, name=Heating circuit 1
```
