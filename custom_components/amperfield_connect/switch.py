"""Switch platform for Amperfied Wallbox Connect."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AmperfieldDataUpdateCoordinator
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfied switch entities from a config entry."""
    runtime_data = config_entry.runtime_data
    client: AmperfieldModbusClient = runtime_data.client
    coordinator: AmperfieldDataUpdateCoordinator = runtime_data.coordinator
    device_info: DeviceInfo = runtime_data.device_info
    serial_number: str = runtime_data.serial_number

    entities: list[SwitchEntity] = [
        AmperfieldRemoteLockSwitch(coordinator, client, device_info, serial_number),
    ]

    _LOGGER.debug("Setting up %d switch entities", len(entities))
    async_add_entities(entities)


class AmperfieldRemoteLockSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity for charging lock control."""

    _attr_has_entity_name = True
    _attr_translation_key = "remote_lock"
    _required_data_keys = ["remote_lock"]
    coordinator: AmperfieldDataUpdateCoordinator

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self.client = client
        self._attr_device_info = device_info
        self._attr_unique_id = f"{serial_number}_remote_lock"
        self._optimistic_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Register data subscriptions when entity is added."""
        await super().async_added_to_hass()
        self.coordinator.subscribe(self.entity_id, self._required_data_keys)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister subscriptions when entity is removed."""
        self.coordinator.unsubscribe(self.entity_id)
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        """Return False if coordinator data for this entity is missing."""
        return (
            super().available and self.coordinator.data.get("remote_lock") is not None
        )

    @property
    def icon(self) -> str:
        """Return the icon based on lock state."""
        if self.is_on:
            return "mdi:lock"
        return "mdi:lock-open"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on (charging locked)."""
        if self._optimistic_is_on is not None:
            return self._optimistic_is_on
        value = self.coordinator.data.get("remote_lock")
        if value is None:
            return None
        # 0 = locked (on), 1 = unlocked (off)
        return value == 0

    @callback
    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state when coordinator provides fresh data."""
        if self.coordinator.data.get("remote_lock") is not None:
            self._optimistic_is_on = None
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (lock charging) with optimistic update."""
        _LOGGER.debug("Locking charging via remote lock")
        self._optimistic_is_on = True
        self.async_write_ha_state()
        success = await self.client.set_remote_lock(True)
        if not success:
            _LOGGER.error("Failed to lock charging")
            self._optimistic_is_on = None
            self.async_write_ha_state()
            raise HomeAssistantError("Failed to lock charging")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (unlock charging) with optimistic update."""
        _LOGGER.debug("Unlocking charging via remote lock")
        self._optimistic_is_on = False
        self.async_write_ha_state()
        success = await self.client.set_remote_lock(False)
        if not success:
            _LOGGER.error("Failed to unlock charging")
            self._optimistic_is_on = None
            self.async_write_ha_state()
            raise HomeAssistantError("Failed to unlock charging")
        await self.coordinator.async_request_refresh()
