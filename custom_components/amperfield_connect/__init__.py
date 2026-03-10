"""The Amperfield Wallbox Connect integration."""
from __future__ import annotations

import asyncio
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
    REGISTER_MAP,
)
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.BUTTON,
]


class AmperfieldDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Amperfield data with smart entity subscription tracking."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AmperfieldModbusClient,
        scan_interval: int,
    ) -> None:
        """Initialize."""
        self.client = client
        self._subscriptions: dict[str, set[str]] = {}  # {data_key: {entity_id, ...}}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    def subscribe(self, entity_id: str, data_keys: list[str]) -> None:
        """Register entity's data requirements.

        Args:
            entity_id: The entity ID subscribing
            data_keys: List of data keys the entity needs
        """
        for key in data_keys:
            self._subscriptions.setdefault(key, set()).add(entity_id)
        _LOGGER.debug(
            "Entity %s subscribed to %d data keys: %s (total subscribers: %d)",
            entity_id,
            len(data_keys),
            data_keys,
            sum(len(subs) for subs in self._subscriptions.values()),
        )

    def unsubscribe(self, entity_id: str) -> None:
        """Remove entity's subscriptions.

        Args:
            entity_id: The entity ID to unsubscribe
        """
        removed_count = 0
        for subscribers in self._subscriptions.values():
            if entity_id in subscribers:
                subscribers.discard(entity_id)
                removed_count += 1
        _LOGGER.debug(
            "Entity %s unsubscribed from %d data keys (remaining subscribers: %d)",
            entity_id,
            removed_count,
            sum(len(subs) for subs in self._subscriptions.values()),
        )

    def _get_required_data_keys(self) -> set[str]:
        """Return data keys that have active subscribers."""
        return {key for key, subs in self._subscriptions.items() if subs}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Modbus.

        Only fetches data for keys that have active entity subscriptions.
        Falls back to full fetch if no subscriptions exist yet.
        """
        try:
            required_keys = self._get_required_data_keys()

            if not required_keys:
                # No subscriptions yet (initial setup), use legacy fetch
                _LOGGER.debug("No entity subscriptions yet, using legacy fetch_all_data()")
                data = await self.client.fetch_all_data()
            else:
                data = await self.client.fetch_selected_data(required_keys)

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
        device_data = await client.fetch_device_info()
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
            configuration_url=f"http://{host}",
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
        await client.close()
        # Wait for wallbox to release the TCP socket (only accepts one connection)
        await asyncio.sleep(2)
        _LOGGER.info("Amperfield Wallbox integration unloaded")

    return unload_ok
