"""Sensor platform for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AmperfieldDataUpdateCoordinator
from .const import (
    CHARGING_STATES,
    DOMAIN,
    MODEL_MAPPING,
    PHASE_SWITCH_STATES,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield sensors from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: AmperfieldDataUpdateCoordinator = data["coordinator"]
    device_info: DeviceInfo = data["device_info"]
    name_prefix: str = data["name_prefix"]

    entities: list[SensorEntity] = [
        AmperfieldChargingStateSensor(coordinator, device_info, name_prefix),
        AmperfieldCurrentSensor(coordinator, device_info, name_prefix, "l1"),
        AmperfieldCurrentSensor(coordinator, device_info, name_prefix, "l2"),
        AmperfieldCurrentSensor(coordinator, device_info, name_prefix, "l3"),
        AmperfieldVoltageSensor(coordinator, device_info, name_prefix, "l1"),
        AmperfieldVoltageSensor(coordinator, device_info, name_prefix, "l2"),
        AmperfieldVoltageSensor(coordinator, device_info, name_prefix, "l3"),
        AmperfieldPowerSensor(coordinator, device_info, name_prefix, "total"),
        AmperfieldPowerSensor(coordinator, device_info, name_prefix, "l1"),
        AmperfieldPowerSensor(coordinator, device_info, name_prefix, "l2"),
        AmperfieldPowerSensor(coordinator, device_info, name_prefix, "l3"),
        AmperfieldTemperatureSensor(coordinator, device_info, name_prefix),
        AmperfieldEnergySensor(coordinator, device_info, name_prefix, "poweron"),
        AmperfieldEnergySensor(coordinator, device_info, name_prefix, "installation"),
        AmperfieldEnergySensor(coordinator, device_info, name_prefix, "cycle"),
        AmperfieldHardwareMaxCurrentSensor(coordinator, device_info, name_prefix),
    ]

    # Add phase switch state sensor if available (solar/solar pro models)
    phase_switching_available = coordinator.data.get("phase_switch_state") is not None
    if phase_switching_available:
        entities.append(AmperfieldPhaseSwitchStateSensor(coordinator, device_info, name_prefix))
        entities.append(AmperfieldMaxPowerSetSensor(coordinator, device_info, name_prefix))

    async_add_entities(entities)


class AmperfieldSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Amperfield sensors."""

    _attr_has_entity_name = True
    _required_data_keys: list[str] = []  # Override in subclasses

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the sensor."""
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


class AmperfieldChargingStateSensor(AmperfieldSensorBase):
    """Charging state sensor."""

    _attr_translation_key = "charging_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(CHARGING_STATES.values())
    _required_data_keys = ["charging_state"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_charging_state"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        state = self.coordinator.data.get("charging_state")
        if state is None:
            return None
        return CHARGING_STATES.get(state, f"Unknown ({state})")


class AmperfieldCurrentSensor(AmperfieldSensorBase):
    """Current sensor for a specific phase."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
        phase: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self.phase = phase
        self._attr_translation_key = f"current_{phase}"
        self._attr_unique_id = f"{name_prefix.lower()}_current_{phase}"
        self._required_data_keys = [f"current_{phase}"]

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.coordinator.data.get(f"current_{self.phase}")


class AmperfieldVoltageSensor(AmperfieldSensorBase):
    """Voltage sensor for a specific phase."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
        phase: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self.phase = phase
        self._attr_translation_key = f"voltage_{phase}"
        self._attr_unique_id = f"{name_prefix.lower()}_voltage_{phase}"
        self._required_data_keys = [f"voltage_{phase}"]

    @property
    def native_value(self) -> int | None:
        """Return the voltage value."""
        return self.coordinator.data.get(f"voltage_{self.phase}")


class AmperfieldPowerSensor(AmperfieldSensorBase):
    """Power sensor."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
        phase: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self.phase = phase
        if phase == "total":
            self._attr_translation_key = "power"
            self._attr_unique_id = f"{name_prefix.lower()}_power"
            self._required_data_keys = ["power"]
        else:
            self._attr_translation_key = f"power_{phase}"
            self._attr_unique_id = f"{name_prefix.lower()}_power_{phase}"
            self._attr_entity_registry_enabled_default = False
            self._required_data_keys = [f"power_{phase}"]

    @property
    def native_value(self) -> int | None:
        """Return the power value."""
        if self.phase == "total":
            return self.coordinator.data.get("power")
        return self.coordinator.data.get(f"power_{self.phase}")


