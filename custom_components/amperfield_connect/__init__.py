"""The Amperfield Wallbox Connect integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amperfield Wallbox Connect from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    client = AmperfieldModbusClient(host, port)

    # Test connection
    try:
        await hass.async_add_executor_job(client.connect)
    except Exception as err:
        _LOGGER.error("Failed to connect to Amperfield Wallbox at %s:%s: %s", host, port, err)
        raise ConfigEntryNotReady(f"Cannot connect to {host}:{port}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        client: AmperfieldModbusClient = hass.data[DOMAIN].pop(entry.entry_id)
        await hass.async_add_executor_job(client.close)

    return unload_ok
