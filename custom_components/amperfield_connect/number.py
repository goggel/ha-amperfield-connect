"""Number platform for Amperfield Wallbox Connect."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AmperfieldDataUpdateCoordinator
from .const import CONTROL_MODE_CURRENT, CONTROL_MODE_POWER
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


def _validate_current(value: float, max_value: float, field_name: str) -> None:
    """Validate wallbox current setting: either off or normal charging range."""
    if value == 0 or 6 <= value <= max_value:
        return

    raise HomeAssistantError(
        f"{field_name} must be 0 A or between 6.0 A and {max_value:.1f} A"
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amperfield number entities from a config entry."""
    runtime_data = config_entry.runtime_data
    client: AmperfieldModbusClient = runtime_data.client
    coordinator: AmperfieldDataUpdateCoordinator = runtime_data.coordinator
    device_info: DeviceInfo = runtime_data.device_info
    serial_number: str = runtime_data.serial_number
    hw_max_current: int = runtime_data.hw_max_current

    entities: list[NumberEntity] = [
        AmperfieldMaxCurrentNumber(
            coordinator, client, device_info, serial_number, hw_max_current
        ),
        AmperfieldFailsafeCurrentNumber(
            coordinator, client, device_info, serial_number, hw_max_current
        ),
    ]

    if runtime_data.supports_phase_switching:
        _LOGGER.debug("Solar/Solar PRO model detected, adding solar number controls")
        entities.append(
            AmperfieldMaxPowerNumber(
                coordinator, client, device_info, serial_number, hw_max_current
            )
        )
        entities.append(
            AmperfieldPhaseSwitchDurationNumber(
                coordinator, client, device_info, serial_number
            )
        )
        entities.append(
            AmperfieldPhaseSwitchWaitingNumber(
                coordinator, client, device_info, serial_number
            )
        )

    _LOGGER.debug("Setting up %d number entities", len(entities))
    async_add_entities(entities)


class AmperfieldNumberBase(CoordinatorEntity, NumberEntity):
    """Base class for Amperfield number entities."""

    _attr_has_entity_name = True
    _required_data_keys: list[str] = []
    coordinator: AmperfieldDataUpdateCoordinator

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.client = client
        self._attr_device_info = device_info
        self._serial_number = serial_number
        self._attr_mode = NumberMode.BOX

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


class AmperfieldMaxCurrentNumber(AmperfieldNumberBase):
    """Number entity for maximum current control."""

    _attr_translation_key = "max_current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_step = 0.1
    _attr_entity_category = EntityCategory.CONFIG
    _required_data_keys = ["max_current"]

    @property
    def available(self) -> bool:
        """Allow current commands only in current control mode."""
        return super().available and self.client.control_mode == CONTROL_MODE_CURRENT

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str | None,
        hw_max_current: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, client, device_info, serial_number)
        self._attr_unique_id = self._unique_id("max_current")
        self._attr_native_max_value = float(hw_max_current)
        self._optimistic_value: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return the current value, using optimistic value if set."""
        if self._optimistic_value is not None:
            return self._optimistic_value
        return self.coordinator.data.get("max_current")

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic value when coordinator provides fresh data."""
        self._optimistic_value = None
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with optimistic update."""
        _validate_current(value, self.native_max_value, "Maximum current")
        _LOGGER.debug("Setting max current to %.1f A", value)
        self._optimistic_value = value
        self.async_write_ha_state()
        success = await self.client.set_max_current(value)
        if not success:
            _LOGGER.error("Failed to set max current to %.1f A", value)
            self._optimistic_value = None
            self.async_write_ha_state()
            raise HomeAssistantError(f"Failed to set maximum current to {value:.1f} A")
        await self.coordinator.async_request_refresh()


class AmperfieldFailsafeCurrentNumber(AmperfieldNumberBase):
    """Number entity for failsafe current setting."""

    _attr_translation_key = "failsafe_current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_step = 0.1
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["failsafe_current"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str | None,
        hw_max_current: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, client, device_info, serial_number)
        self._attr_unique_id = self._unique_id("failsafe_current")
        self._attr_native_max_value = float(hw_max_current)
        self._optimistic_value: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return the current value, using optimistic value if set."""
        if self._optimistic_value is not None:
            return self._optimistic_value
        return self.coordinator.data.get("failsafe_current")

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic value when coordinator provides fresh data."""
        self._optimistic_value = None
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with optimistic update."""
        _validate_current(value, self.native_max_value, "Failsafe current")
        _LOGGER.debug("Setting failsafe current to %.1f A", value)
        self._optimistic_value = value
        self.async_write_ha_state()
        success = await self.client.set_failsafe_current(value)
        if not success:
            _LOGGER.error("Failed to set failsafe current to %.1f A", value)
            self._optimistic_value = None
            self.async_write_ha_state()
            raise HomeAssistantError(f"Failed to set failsafe current to {value:.1f} A")
        await self.coordinator.async_request_refresh()


