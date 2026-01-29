"""The Amperfield Wallbox Connect integration."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_NAME_PREFIX,
    DEFAULT_NAME_PREFIX,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODEL_MAPPING,
)
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
]


class AmperfieldDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Amperfield data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AmperfieldModbusClient,
        scan_interval: int,
    ) -> None:
        """Initialize."""
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Modbus.

        Uses batch fetch to retrieve all data in a single connection,
        since the wallbox only supports one connection at a time.
        """
        _LOGGER.debug("Coordinator requesting data update")
        try:
            data = await self.hass.async_add_executor_job(self.client.fetch_all_data)
            _LOGGER.debug("Coordinator received data update successfully")
            return data
        except Exception as err:
            _LOGGER.warning("Coordinator update failed: %s", err)
            raise UpdateFailed(f"Error communicating with device: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amperfield Wallbox Connect from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    _LOGGER.debug("Setting up Amperfield Wallbox at %s:%s", host, port)
    client = AmperfieldModbusClient(host, port)

    # Test connection and fetch device info in a single connection
    try:
        _LOGGER.debug("Fetching device info from wallbox")
        device_data = await hass.async_add_executor_job(client.fetch_device_info)
    except Exception as err:
        _LOGGER.error("Failed to connect to Amperfield Wallbox at %s:%s: %s", host, port, err)
        raise ConfigEntryNotReady(f"Cannot connect to {host}:{port}") from err

    try:
        serial_number = device_data.get("serial_number")
        firmware_version = device_data.get("firmware_version")
        item_number = device_data.get("item_number")
        hw_max_current = device_data.get("hw_max_current") or 16  # Default to 16A

        # Get friendly model name from mapping
        model_name = MODEL_MAPPING.get(item_number, f"Unknown ({item_number})") if item_number else "Unknown"

        _LOGGER.info(
            "Found Amperfield Wallbox: serial=%s, model=%s, firmware=%s, max_current=%dA",
            serial_number,
            model_name,
            firmware_version,
            hw_max_current,
        )

        device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number or entry.entry_id)},
            name=f"Wallbox {serial_number}" if serial_number else "Amperfield Wallbox",
            manufacturer="Amperfield",
            model=model_name,
            sw_version=firmware_version,
            serial_number=serial_number,
        )

        # Create coordinator
        scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        _LOGGER.debug("Creating data coordinator with %ds scan interval", scan_interval)
        coordinator = AmperfieldDataUpdateCoordinator(hass, client, scan_interval)
        await coordinator.async_config_entry_first_refresh()

    except Exception as err:
        _LOGGER.error("Failed to set up Amperfield Wallbox: %s", err)
        raise ConfigEntryNotReady(f"Failed to set up device: {err}") from err

    # Store everything centrally for all platforms to use
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "device_info": device_info,
        "name_prefix": entry.data.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX),
        "hw_max_current": hw_max_current,
    }

    _LOGGER.debug("Setting up platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Amperfield Wallbox integration setup complete for %s", serial_number or host)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Amperfield Wallbox integration")
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        client: AmperfieldModbusClient = data["client"]
        await hass.async_add_executor_job(client.close)
        _LOGGER.info("Amperfield Wallbox integration unloaded")

    return unload_ok
