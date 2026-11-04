"""set_away_event: standing slot ev1 moved and verified."""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import sys
from pathlib import Path
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.bosch.const import POINTTAPI, SERVICE_SET_AWAY_EVENT
from custom_components.bosch.services import async_register_services

_spec = importlib.util.spec_from_file_location(
    "bosch_away_under_test", Path(__file__).resolve().parents[1] / "custom_components" / "bosch" / "__init__.py"
)
bosch_module = importlib.util.module_from_spec(_spec)
bosch_module.__package__ = "custom_components.bosch"
sys.modules["bosch_away_under_test"] = bosch_module
_spec.loader.exec_module(bosch_module)
BoschGatewayEntry = bosch_module.BoschGatewayEntry

b64 = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731


def _ev(name, start, end):
    return {"value": [{"name": b64(name), "start": start, "end": end, "type": "away", "id": 1}]}


def _entry(gets, put=None):
    e = object.__new__(BoschGatewayEntry)
    e._protocol = POINTTAPI
    e._update_lock = asyncio.Lock()
    e.gateway = SimpleNamespace(get=AsyncMock(side_effect=gets), put=put or AsyncMock(return_value=True))
    return e


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("bosch_away_under_test.asyncio.sleep", AsyncMock()):
        yield


@pytest.mark.asyncio
async def test_writes_one_element_and_verifies():
    old, new = _ev("Away (blippstrom)", "2099-12-30", "2099-12-31"), _ev("Away (blippstrom)", "2026-12-01", "2026-12-10")
    e = _entry([old, old, new])  # first read-back still stale, retry lands
    res = await e.set_away_event("Away (blippstrom)", "2026-12-01", "2026-12-10")
    assert res == {"name": "Away (blippstrom)", "start": "2026-12-01", "end": "2026-12-10", "verified": True}
    sent = e.gateway.put.await_args.kwargs["value"]
    assert len(sent) == 1 and sent[0]["id"] == 1 and sent[0]["start"] == "2026-12-01"


@pytest.mark.asyncio
async def test_device_ignoring_write_raises():
    old = _ev("Away (blippstrom)", "2099-12-30", "2099-12-31")
    e = _entry([old] * 4)
    with pytest.raises(HomeAssistantError, match="did not reflect"):
        await e.set_away_event("Away (blippstrom)", "2026-12-01", "2026-12-10")


@pytest.mark.asyncio
async def test_missing_slot_raises_without_put():
    e = _entry([RuntimeError("GET failed: 404")])
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await e.set_away_event("x", "2026-12-01", "2026-12-10")
    e.gateway.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_rejects_start_after_end_and_passes_iso():
    hass = MagicMock()
    async_register_services(hass, MagicMock())
    handler = {c.args[1]: c.args[2] for c in hass.services.async_register.call_args_list}[SERVICE_SET_AWAY_EVENT]
    g = SimpleNamespace(set_away_event=AsyncMock(return_value={"verified": True}))
    base = {ATTR_DEVICE_ID: ["d"], "name": "n"}
    with patch("custom_components.bosch.services.find_gateway_entry", return_value=[g]):
        with pytest.raises(ServiceValidationError):
            await handler(SimpleNamespace(data={**base, "start": date(2026, 12, 5), "end": date(2026, 12, 1)}))
        g.set_away_event.assert_not_awaited()
        res = await handler(SimpleNamespace(data={**base, "start": date(2026, 12, 1), "end": date(2026, 12, 1)}))
    assert res == {"verified": True}
    g.set_away_event.assert_awaited_once_with("n", "2026-12-01", "2026-12-01")