class AmperfieldTemperatureSensor(AmperfieldSensorBase):
    """Temperature sensor."""

    _attr_translation_key = "temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["temperature"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the temperature value."""
        return self.coordinator.data.get("temperature")


class AmperfieldHardwareMaxCurrentSensor(AmperfieldSensorBase):
    """Hardware maximum current sensor (configured via hardware switch)."""

    _attr_translation_key = "hw_max_current"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["hw_max_current"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_hw_max_current"

    @property
    def native_value(self) -> int | None:
        """Return the hardware max current value."""
        return self.coordinator.data.get("hw_max_current")


class AmperfieldFirmwareVersionSensor(AmperfieldSensorBase):
    """Firmware version sensor."""

    _attr_translation_key = "firmware_version"
    _attr_unique_id = "amperfield_firmware_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the firmware version."""
        return self.coordinator.data.get("firmware_version")


class AmperfieldItemNumberSensor(AmperfieldSensorBase):
    """Item/model number sensor."""

    _attr_translation_key = "item_number"
    _attr_unique_id = "amperfield_item_number"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the friendly model name."""
        item_number = self.coordinator.data.get("item_number")
        if item_number is None:
            return None
        # Return friendly name if mapped, otherwise return the item number
        return MODEL_MAPPING.get(item_number, item_number)


class AmperfieldEnergySensor(AmperfieldSensorBase):
    """Energy sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
        energy_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self.energy_type = energy_type
        self._required_data_keys = [f"energy_{energy_type}"]
        if energy_type == "poweron":
            self._attr_translation_key = "energy_poweron"
            self._attr_unique_id = f"{name_prefix.lower()}_energy_poweron"
            self._attr_entity_registry_enabled_default = False
        elif energy_type == "installation":
            self._attr_translation_key = "energy_installation"
            self._attr_unique_id = f"{name_prefix.lower()}_energy_installation"
            self._attr_entity_registry_enabled_default = False
        else:  # cycle
            self._attr_translation_key = "energy_cycle"
            self._attr_unique_id = f"{name_prefix.lower()}_energy_cycle"
            self._attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self) -> float | None:
        """Return the energy value in kWh."""
        value = self.coordinator.data.get(f"energy_{self.energy_type}")
        if value is None:
            return None
        # Convert from VAh to kWh (VAh to Wh is same for resistive loads, then divide by 1000 for kWh)
        return float(value) / 1000


class AmperfieldPhaseSwitchStateSensor(AmperfieldSensorBase):
    """Phase switch state sensor."""

    _attr_translation_key = "phase_switch_state"
    _required_data_keys = ["phase_switch_state"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_phase_switch_state"

    @property
    def native_value(self) -> str | None:
        """Return the phase switch state."""
        state = self.coordinator.data.get("phase_switch_state")
        if state is None:
            return None
        return PHASE_SWITCH_STATES.get(state, f"Unknown ({state})")


class AmperfieldMaxPowerSetSensor(AmperfieldSensorBase):
    """Maximum power set sensor (read-back of register 500)."""

    _attr_translation_key = "max_power_set"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["max_power_set"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        name_prefix: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, name_prefix)
        self._attr_unique_id = f"{name_prefix.lower()}_max_power_set"

    @property
    def native_value(self) -> int | None:
        """Return the maximum power set value."""
        return self.coordinator.data.get("max_power_set")
