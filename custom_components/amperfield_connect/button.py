"""Button platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
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
    """Set up Amperfield button entities from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    client: AmperfieldModbusClient = data["client"]
    coordinator: AmperfieldDataUpdateCoordinator = data["coordinator"]
    device_info: DeviceInfo = data["device_info"]
    name_prefix: str = data["name_prefix"]

    entities = []

    # Disconnect simulation only available on solar/solar pro models
    if coordinator.data.get("phase_switch_state") is not None:
        _LOGGER.debug("Solar/Solar PRO model detected, adding disconnect simulation button")
        entities.append(AmperfieldDisconnectSimulationButton(coordinator, client, device_info, name_prefix))

    if entities:
        _LOGGER.debug("Setting up %d button entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No button entities to set up (non-solar model)")


class AmperfieldDisconnectSimulationButton(CoordinatorEntity, ButtonEntity):
    """Button entity for disconnect simulation command."""

    _attr_has_entity_name = True
    _attr_translation_key = "disconnect_simulation"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self.client = client
        self._attr_device_info = device_info
        self._attr_unique_id = f"{name_prefix.lower()}_disconnect_simulation"

    async def async_press(self) -> None:
        """Handle the button press - send disconnect simulation command (value 73)."""
        _LOGGER.debug("Sending disconnect simulation command")
        success = await self.client.set_disconnect_simulation()
        if not success:
            _LOGGER.error("Failed to send disconnect simulation command")
        await self.coordinator.async_request_refresh()
