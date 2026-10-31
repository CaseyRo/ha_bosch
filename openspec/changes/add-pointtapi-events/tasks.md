# Tasks

## 1. Probe the device

- [ ] 1.1 Read `/events/ev1` on 101506113 and record the valid `type` values, name length limit and id assignment rule in `docs/pointtapi-api.md`
- [ ] 1.1a Confirm whether an event carries or inherits the away setpoint (15 °C assumed by the blippstrom flow) and the write-to-gateway delay for HA-made events
- [ ] 1.2 Confirm on the device that a full-array PUT with one extra entry is accepted and appears on read-back

## 2. Read path

- [ ] 2.1 Add `/events/ev1` to the fast tier in `pointtapi_coordinator.py`; exclude `/events/list*` and `/events/ev2` from discovery
- [ ] 2.2 Add the events sensor in `pointtapi_entities.py` (count state, decoded entries as attributes, unavailable when absent)

## 3. Write path

- [ ] 3.1 Add an events helper (decode/encode names, read-modify-write under the update lock, read-back with bounded retry)
- [ ] 3.1a Register create with an optional service response returning the new id; delete takes one id
- [ ] 3.2 Register create and delete services in `services.py`, `services.yaml` and translations, with start<end and name validation

## 4. Diagnostics

- [ ] 4.1 Redact `/events` names and ids in `diagnostics.py` and the debug scan

## 5. Tests and docs

- [ ] 5.1 Unit tests: sensor decode, create, delete, invalid range, unknown id, device ignoring write (original array preserved), diagnostics redaction
- [ ] 5.2 Update README and CHANGELOG
- [ ] 5.3 Run `ruff check custom_components/bosch` and `python3 -m pytest --tb=short -q unittests`
