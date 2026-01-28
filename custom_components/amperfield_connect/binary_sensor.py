"""Binary sensor platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AmperfieldDataUpdateCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield binary sensor entities from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: AmperfieldDataUpdateCoordinator = data["coordinator"]
    device_info: DeviceInfo = data["device_info"]
    name_prefix: str = data["name_prefix"]

    entities = [
        AmperfieldVehicleConnectedBinarySensor(coordinator, device_info, name_prefix),
    ]

    # Only add phase switching available sensor if phase switching is supported (solar/solar pro models)
    if coordinator.data.get("phase_switch_state") is not None:
        entities.append(AmperfieldPhaseSwitchingAvailableBinarySensor(coordinator, device_info, name_prefix))

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


class AmperfieldVehicleConnectedBinarySensor(AmperfieldBinarySensorBase):
    """Binary sensor showing if a vehicle is connected."""

    _attr_translation_key = "vehicle_connected"
    _attr_device_class = BinarySensorDeviceClass.PLUG

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_vehicle_connected"

    @property
    def is_on(self) -> bool | None:
        """Return true if a vehicle is connected."""
        state = self.coordinator.data.get("charging_state")
        if state is None:
            return None
        # Vehicle is connected when state is between 3 and 8 (inclusive)
        # 3: vehicle_ready_to_connect, 4: vehicle_ready_to_charge,
        # 5: waiting_for_release, 6: charging_paused, 7: charging, 8: derating
        return 3 <= state <= 8
