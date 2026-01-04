"""Switch platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX, DOMAIN, MODEL_MAPPING
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield switch entities from a config entry."""
    client: AmperfieldModbusClient = hass.data[DOMAIN][config_entry.entry_id]
    name_prefix = config_entry.data.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX)

    # Get device info
    serial_number = await hass.async_add_executor_job(client.get_serial_number)
    firmware_version = await hass.async_add_executor_job(client.get_firmware_version)
    item_number = await hass.async_add_executor_job(client.get_item_number)

    # Get friendly model name from mapping
    model_name = MODEL_MAPPING.get(item_number, f"Unknown ({item_number})") if item_number else "Unknown"

    device_info = DeviceInfo(
        identifiers={(DOMAIN, serial_number or config_entry.entry_id)},
        name=f"Wallbox {serial_number}" if serial_number else "Amperfield Wallbox",
        manufacturer="Amperfield",
        model=model_name,
        sw_version=firmware_version,
        serial_number=serial_number,
    )

    entities = [
        AmperfieldRemoteLockSwitch(client, device_info, name_prefix),
    ]

    async_add_entities(entities)


class AmperfieldSwitchBase(SwitchEntity):
    """Base class for Amperfield switch entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the switch entity."""
        self.client = client
        self._attr_device_info = device_info
        self._name_prefix = name_prefix


class AmperfieldRemoteLockSwitch(AmperfieldSwitchBase):
    """Switch entity for charging lock control."""

    _attr_translation_key = "remote_lock"

    def __init__(
        self,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(client, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_remote_lock"

    @property
    def icon(self) -> str:
        """Return the icon based on lock state."""
        if self.is_on:
            return "mdi:lock"
        return "mdi:lock-open"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on (charging locked)."""
        value = self.client.get_remote_lock()
        if value is None:
            return None
        # 0 = locked (on), 1 = unlocked (off)
        return value == 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (lock charging)."""
        await self.hass.async_add_executor_job(self.client.set_remote_lock, True)
        # Request update
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (unlock charging)."""
        await self.hass.async_add_executor_job(self.client.set_remote_lock, False)
        # Request update
        self.async_write_ha_state()
