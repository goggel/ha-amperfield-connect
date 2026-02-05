"""Number platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfPower
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
    """Set up Amperfield number entities from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    client: AmperfieldModbusClient = data["client"]
    coordinator: AmperfieldDataUpdateCoordinator = data["coordinator"]
    device_info: DeviceInfo = data["device_info"]
    name_prefix: str = data["name_prefix"]
    hw_max_current: int = data["hw_max_current"]

    entities: list[NumberEntity] = [
        AmperfieldMaxCurrentNumber(coordinator, client, device_info, name_prefix, hw_max_current),
        AmperfieldFailsafeCurrentNumber(coordinator, client, device_info, name_prefix, hw_max_current),
    ]

    # Add max power target control if phase switching is available (solar/solar pro)
    if coordinator.data.get("phase_switch_state") is not None:
        _LOGGER.debug("Solar/Solar PRO model detected, adding max power target control")
        entities.append(AmperfieldMaxPowerNumber(coordinator, client, device_info, name_prefix, hw_max_current))

    _LOGGER.debug("Setting up %d number entities", len(entities))
    async_add_entities(entities)


class AmperfieldNumberBase(CoordinatorEntity, NumberEntity):
    """Base class for Amperfield number entities."""

    _attr_has_entity_name = True
    _required_data_keys: list[str] = []  # Override in subclasses

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.client = client
        self._attr_device_info = device_info
        self._name_prefix = name_prefix
        self._attr_mode = NumberMode.BOX

    async def async_added_to_hass(self) -> None:
        """Register data subscriptions when entity is added."""
        await super().async_added_to_hass()
        if self._required_data_keys:
            self.coordinator.subscribe(self.entity_id, self._required_data_keys)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister subscriptions when entity is removed."""
        self.coordinator.unsubscribe(self.entity_id)
        await super().async_will_remove_from_hass()


class AmperfieldMaxCurrentNumber(AmperfieldNumberBase):
    """Number entity for maximum current control."""

    _attr_translation_key = "max_current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_step = 0.1
    _required_data_keys = ["max_current"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
        hw_max_current: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, client, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_max_current"
        self._attr_native_max_value = float(hw_max_current)

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.coordinator.data.get("max_current")

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with optimistic update."""
        _LOGGER.debug("Setting max current to %.1f A", value)
        # Optimistic update: reflect change immediately in UI
        self.coordinator.data["max_current"] = value
        self.async_write_ha_state()
        # Write to device and schedule refresh
        success = await self.client.set_max_current(value)
        if not success:
            _LOGGER.error("Failed to set max current to %.1f A", value)
        await self.coordinator.async_request_refresh()


class AmperfieldFailsafeCurrentNumber(AmperfieldNumberBase):
    """Number entity for failsafe current setting."""

    _attr_translation_key = "failsafe_current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_step = 0.1
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["failsafe_current"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
        hw_max_current: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, client, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_failsafe_current"
        self._attr_native_max_value = float(hw_max_current)

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.coordinator.data.get("failsafe_current")

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with optimistic update."""
        _LOGGER.debug("Setting failsafe current to %.1f A", value)
        self.coordinator.data["failsafe_current"] = value
        self.async_write_ha_state()
        success = await self.client.set_failsafe_current(value)
        if not success:
            _LOGGER.error("Failed to set failsafe current to %.1f A", value)
        await self.coordinator.async_request_refresh()


class AmperfieldMaxPowerNumber(AmperfieldNumberBase):
    """Number entity for maximum power target control (solar/solar pro only)."""

    _attr_translation_key = "max_power_target"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_min_value = 0
    _attr_native_step = 100
    _required_data_keys = ["max_power_target"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
        hw_max_current: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, client, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_max_power_target"
        # Calculate max power: hw_max_current * 230V * 3 phases
        self._attr_native_max_value = float(hw_max_current * 230 * 3)

    @property
    def native_value(self) -> int | None:
        """Return the current value."""
        return self.coordinator.data.get("max_power_target")

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with optimistic update."""
        watts = int(value)
        if 0 < watts < 1400:
            watts = 1400
            _LOGGER.debug("Rounding up max power target to minimum 1400 W")
        _LOGGER.debug("Setting max power target to %d W", watts)
        self.coordinator.data["max_power_target"] = watts
        self.async_write_ha_state()
        success = await self.client.set_max_power_target(watts)
        if not success:
            _LOGGER.error("Failed to set max power target to %d W", watts)
        await self.coordinator.async_request_refresh()
