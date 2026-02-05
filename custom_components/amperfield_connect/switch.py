"""Switch platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import callback
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
        return self._attr_is_on

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        value = self.coordinator.data.get("remote_lock")
        if value is not None:
            # 0 = locked (on), 1 = unlocked (off)
            self._attr_is_on = value == 0
        else:
            _LOGGER.debug("remote_lock is None in coordinator data, keeping last known state")
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (lock charging) with optimistic update."""
        _LOGGER.debug("Locking charging via remote lock")
        self._attr_is_on = True
        self.async_write_ha_state()
        success = await self.client.set_remote_lock(True)
        if not success:
            _LOGGER.error("Failed to lock charging")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (unlock charging) with optimistic update."""
        _LOGGER.debug("Unlocking charging via remote lock")
        self._attr_is_on = False
        self.async_write_ha_state()
        success = await self.client.set_remote_lock(False)
        if not success:
            _LOGGER.error("Failed to unlock charging")
        await self.coordinator.async_request_refresh()
