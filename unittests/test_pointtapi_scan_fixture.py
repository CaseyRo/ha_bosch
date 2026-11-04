"""Real CT200 debug scan from #78 (7 zones, 3 programs), redacted, shared with consent."""
from __future__ import annotations

import json
import re
from pathlib import Path

from custom_components.bosch.pointtapi_entities import _zone_assigned_program_attributes

FIXTURE = Path(__file__).parent / "fixtures" / "pointtapi_ct200_scan_78.json"
RESOURCES = json.loads(FIXTURE.read_text())["resources"]


def test_zones_on_a_program_get_its_week_schedule():
    # zn4-6 report clockProgram 0 (no program, flat 15 °C) and get no schedule.
    programs = {}
    for n in range(1, 8):
        attrs = _zone_assigned_program_attributes(RESOURCES, f"zn{n}")
        programs[n] = attrs and attrs["program_id"]
        if attrs:
            assert set(attrs["schedule"]) == {
                "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
            }
            assert all(attrs["schedule"].values()), n
    assert programs == {1: "pg1", 2: "pg2", 3: "pg3", 4: None, 5: None, 6: None, 7: "pg2"}
    assert {"time": "08:00", "temperature": 20.5} in _zone_assigned_program_attributes(
        RESOURCES, "zn1"
    )["schedule"]["sunday"]


def test_fixture_carries_no_identifiers():
    # Keys the redaction blanks inside list values; any real value here is a leak.
    assert not re.search(r'"(sgtin|dlk|No)": "(?!\*\*REDACTED\*\*")', FIXTURE.read_text())