class AmperfieldMaxPowerNumber(AmperfieldNumberBase):
    """Number entity for maximum power target control (solar/solar pro only)."""

    _attr_translation_key = "max_power_target"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_min_value = 0
    _attr_native_step = 100
    _attr_entity_category = EntityCategory.CONFIG
    _required_data_keys = ["max_power_target"]

    @property
    def available(self) -> bool:
        """Allow automatic power commands only in power control mode."""
        return super().available and self.client.control_mode == CONTROL_MODE_POWER

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str | None,
        hw_max_current: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, client, device_info, serial_number)
        self._attr_unique_id = self._unique_id("max_power_target")
        self._attr_native_max_value = float(hw_max_current * 230 * 3)
        self._optimistic_value: int | None = None

    @property
    def native_value(self) -> int | None:
        """Return the current value, using optimistic value if set."""
        if self._optimistic_value is not None:
            return self._optimistic_value
        return self.coordinator.data.get("max_power_target")

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic value when coordinator provides fresh data."""
        self._optimistic_value = None
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with optimistic update."""
        watts = int(value)
        if 0 < watts < 1400:
            watts = 1400
            _LOGGER.debug("Rounding up max power target to minimum 1400 W")
        _LOGGER.debug("Setting max power target to %d W", watts)
        self._optimistic_value = watts
        self.async_write_ha_state()
        success = await self.client.set_max_power_target(watts)
        if not success:
            _LOGGER.error("Failed to set max power target to %d W", watts)
            self._optimistic_value = None
            self.async_write_ha_state()
            raise HomeAssistantError(f"Failed to set maximum power target to {watts} W")
        await self.coordinator.async_request_refresh()


class AmperfieldPhaseSwitchDurationNumber(AmperfieldNumberBase):
    """Number entity for phase switch duration time (solar/solar pro only)."""

    _attr_translation_key = "phase_switch_duration"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_native_min_value = 15
    _attr_native_max_value = 900
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["phase_switch_duration"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, client, device_info, serial_number)
        self._attr_unique_id = self._unique_id("phase_switch_duration")
        self._optimistic_value: int | None = None

    @property
    def native_value(self) -> int | None:
        """Return the current value, using optimistic value if set."""
        if self._optimistic_value is not None:
            return self._optimistic_value
        return self.coordinator.data.get("phase_switch_duration")

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic value when coordinator provides fresh data."""
        self._optimistic_value = None
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with optimistic update."""
        seconds = int(value)
        _LOGGER.debug("Setting phase switch duration to %d s", seconds)
        self._optimistic_value = seconds
        self.async_write_ha_state()
        success = await self.client.set_phase_switch_duration(seconds)
        if not success:
            _LOGGER.error("Failed to set phase switch duration to %d s", seconds)
            self._optimistic_value = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to set phase switch duration to {seconds} s"
            )
        await self.coordinator.async_request_refresh()


class AmperfieldPhaseSwitchWaitingNumber(AmperfieldNumberBase):
    """Number entity for phase switch waiting time (solar/solar pro only)."""

    _attr_translation_key = "phase_switch_waiting"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_native_min_value = 0
    _attr_native_max_value = 3600
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _required_data_keys = ["phase_switch_waiting"]

    def __init__(
        self,
        coordinator: AmperfieldDataUpdateCoordinator,
        client: AmperfieldModbusClient,
        device_info: DeviceInfo,
        serial_number: str | None,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, client, device_info, serial_number)
        self._attr_unique_id = self._unique_id("phase_switch_waiting")
        self._optimistic_value: int | None = None

    @property
    def native_value(self) -> int | None:
        """Return the current value, using optimistic value if set."""
        if self._optimistic_value is not None:
            return self._optimistic_value
        return self.coordinator.data.get("phase_switch_waiting")

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic value when coordinator provides fresh data."""
        self._optimistic_value = None
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with optimistic update."""
        seconds = int(value)
        _LOGGER.debug("Setting phase switch waiting time to %d s", seconds)
        self._optimistic_value = seconds
        self.async_write_ha_state()
        success = await self.client.set_phase_switch_waiting(seconds)
        if not success:
            _LOGGER.error("Failed to set phase switch waiting time to %d s", seconds)
            self._optimistic_value = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Failed to set phase switch waiting time to {seconds} s"
            )
        await self.coordinator.async_request_refresh()
