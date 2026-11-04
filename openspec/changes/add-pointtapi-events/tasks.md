# Tasks

Standing-slot model (design.md, "Standing slot"). Slot creation/deletion is out of scope.

## 1. Ship set_away_event

- [x] 1.1 `BoschGatewayEntry.set_away_event`: GET ev1, one-element PUT under the update lock, bounded read-back, raise on mismatch or missing slot
- [x] 1.2 Service `bosch.set_away_event` in `services.py`, `services.yaml`, `const.py` (start <= end, name length, optional response)
- [x] 1.3 Unit tests incl. device ignoring the write and missing slot (`unittests/test_set_away_event.py`)
- [x] 1.4 CHANGELOG
- [ ] 1.5 Beta release, HACS update on realnasivm (one at a time, back up first)
- [ ] 1.6 Tell the Node-RED side the service name (nr to-do "wire Bosch away flow")

## 2. Follow-ups (not blockers)

- [ ] 2.1 Events sensor reading `/events/ev1` (fast tier; skip `list*`, `ev2`)
- [ ] 2.2 Redact event names in diagnostics and the debug scan
- [ ] 2.3 Probe name length limit and the away setpoint source
- [ ] 2.4 Capture the app's slot-creation request
