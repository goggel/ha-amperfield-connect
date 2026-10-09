"""Binary sensor platform for Amperfied Wallbox Connect."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AmperfieldDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfied binary sensor entities from a config entry."""
    runtime_data = config_entry.runtime_data
    coordinator: AmperfieldDataUpdateCoordinator = runtime_data.coordinator
    device_info: DeviceInfo = runtime_data.device_info
    serial_number: str = runtime_data.serial_number

    entities: list[BinarySensorEntity] = [
        AmperfieldVehicleConnectedBinarySensor(coordinator, device_info, serial_number),
        AmperfieldChargingAllowedBinarySensor(coordinator, device_info, serial_number),
        AmperfieldVehicleRequestsChargingBinarySensor(
            coordinator, device_info, serial_number
        ),
    ]
    if runtime_data.supports_phase_switching:
        entities.append(
            AmperfieldDisconnectSimulationStatusBinarySensor(
                coordinator, device_info, serial_number
            )
        )
    async_add_entities(entities)


class AmperfieldBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    """Base class for Amperfied binary sensor entities."""

    _attr_has_entity_name = True
    _required_data_keys: list[str] = []
    coordinator: AmperfieldDataUpdateCoordinator

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._serial_number = serial_number

    def _unique_id(self, suffix: str) -> str:
        """Build a stable unique_id based on serial number."""
        return f"{self._serial_number}_{suffix}"

    async def async_added_to_hass(self) -> None:
        """Register data subscriptions when entity is added."""
        await super().async_added_to_hass()
        if self._required_data_keys:
            self.coordinator.subscribe(self.entity_id, self._required_data_keys)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister subscriptions when entity is removed."""
        self.coordinator.unsubscribe(self.entity_id)
        await super().async_will_remove_from_hass()


class AmperfieldVehicleConnectedBinarySensor(AmperfieldBinarySensorBase):
    """Binary sensor showing if a vehicle is connected."""

    _attr_translation_key = "vehicle_connected"
    _attr_device_class = BinarySensorDeviceClass.PLUG
    _required_data_keys = ["charging_state"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self._attr_unique_id = self._unique_id("vehicle_connected")

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
        serial_number: str | None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self._attr_unique_id = self._unique_id("charging_allowed")

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
        serial_number: str | None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self._attr_unique_id = self._unique_id("vehicle_requests_charging")

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


class AmperfieldDisconnectSimulationStatusBinarySensor(AmperfieldBinarySensorBase):
    """Show whether disconnect simulation is currently active."""

    _attr_translation_key = "disconnect_simulation_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["disconnect_simulation_status"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        serial_number: str,
    ) -> None:
        """Initialize the status sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self._attr_unique_id = self._unique_id("disconnect_simulation_status")

    @property
    def is_on(self) -> bool | None:
        """Return whether disconnect simulation is active."""
        value = self.coordinator.data.get("disconnect_simulation_status")
        return None if value is None else value == 1
