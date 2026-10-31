# Spec Delta

## Purpose
Lets users see, create and delete EasyControl events (scheduled away/holiday periods) from Home Assistant, with every write verified against the device.

## ADDED Requirements

### Requirement: Event listing

The integration SHALL read `/events/ev1` and expose its entries (decoded name, start, end, type, id) as attributes of a sensor on the EasyControl Gateway device. The sensor state SHALL be the number of events. The read-only views `/events/list1`–`list3` and the failing `/events/ev2` SHALL NOT be polled.

#### Scenario: Events present

- **WHEN** `/events/ev1` holds two entries
- **THEN** the sensor state is 2 and its attributes list both entries with names decoded from base64

#### Scenario: Events path absent

- **WHEN** `/events/ev1` is absent from coordinator data
- **THEN** the sensor is unavailable

### Requirement: Event creation

A service SHALL create an event by reading the current array, appending the new entry (name base64-encoded) and PUTting the complete array to `/events/ev1`. It SHALL reject start ≥ end and a name that does not fit the device.

#### Scenario: Create an event

- **WHEN** the service is called with a name, start and end
- **THEN** the full array including the new entry is PUT to `/events/ev1`, and the call succeeds only after a read-back shows the entry

#### Scenario: Invalid range

- **WHEN** end is not after start
- **THEN** the service raises a validation error and nothing is sent

#### Scenario: Created id is returned

- **WHEN** an event is created successfully
- **THEN** the service response contains the id the device assigned, taken from the read-back

### Requirement: Event deletion

A service SHALL delete an event by id with the same read-modify-write and read-back as creation. Unknown ids SHALL raise an error without writing.

#### Scenario: Other events untouched

- **WHEN** an event is deleted by id and the array also holds events created in the Bosch app
- **THEN** the PUT array contains every other entry unchanged, names and ids included

#### Scenario: Delete an event

- **WHEN** the service is called with an existing id
- **THEN** the array without that entry is PUT and the read-back confirms it is gone

### Requirement: Verified writes

Every events write SHALL be read back and retried a bounded number of times if the device does not reflect it. If it never does, the service SHALL raise an error naming the path rather than report success.

#### Scenario: Device ignores a write

- **WHEN** read-back after every attempt still lacks the change
- **THEN** the service fails with an error and the sensor keeps showing the device's actual state

### Requirement: Event names are redacted in diagnostics

Diagnostics output SHALL redact event names and ids from `/events`.

#### Scenario: Diagnostics download

- **WHEN** diagnostics are generated for a device with events
- **THEN** no decoded or base64 event name appears in the output
