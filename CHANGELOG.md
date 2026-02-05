# Changelog

All notable changes to this Bosch Home Assistant custom component will be documented in this file.

## [Unreleased]

### Fixed
- Fixed blocking SSL operations warning by wrapping gateway instantiation in executor thread
  - SSL operations (`set_default_verify_paths`, `load_default_certs`, `load_verify_locations`) 
    occur during gateway creation and are now executed in a thread pool executor
  - Applies to both HTTP and XMPP protocol connections
  - Fixes Home Assistant warnings about blocking calls in the event loop

### Changed
- Restored original codebase from GitHub repository
- Kept only the `_patch_bosch_sensor_print()` fix for RecursionError prevention
- Removed all custom logging prefixes and executor thread workarounds

### Technical Details
- Gateway creation now uses `hass.async_add_executor_job()` to run blocking SSL operations
- HTTP session is created in event loop before executor call
- Exception handling added for gateway creation failures

## Notes

This component is based on the official repository:
https://github.com/bosch-thermostat/home-assistant-bosch-custom-component

The only modification from the original is:
1. The `_patch_bosch_sensor_print()` function to prevent RecursionError
2. Wrapping gateway creation in executor thread to avoid SSL blocking warnings
