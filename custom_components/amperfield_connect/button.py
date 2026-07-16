"""Button platform for Amperfield Wallbox Connect."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AmperfieldDataUpdateCoordinator
from .const import DOMAIN
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield button entities from a config entry."""
    runtime_data = config_entry.runtime_data
    if not runtime_data.supports_phase_switching:
        return

    unique_id = f"{runtime_data.serial_number}_disconnect_simulation"

    # The command used to be exposed as a switch. A platform cannot migrate an
    # entity between domains, so remove the obsolete registry entry before the
    # replacement button is added.
    registry = er.async_get(hass)
    old_entity_id = registry.async_get_entity_id("switch", DOMAIN, unique_id)
    if old_entity_id is not None:
        registry.async_remove(old_entity_id)

    async_add_entities(
        [
            AmperfieldDisconnectSimulationButton(
                runtime_data.coordinator,
                runtime_data.client,
                runtime_data.device_info,
                runtime_data.serial_number,
            )
        ]
    )


class AmperfieldDisconnectSimulationButton(CoordinatorEntity, ButtonEntity):
    """Trigger the wallbox disconnect simulation command."""

    _attr_has_entity_name = True
    _attr_translation_key = "disconnect_simulation"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.client = client
        self._attr_device_info = device_info
        self._attr_unique_id = f"{serial_number}_disconnect_simulation"

    async def async_press(self) -> None:
        """Send the documented disconnect simulation command value."""
        _LOGGER.debug("Triggering disconnect simulation")
        if not await self.client.set_disconnect_simulation(True):
            raise HomeAssistantError("Failed to trigger disconnect simulation")
        await self.coordinator.async_request_refresh()
