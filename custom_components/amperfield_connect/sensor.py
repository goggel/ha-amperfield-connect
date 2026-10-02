"""Sensor platform for Amperfield Wallbox Connect."""

from __future__ import annotations

import logging

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
    PHASE_SWITCH_STATES,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield sensors from a config entry."""
    runtime_data = config_entry.runtime_data
    coordinator: AmperfieldDataUpdateCoordinator = runtime_data.coordinator
    device_info: DeviceInfo = runtime_data.device_info
    serial_number: str = runtime_data.serial_number

    entities: list[SensorEntity] = [
        AmperfieldChargingStateSensor(coordinator, device_info, serial_number),
        AmperfieldCurrentSensor(coordinator, device_info, serial_number, "l1"),
        AmperfieldCurrentSensor(coordinator, device_info, serial_number, "l2"),
        AmperfieldCurrentSensor(coordinator, device_info, serial_number, "l3"),
        AmperfieldVoltageSensor(coordinator, device_info, serial_number, "l1"),
        AmperfieldVoltageSensor(coordinator, device_info, serial_number, "l2"),
        AmperfieldVoltageSensor(coordinator, device_info, serial_number, "l3"),
        AmperfieldPowerSensor(coordinator, device_info, serial_number, "total"),
        AmperfieldPowerSensor(coordinator, device_info, serial_number, "l1"),
        AmperfieldPowerSensor(coordinator, device_info, serial_number, "l2"),
        AmperfieldPowerSensor(coordinator, device_info, serial_number, "l3"),
        AmperfieldTemperatureSensor(coordinator, device_info, serial_number),
        AmperfieldEnergySensor(coordinator, device_info, serial_number, "poweron"),
        AmperfieldEnergySensor(coordinator, device_info, serial_number, "installation"),
        AmperfieldEnergySensor(coordinator, device_info, serial_number, "cycle"),
        AmperfieldHardwareMaxCurrentSensor(coordinator, device_info, serial_number),
    ]

    # Add phase switch state sensor if available (solar/solar pro models)
    if runtime_data.supports_phase_switching:
        entities.append(
            AmperfieldPhaseSwitchStateSensor(coordinator, device_info, serial_number)
        )
        entities.append(
            AmperfieldMaxPowerSetSensor(coordinator, device_info, serial_number)
        )

    async_add_entities(entities)


class AmperfieldSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Amperfield sensors."""

    _attr_has_entity_name = True
    _required_data_keys: list[str] = []
    coordinator: AmperfieldDataUpdateCoordinator

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the sensor."""
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
        serial_number: str | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self._attr_unique_id = self._unique_id("charging_state")

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        state = self.coordinator.data.get("charging_state")
        if state is None:
            return None
        return CHARGING_STATES.get(state)


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
        serial_number: str | None,
        phase: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self.phase = phase
        self._attr_translation_key = f"current_{phase}"
        self._attr_unique_id = self._unique_id(f"current_{phase}")
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
        serial_number: str | None,
        phase: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self.phase = phase
        self._attr_translation_key = f"voltage_{phase}"
        self._attr_unique_id = self._unique_id(f"voltage_{phase}")
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
        serial_number: str | None,
        phase: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self.phase = phase
        if phase == "total":
            self._attr_translation_key = "power"
            self._attr_unique_id = self._unique_id("power")
            self._required_data_keys = ["power"]
        else:
            self._attr_translation_key = f"power_{phase}"
            self._attr_unique_id = self._unique_id(f"power_{phase}")
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
        serial_number: str | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self._attr_unique_id = self._unique_id("temperature")

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
        serial_number: str | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self._attr_unique_id = self._unique_id("hw_max_current")

    @property
    def native_value(self) -> int | None:
        """Return the hardware max current value."""
        return self.coordinator.data.get("hw_max_current")


class AmperfieldEnergySensor(AmperfieldSensorBase):
    """Energy sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        serial_number: str | None,
        energy_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self.energy_type = energy_type
        self._required_data_keys = [f"energy_{energy_type}"]
        if energy_type == "poweron":
            self._attr_translation_key = "energy_poweron"
            self._attr_unique_id = self._unique_id("energy_poweron")
            self._attr_entity_registry_enabled_default = False
        elif energy_type == "installation":
            self._attr_translation_key = "energy_installation"
            self._attr_unique_id = self._unique_id("energy_installation")
            self._attr_entity_registry_enabled_default = False
        else:  # cycle
            self._attr_translation_key = "energy_cycle"
            self._attr_unique_id = self._unique_id("energy_cycle")
            self._attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self) -> float | None:
        """Return the energy value in kWh."""
        value = self.coordinator.data.get(f"energy_{self.energy_type}")
        if value is None:
            return None
        return float(value) / 1000


class AmperfieldPhaseSwitchStateSensor(AmperfieldSensorBase):
    """Phase switch state sensor."""

    _attr_translation_key = "phase_switch_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(PHASE_SWITCH_STATES.values())
    _required_data_keys = ["phase_switch_state"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self._attr_unique_id = self._unique_id("phase_switch_state")

    @property
    def native_value(self) -> str | None:
        """Return the phase switch state."""
        state = self.coordinator.data.get("phase_switch_state")
        if state is None:
            return None
        return PHASE_SWITCH_STATES.get(state)


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
        serial_number: str | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info, serial_number)
        self._attr_unique_id = self._unique_id("max_power_set")

    @property
    def native_value(self) -> int | None:
        """Return the maximum power set value."""
        return self.coordinator.data.get("max_power_set")
