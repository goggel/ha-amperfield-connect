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
        AmperfieldChargingAllowedBinarySensor(coordinator, device_info, name_prefix),
        AmperfieldVehicleRequestsChargingBinarySensor(coordinator, device_info, name_prefix),
    ]

    # Only add phase switching available sensor if phase switching is supported (solar/solar pro models)
    if coordinator.data.get("phase_switch_state") is not None:
        entities.append(AmperfieldPhaseSwitchingAvailableBinarySensor(coordinator, device_info, name_prefix))

    async_add_entities(entities)


class AmperfieldBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    """Base class for Amperfield binary sensor entities."""

    _attr_has_entity_name = True
    _required_data_keys: list[str] = []  # Override in subclasses

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

    async def async_added_to_hass(self) -> None:
        """Register data subscriptions when entity is added."""
        await super().async_added_to_hass()
        if self._required_data_keys:
            self.coordinator.subscribe(self.entity_id, self._required_data_keys)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister subscriptions when entity is removed."""
        self.coordinator.unsubscribe(self.entity_id)
        await super().async_will_remove_from_hass()


class AmperfieldPhaseSwitchingAvailableBinarySensor(AmperfieldBinarySensorBase):
    """Diagnostic binary sensor showing if automatic phase switching is available."""

    _attr_translation_key = "phase_switching_available"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["phase_switch_state"]

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
    _required_data_keys = ["charging_state"]

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
        # Vehicle is plugged in states 4-8
        # 4: B1, 5: B2, 6: C1, 7: C2, 8: derating
        return 4 <= state <= 8


class AmperfieldChargingAllowedBinarySensor(AmperfieldBinarySensorBase):
    """Binary sensor showing if the wallbox allows charging."""

    _attr_translation_key = "charging_allowed"
    _required_data_keys = ["charging_state"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_charging_allowed"

    @property
    def is_on(self) -> bool | None:
        """Return true if the wallbox allows charging."""
        state = self.coordinator.data.get("charging_state")
        if state is None:
            return None
        # Wallbox allows charging in these states:
        # 3: A2 (no vehicle, wallbox allows)
        # 5: B2 (vehicle plugged, no charge request, wallbox allows)
        # 7: C2 (vehicle plugged, charge request, wallbox allows = charging)
        return state in (3, 5, 7)


class AmperfieldVehicleRequestsChargingBinarySensor(AmperfieldBinarySensorBase):
    """Binary sensor showing if the vehicle is requesting to charge."""

    _attr_translation_key = "vehicle_requests_charging"
    _required_data_keys = ["charging_state"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_vehicle_requests_charging"

    @property
    def is_on(self) -> bool | None:
        """Return true if the vehicle is requesting to charge."""
        state = self.coordinator.data.get("charging_state")
        if state is None:
            return None
        # Vehicle requests charging in these states:
        # 6: C1 (charge request, wallbox doesn't allow)
        # 7: C2 (charge request, wallbox allows = charging)
        return state in (6, 7)
