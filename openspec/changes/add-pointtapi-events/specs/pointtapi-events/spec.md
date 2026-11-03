# Spec Delta

## Purpose
Lets Home Assistant move the standing away event (`/events/ev1`) to new dates, with every write verified against the device.

## ADDED Requirements

### Requirement: Move the standing away event

`bosch.set_away_event` SHALL read `/events/ev1`, PUT a one-element array that keeps the slot's id and carries the given name (base64-encoded), start and end, and succeed only after a read-back shows those values. The read, write and read-back SHALL run under the gateway update lock. It SHALL NOT create or delete a slot.

#### Scenario: Move to trip dates

- **WHEN** the service is called with a name, start and end
- **THEN** a one-element array is PUT to `/events/ev1` and the response is `{name, start, end, verified: true}` after read-back

#### Scenario: Invalid input

- **WHEN** start is after end, or the name is empty or longer than 32 characters
- **THEN** the service raises a validation error and nothing is sent

#### Scenario: Slot missing

- **WHEN** `/events/ev1` returns 404 or holds no event
- **THEN** the service raises an error and nothing is written

### Requirement: Verified writes

The write SHALL be read back up to 3 times; if the device never reflects it, the service SHALL raise an error naming the path rather than report success.

#### Scenario: Device ignores a write

- **WHEN** every read-back still shows the old values
- **THEN** the service fails with an error that includes what the device shows
