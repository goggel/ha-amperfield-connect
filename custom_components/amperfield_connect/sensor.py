"""Sensor platform for Amperfield Wallbox Connect."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CHARGING_STATES,
    CONF_NAME_PREFIX,
    DEFAULT_NAME_PREFIX,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODEL_MAPPING,
    PHASE_SWITCH_STATES,
)
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield sensors from a config entry."""
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


class AmperfieldDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Amperfield data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AmperfieldModbusClient,
        scan_interval: int,
    ) -> None:
        """Initialize."""
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Modbus."""
        try:
            data = await self.hass.async_add_executor_job(self._fetch_data)
            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err

    def _fetch_data(self) -> dict[str, Any]:
        """Fetch all data from the wallbox."""
        data = {
            "charging_state": self.client.get_charging_state(),
            "current_l1": self.client.get_current_l1(),
            "current_l2": self.client.get_current_l2(),
            "current_l3": self.client.get_current_l3(),
            "voltage_l1": self.client.get_voltage_l1(),
            "voltage_l2": self.client.get_voltage_l2(),
            "voltage_l3": self.client.get_voltage_l3(),
            "power": self.client.get_power(),
            "power_l1": self.client.get_power_l1(),
            "power_l2": self.client.get_power_l2(),
            "power_l3": self.client.get_power_l3(),
            "temperature": self.client.get_temperature(),
            "energy_poweron": self.client.get_energy_since_poweron(),
            "energy_installation": self.client.get_energy_since_installation(),
            "energy_cycle": self.client.get_energy_charge_cycle(),
            "extern_lock": self.client.get_extern_lock_state(),
            "remote_lock": self.client.get_remote_lock(),
            "max_current": self.client.get_max_current(),
            "hw_max_current": self.client.get_hardware_max_current(),
            "firmware_version": self.client.get_firmware_version(),
            "item_number": self.client.get_item_number(),
        }

        # Try to read phase switch state (only available on solar/solar pro)
        phase_switch_state = self.client.get_phase_switch_state()
        if phase_switch_state is not None:
            data["phase_switch_state"] = phase_switch_state
            data["phase_switch_control"] = self.client.get_phase_switch_control()
            data["charging_strategy"] = self.client.get_charging_strategy()
            data["max_power_set"] = self.client.get_max_power_set()

        return data


class AmperfieldSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Amperfield sensors."""

    _attr_has_entity_name = True

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


class AmperfieldChargingStateSensor(AmperfieldSensorBase):
    """Charging state sensor."""

    _attr_translation_key = "charging_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(CHARGING_STATES.values())

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
        else:
            self._attr_translation_key = f"power_{phase}"
            self._attr_unique_id = f"{name_prefix.lower()}_power_{phase}"
            self._attr_entity_registry_enabled_default = False

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
