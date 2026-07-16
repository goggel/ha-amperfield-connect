"""Select platform for Amperfield Wallbox Connect."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AmperfieldDataUpdateCoordinator
from .const import CHARGING_STRATEGIES
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield select entities from a config entry."""
    runtime_data = config_entry.runtime_data
    client: AmperfieldModbusClient = runtime_data.client
    coordinator: AmperfieldDataUpdateCoordinator = runtime_data.coordinator
    device_info: DeviceInfo = runtime_data.device_info
    serial_number: str = runtime_data.serial_number

    # Charging strategy only available on solar/solar pro models
    if runtime_data.supports_phase_switching:
        _LOGGER.debug("Solar/Solar PRO model detected, adding charging strategy select")
        async_add_entities(
            [
                AmperfieldChargingStrategySelect(
                    coordinator, client, device_info, serial_number
                ),
            ]
        )
    else:
        _LOGGER.debug("No select entities to set up (non-solar model)")


class AmperfieldChargingStrategySelect(CoordinatorEntity, SelectEntity):
    """Select entity for charging strategy."""

    _attr_has_entity_name = True
    _attr_translation_key = "charging_strategy"
    _attr_options = list(CHARGING_STRATEGIES.values())
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["charging_strategy"]
    coordinator: AmperfieldDataUpdateCoordinator

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.client = client
        self._attr_device_info = device_info
        self._attr_unique_id = f"{serial_number}_charging_strategy"
        self._optimistic_option: str | None = None

    async def async_added_to_hass(self) -> None:
        """Register data subscriptions when entity is added."""
        await super().async_added_to_hass()
        self.coordinator.subscribe(self.entity_id, self._required_data_keys)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister subscriptions when entity is removed."""
        self.coordinator.unsubscribe(self.entity_id)
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state when coordinator provides fresh data."""
        if self.coordinator.data.get("charging_strategy") is not None:
            self._optimistic_option = None
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        if self._optimistic_option is not None:
            return self._optimistic_option
        value = self.coordinator.data.get("charging_strategy")
        if value is None:
            return None
        return CHARGING_STRATEGIES.get(value)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug("Changing charging strategy to '%s'", option)
        value = next((k for k, v in CHARGING_STRATEGIES.items() if v == option), None)

        if value is None:
            _LOGGER.error("Invalid charging strategy option: %s", option)
            raise HomeAssistantError(f"Invalid charging strategy option: {option}")

        self._optimistic_option = option
        self.async_write_ha_state()
        success = await self.client.set_charging_strategy(value)
        if not success:
            _LOGGER.error("Failed to set charging strategy to '%s'", option)
            self._optimistic_option = None
            self.async_write_ha_state()
            raise HomeAssistantError(f"Failed to set charging strategy to {option}")
        await self.coordinator.async_request_refresh()
