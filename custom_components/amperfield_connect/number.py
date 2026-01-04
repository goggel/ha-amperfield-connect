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

from .const import CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX, DOMAIN, MODEL_MAPPING
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield number entities from a config entry."""
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

    # Get hardware max current to set the proper range
    hw_max_current = await hass.async_add_executor_job(client.get_hardware_max_current)
    if hw_max_current is None:
        hw_max_current = 16  # Default to 16A

    entities = [
        AmperfieldMaxCurrentNumber(client, device_info, name_prefix, hw_max_current),
        AmperfieldFailsafeCurrentNumber(client, device_info, name_prefix, hw_max_current),
    ]

    # Add max power target control if phase switching is available (solar/solar pro)
    phase_switch_state = await hass.async_add_executor_job(client.get_phase_switch_state)
    if phase_switch_state is not None:
        entities.append(AmperfieldMaxPowerNumber(client, device_info, name_prefix, hw_max_current))

    async_add_entities(entities)


class AmperfieldNumberBase(NumberEntity):
    """Base class for Amperfield number entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the number entity."""
        self.client = client
        self._attr_device_info = device_info
        self._name_prefix = name_prefix
        self._attr_mode = NumberMode.BOX


class AmperfieldMaxCurrentNumber(AmperfieldNumberBase):
    """Number entity for maximum current control."""

    _attr_translation_key = "max_current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_step = 0.1

    def __init__(
        self,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
        hw_max_current: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(client, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_max_current"
        self._attr_native_max_value = float(hw_max_current)

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.client.get_max_current()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        # According to documentation:
        # 60-160 = valid range (6.0A - 16.0A+ in 0.1A steps)
        await self.hass.async_add_executor_job(self.client.set_max_current, value)


class AmperfieldFailsafeCurrentNumber(AmperfieldNumberBase):
    """Number entity for failsafe current setting."""

    _attr_translation_key = "failsafe_current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_step = 0.1
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
        hw_max_current: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(client, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_failsafe_current"
        self._attr_native_max_value = float(hw_max_current)

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.client.get_failsafe_current()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.hass.async_add_executor_job(self.client.set_failsafe_current, value)


class AmperfieldMaxPowerNumber(AmperfieldNumberBase):
    """Number entity for maximum power target control (solar/solar pro only)."""

    _attr_translation_key = "max_power_target"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_min_value = 0
    _attr_native_step = 100

    def __init__(
        self,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
        hw_max_current: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(client, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_max_power_target"
        # Calculate max power: hw_max_current * 230V * 3 phases
        self._attr_native_max_value = float(hw_max_current * 230 * 3)

    @property
    def native_value(self) -> int | None:
        """Return the current value."""
        return self.client.get_max_power_target()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        # Set the power target, wallbox will automatically switch phases
        watts = int(value)
        await self.hass.async_add_executor_job(self.client.set_max_power_target, watts)
