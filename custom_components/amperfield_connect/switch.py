"""Switch platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AmperfieldDataUpdateCoordinator
from .const import DOMAIN
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield switch entities from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    client: AmperfieldModbusClient = data["client"]
    coordinator: AmperfieldDataUpdateCoordinator = data["coordinator"]
    device_info: DeviceInfo = data["device_info"]
    name_prefix: str = data["name_prefix"]

    entities = [
        AmperfieldRemoteLockSwitch(coordinator, client, device_info, name_prefix),
    ]

    _LOGGER.debug("Setting up %d switch entities", len(entities))
    async_add_entities(entities)


class AmperfieldRemoteLockSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity for charging lock control."""

    _attr_has_entity_name = True
    _attr_translation_key = "remote_lock"

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self.client = client
        self._attr_device_info = device_info
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
        value = self.coordinator.data.get("remote_lock")
        if value is None:
            return None
        # 0 = locked (on), 1 = unlocked (off)
        return value == 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (lock charging)."""
        _LOGGER.debug("Locking charging via remote lock")
        success = await self.hass.async_add_executor_job(self.client.set_remote_lock, True)
        if success:
            self.coordinator.data["remote_lock"] = 0
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to lock charging")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (unlock charging)."""
        _LOGGER.debug("Unlocking charging via remote lock")
        success = await self.hass.async_add_executor_job(self.client.set_remote_lock, False)
        if success:
            self.coordinator.data["remote_lock"] = 1
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to unlock charging")
        await self.coordinator.async_request_refresh()
