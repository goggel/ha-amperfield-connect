"""The Amperfield Wallbox Connect integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import ipaddress
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODEL_MAPPING,
    PHASE_SWITCHING_ITEM_NUMBERS,
)
from .modbus_client import AmperfieldModbusClient

type AmperfieldConfigEntry = ConfigEntry[AmperfieldRuntimeData]

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.BUTTON,
]

PARALLEL_UPDATES = 1


@dataclass
class AmperfieldRuntimeData:
    """Runtime data stored on the config entry."""

    client: AmperfieldModbusClient
    coordinator: AmperfieldDataUpdateCoordinator
    device_info: DeviceInfo
    serial_number: str
    hw_max_current: int
    supports_phase_switching: bool


class AmperfieldDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Amperfield data with smart entity subscription tracking."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AmperfieldConfigEntry,
        client: AmperfieldModbusClient,
        scan_interval: int,
        supports_phase_switching: bool,
    ) -> None:
        """Initialize."""
        self.client = client
        self.supports_phase_switching = supports_phase_switching
        self._subscriptions: dict[str, set[str]] = {}  # {data_key: {entity_id, ...}}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )

    def subscribe(self, entity_id: str, data_keys: list[str]) -> None:
        """Register entity's data requirements."""
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
        """Remove entity's subscriptions."""
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
                _LOGGER.debug(
                    "No entity subscriptions yet, using legacy fetch_all_data()"
                )
                data = await self.client.fetch_all_data(
                    supports_phase_switching=self.supports_phase_switching
                )
            else:
                data = await self.client.fetch_selected_data(required_keys)

            return data
        except Exception as err:
            _LOGGER.warning("Coordinator update failed: %s", err)
            raise UpdateFailed(f"Error communicating with device: {err}") from err


async def async_reload_entry(hass: HomeAssistant, entry: AmperfieldConfigEntry) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: AmperfieldConfigEntry) -> bool:
    """Set up Amperfield Wallbox Connect from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    _LOGGER.debug("Setting up Amperfield Wallbox at %s:%s", host, port)
    client = AmperfieldModbusClient(host, port)

    try:
        if not await client.connect():
            raise ConfigEntryNotReady(f"Cannot connect to {host}:{port}")

        _LOGGER.debug("Fetching device info from wallbox")
        device_data = await client.fetch_device_info()
    except Exception as err:
        await client.close()
        raise ConfigEntryNotReady(f"Cannot connect to {host}:{port}") from err

    try:
        serial_number = device_data.get("serial_number")
        firmware_version = device_data.get("firmware_version")
        item_number = device_data.get("item_number")
        hw_max_current = device_data.get("hw_max_current") or 16

        if not serial_number or "\N{REPLACEMENT CHARACTER}" in serial_number:
            raise ConfigEntryError("Wallbox did not return a hardware serial number")

        duplicate = next(
            (
                candidate
                for candidate in hass.config_entries.async_entries(DOMAIN)
                if candidate.entry_id != entry.entry_id
                and candidate.unique_id == serial_number
            ),
            None,
        )
        if duplicate is not None:
            raise ConfigEntryError(
                f"Wallbox {serial_number} is already configured by another entry"
            )
        if entry.unique_id != serial_number:
            hass.config_entries.async_update_entry(entry, unique_id=serial_number)

        if item_number in MODEL_MAPPING:
            supports_phase_switching = item_number in PHASE_SWITCHING_ITEM_NUMBERS
        else:
            supports_phase_switching = await client.probe_phase_switching()

        model_name = (
            MODEL_MAPPING.get(item_number, f"Unknown ({item_number})")
            if item_number
            else "Unknown"
        )

        _LOGGER.info(
            "Found Amperfield Wallbox: serial=%s, model=%s, firmware=%s, max_current=%dA",
            serial_number,
            model_name,
            firmware_version,
            hw_max_current,
        )

        configuration_host = host
        try:
            host_ip = ipaddress.ip_address(host)
        except ValueError:
            host_ip = None
        if host_ip is not None and host_ip.version == 6:
            configuration_host = f"[{host.replace('%', '%25')}]"

        device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            name=f"Wallbox {serial_number}",
            manufacturer="Amperfield",
            model=model_name,
            sw_version=firmware_version,
            serial_number=serial_number,
            configuration_url=f"http://{configuration_host}",
        )

        # Read scan_interval from options first (set via OptionsFlow), fall back to entry.data
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        _LOGGER.debug("Creating data coordinator with %ds scan interval", scan_interval)
        coordinator = AmperfieldDataUpdateCoordinator(
            hass,
            entry,
            client,
            scan_interval,
            supports_phase_switching,
        )
        await coordinator.async_config_entry_first_refresh()

    except ConfigEntryError:
        await client.close()
        raise
    except Exception as err:
        await client.close()
        raise ConfigEntryNotReady(f"Failed to set up device: {err}") from err

    entry.runtime_data = AmperfieldRuntimeData(
        client=client,
        coordinator=coordinator,
        device_info=device_info,
        serial_number=serial_number,
        hw_max_current=hw_max_current,
        supports_phase_switching=supports_phase_switching,
    )

    _LOGGER.debug("Setting up platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("Amperfield Wallbox integration setup complete for %s", serial_number)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AmperfieldConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Amperfield Wallbox integration")
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.close()
        # Wait for wallbox to release the TCP socket (only accepts one connection)
        await asyncio.sleep(2)
        _LOGGER.info("Amperfield Wallbox integration unloaded")

    return unload_ok
