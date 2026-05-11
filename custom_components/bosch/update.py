"""Support for Bosch POINTTAPI Update platform (v0.32.0).

Surfaces gateway firmware updates in HA's native Updates panel. POINTTAPI-only
— the legacy XMPP/HTTP path doesn't have firmware update info to expose, so
non-POINTTAPI entries no-op.
"""
from __future__ import annotations

import logging

from .const import CONF_PROTOCOL, POINTTAPI, UUID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Bosch Update entities from a config entry."""
    if config_entry.data.get(CONF_PROTOCOL) != POINTTAPI:
        async_add_entities([])
        return True

    from .pointtapi_entities import (
        BoschPoinTTAPIUpdateEntity,
        POINTTAPI_UPDATE_DESCRIPTIONS,
    )

    rt_data = config_entry.runtime_data
    coordinator = getattr(rt_data, "coordinator", None)
    if coordinator is None:
        async_add_entities([])
        return True

    uuid = config_entry.data.get(UUID)
    entities = [
        BoschPoinTTAPIUpdateEntity(
            coordinator,
            config_entry.entry_id,
            uuid,
            desc,
        )
        for desc in POINTTAPI_UPDATE_DESCRIPTIONS
    ]
    async_add_entities(entities)
    return True
