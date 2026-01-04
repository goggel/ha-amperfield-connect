"""Binary sensor platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_NAME_PREFIX,
    DEFAULT_NAME_PREFIX,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODEL_MAPPING,
)
from .modbus_client import AmperfieldModbusClient
from .sensor import AmperfieldDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield binary sensor entities from a config entry."""
    client: AmperfieldModbusClient = hass.data[DOMAIN][config_entry.entry_id]

    scan_interval = config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    name_prefix = config_entry.data.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX)

    coordinator = AmperfieldDataUpdateCoordinator(
        hass,
        client,
        scan_interval,
    )

    await coordinator.async_config_entry_first_refresh()

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

    # Only add phase switching available sensor if phase switching is supported (solar/solar pro models)
    if coordinator.data.get("phase_switch_state") is not None:
        entities.append(AmperfieldPhaseSwitchingAvailableBinarySensor(coordinator, device_info, name_prefix))

    if entities:
        async_add_entities(entities)


class AmperfieldBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    """Base class for Amperfield binary sensor entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._name_prefix = name_prefix


class AmperfieldPhaseSwitchingAvailableBinarySensor(AmperfieldBinarySensorBase):
    """Diagnostic binary sensor showing if automatic phase switching is available."""

    _attr_translation_key = "phase_switching_available"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_phase_switching_available"

    @property
    def is_on(self) -> bool:
        """Return true if phase switching is available."""
        return self.coordinator.data.get("phase_switch_state") is not None
