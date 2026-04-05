"""Button platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AmperfieldDataUpdateCoordinator
from .const import DOMAIN
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield button entities from a config entry."""
    runtime_data = config_entry.runtime_data
    client: AmperfieldModbusClient = runtime_data.client
    coordinator: AmperfieldDataUpdateCoordinator = runtime_data.coordinator
    device_info: DeviceInfo = runtime_data.device_info
    serial_number: str | None = runtime_data.serial_number

    # Disconnect simulation only available on solar/solar pro models
    if coordinator.data.get("phase_switch_state") is not None:
        _LOGGER.debug("Solar/Solar PRO model detected, adding disconnect simulation button")
        async_add_entities([
            AmperfieldDisconnectSimulationButton(client, device_info, serial_number),
        ])
    else:
        _LOGGER.debug("No button entities to set up (non-solar model)")


class AmperfieldDisconnectSimulationButton(ButtonEntity):
    """Button entity for disconnect simulation command."""

    _attr_has_entity_name = True
    _attr_translation_key = "disconnect_simulation"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the button entity."""
        self.client = client
        self._attr_device_info = device_info
        prefix = serial_number or "amperfield"
        self._attr_unique_id = f"{prefix}_disconnect_simulation"

    async def async_press(self) -> None:
        """Handle the button press - send disconnect simulation command (value 73)."""
        _LOGGER.debug("Sending disconnect simulation command")
        success = await self.client.set_disconnect_simulation()
        if not success:
            _LOGGER.error("Failed to send disconnect simulation command")
