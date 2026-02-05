"""Select platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AmperfieldDataUpdateCoordinator
from .const import (
    CHARGING_STRATEGIES,
    DOMAIN,
)
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield select entities from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    client: AmperfieldModbusClient = data["client"]
    coordinator: AmperfieldDataUpdateCoordinator = data["coordinator"]
    device_info: DeviceInfo = data["device_info"]
    name_prefix: str = data["name_prefix"]

    entities = []

    # Check if phase switching is available (solar/solar pro models only)
    if coordinator.data.get("phase_switch_state") is not None:
        _LOGGER.debug("Solar/Solar PRO model detected, adding charging strategy select")
        entities.append(AmperfieldChargingStrategySelect(coordinator, client, device_info, name_prefix))

    if entities:
        _LOGGER.debug("Setting up %d select entities", len(entities))
        async_add_entities(entities)
    else:
        _LOGGER.debug("No select entities to set up (non-solar model)")


class AmperfieldChargingStrategySelect(CoordinatorEntity, SelectEntity):
    """Select entity for charging strategy."""

    _attr_has_entity_name = True
    _attr_translation_key = "charging_strategy"
    _attr_options = list(CHARGING_STRATEGIES.values())
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["charging_strategy"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.client = client
        self._attr_device_info = device_info
        self._attr_unique_id = f"{name_prefix.lower()}_charging_strategy"

    async def async_added_to_hass(self) -> None:
        """Register data subscriptions when entity is added."""
        await super().async_added_to_hass()
        if self._required_data_keys:
            self.coordinator.subscribe(self.entity_id, self._required_data_keys)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister subscriptions when entity is removed."""
        self.coordinator.unsubscribe(self.entity_id)
        await super().async_will_remove_from_hass()

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        value = self.coordinator.data.get("charging_strategy")
        if value is None:
            return None
        return CHARGING_STRATEGIES.get(value)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug("Changing charging strategy to '%s'", option)
        # Reverse lookup
        value = None
        for key, val in CHARGING_STRATEGIES.items():
            if val == option:
                value = key
                break

        if value is None:
            _LOGGER.error("Invalid charging strategy option: %s", option)
            return

        self.coordinator.data["charging_strategy"] = value
        self.async_write_ha_state()
        success = await self.client.set_charging_strategy(value)
        if not success:
            _LOGGER.error("Failed to set charging strategy to '%s'", option)
        await self.coordinator.async_request_refresh()
