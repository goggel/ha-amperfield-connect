"""Select platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CHARGING_STRATEGIES,
    CHARGING_STRATEGY_MANUAL,
    CHARGING_STRATEGY_SOLAR,
    CONF_NAME_PREFIX,
    DEFAULT_NAME_PREFIX,
    DOMAIN,
    MODEL_MAPPING,
)
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield select entities from a config entry."""
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

    entities = []

    # Check if phase switching is available (solar/solar pro models only)
    phase_switch_state = await hass.async_add_executor_job(client.get_phase_switch_state)
    if phase_switch_state is not None:
        # Only add charging strategy select
        # Phase switching is now controlled via Maximum Power Target (register 500)
        # instead of manual phase switch control (register 501)
        entities.append(AmperfieldChargingStrategySelect(client, device_info, name_prefix))

    if entities:
        async_add_entities(entities)


class AmperfieldSelectBase(SelectEntity):
    """Base class for Amperfield select entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the select entity."""
        self.client = client
        self._attr_device_info = device_info
        self._name_prefix = name_prefix


class AmperfieldChargingStrategySelect(AmperfieldSelectBase):
    """Select entity for charging strategy."""

    _attr_translation_key = "charging_strategy"
    _attr_options = list(CHARGING_STRATEGIES.values())
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(client, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_charging_strategy"

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        value = self.client.get_charging_strategy()
        if value is None:
            return None
        return CHARGING_STRATEGIES.get(value)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        # Reverse lookup
        value = None
        for key, val in CHARGING_STRATEGIES.items():
            if val == option:
                value = key
                break

        if value is None:
            _LOGGER.error("Invalid charging strategy option: %s", option)
            return

        await self.hass.async_add_executor_job(self.client.set_charging_strategy, value)
        # Request update
        self.async_write_ha_state()
