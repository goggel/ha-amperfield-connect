"""Modbus client for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging
from typing import Any

from pymodbus.client import ModbusTcpClient

from .const import (
    REG_CHARGING_STATE,
    REG_CHARGING_STRATEGY,
    REG_CHARGING_STRATEGY_STATUS,
    REG_CURRENT_L1,
    REG_CURRENT_L2,
    REG_CURRENT_L3,
    REG_DISCONNECT_SIMULATION,
    REG_DISCONNECT_SIMULATION_STATUS,
    REG_ENERGY_CYCLE_HIGH,
    REG_ENERGY_INSTALL_HIGH,
    REG_ENERGY_POWERON_HIGH,
    REG_EXTERN_LOCK,
    REG_FAILSAFE_CURRENT,
    REG_FIRMWARE_VARIANT_START,
    REG_FIRMWARE_VERSION_START,
    REG_HW_MAX_CURRENT,
    REG_HW_MIN_CURRENT,
    REG_ITEM_NUMBER_START,
    REG_MAX_CURRENT,
    REG_MAX_POWER_SET,
    REG_MAX_POWER_TARGET,
    REG_MODBUS_VERSION,
    REG_PHASE_SWITCH_CONTROL,
    REG_PHASE_SWITCH_DURATION,
    REG_PHASE_SWITCH_STATE,
    REG_PHASE_SWITCH_WAITING,
    REG_POWER,
    REG_POWER_L1,
    REG_POWER_L2,
    REG_POWER_L3,
    REG_PRODUCTION_DATE_START,
    REG_REMOTE_LOCK,
    REG_SERIAL_START,
    REG_TEMPERATURE,
    REG_VOLTAGE_L1,
    REG_VOLTAGE_L2,
    REG_VOLTAGE_L3,
    REG_WATCHDOG_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class AmperfieldModbusClient:
    """Modbus client for Amperfield Wallbox."""

    def __init__(self, host: str, port: int) -> None:
        """Initialize the Modbus client."""
        self.host = host
        self.port = port
        self.client = ModbusTcpClient(host=host, port=port, timeout=5)

    def connect(self) -> bool:
        """Connect to the Modbus device."""
        return self.client.connect()

    def close(self) -> None:
        """Close the Modbus connection."""
        self.client.close()

    def read_input_register(self, address: int) -> int | None:
        """Read a single input register."""
        try:
            result = self.client.read_input_registers(address=address, count=1)
            if result.isError():
                _LOGGER.error("Error reading input register %s: %s", address, result)
                return None
            return result.registers[0]
        except Exception as err:
            _LOGGER.error("Exception reading input register %s: %s", address, err)
            return None

    def read_holding_register(self, address: int) -> int | None:
        """Read a single holding register."""
        try:
            result = self.client.read_holding_registers(address=address, count=1)
            if result.isError():
                _LOGGER.error("Error reading holding register %s: %s", address, result)
                return None
            return result.registers[0]
        except Exception as err:
            _LOGGER.error("Exception reading holding register %s: %s", address, err)
            return None

    def write_holding_register(self, address: int, value: int) -> bool:
        """Write a single holding register."""
        try:
            result = self.client.write_register(address=address, value=value)
            if result.isError():
                _LOGGER.error("Error writing holding register %s: %s", address, result)
                return False
            return True
        except Exception as err:
            _LOGGER.error("Exception writing holding register %s: %s", address, err)
            return False

    def read_string_registers(self, start_address: int, count: int) -> str | None:
        """Read multiple registers and convert to ASCII string."""
        try:
            result = self.client.read_input_registers(address=start_address, count=count)
            if result.isError():
                _LOGGER.error("Error reading string registers from %s: %s", start_address, result)
                return None

            # Each register contains 2 ASCII characters
            text = ""
            for register in result.registers:
                high_byte = (register >> 8) & 0xFF
                low_byte = register & 0xFF
                if high_byte == 0:
                    break
                text += chr(high_byte)
                if low_byte == 0:
                    break
                text += chr(low_byte)
            return text
        except Exception as err:
            _LOGGER.error("Exception reading string registers from %s: %s", start_address, err)
            return None

    def read_32bit_value(self, high_address: int) -> int | None:
        """Read a 32-bit value from two consecutive registers."""
        try:
            result = self.client.read_input_registers(address=high_address, count=2)
            if result.isError():
                _LOGGER.error("Error reading 32-bit value from %s: %s", high_address, result)
                return None

            high_byte = result.registers[0]
            low_byte = result.registers[1]
            return (high_byte << 16) + low_byte
        except Exception as err:
            _LOGGER.error("Exception reading 32-bit value from %s: %s", high_address, err)
            return None

    # Convenience methods for specific readings
    def get_modbus_version(self) -> int | None:
        """Get Modbus protocol version."""
        return self.read_input_register(REG_MODBUS_VERSION)

    def get_charging_state(self) -> int | None:
        """Get current charging state."""
        return self.read_input_register(REG_CHARGING_STATE)

    def get_current_l1(self) -> float | None:
        """Get current on L1 in Amperes."""
        value = self.read_input_register(REG_CURRENT_L1)
        return value / 10.0 if value is not None else None

    def get_current_l2(self) -> float | None:
        """Get current on L2 in Amperes."""
        value = self.read_input_register(REG_CURRENT_L2)
        return value / 10.0 if value is not None else None

    def get_current_l3(self) -> float | None:
        """Get current on L3 in Amperes."""
        value = self.read_input_register(REG_CURRENT_L3)
        return value / 10.0 if value is not None else None

    def get_temperature(self) -> float | None:
        """Get internal temperature in Celsius."""
        value = self.read_input_register(REG_TEMPERATURE)
        if value is not None:
            # Handle signed integer
            if value > 32767:
                value = value - 65536
            return value / 10.0
        return None

    def get_voltage_l1(self) -> int | None:
        """Get voltage on L1 in Volts."""
        return self.read_input_register(REG_VOLTAGE_L1)

    def get_voltage_l2(self) -> int | None:
        """Get voltage on L2 in Volts."""
        return self.read_input_register(REG_VOLTAGE_L2)

    def get_voltage_l3(self) -> int | None:
        """Get voltage on L3 in Volts."""
        return self.read_input_register(REG_VOLTAGE_L3)

    def get_extern_lock_state(self) -> int | None:
        """Get external lock state (0=locked, 1=unlocked)."""
        return self.read_input_register(REG_EXTERN_LOCK)

    def get_power(self) -> int | None:
        """Get total power in Watts."""
        return self.read_input_register(REG_POWER)

    def get_power_l1(self) -> int | None:
        """Get power on L1 in Watts."""
        return self.read_input_register(REG_POWER_L1)

    def get_power_l2(self) -> int | None:
        """Get power on L2 in Watts."""
        return self.read_input_register(REG_POWER_L2)

    def get_power_l3(self) -> int | None:
        """Get power on L3 in Watts."""
        return self.read_input_register(REG_POWER_L3)

    def get_energy_since_poweron(self) -> int | None:
        """Get energy since power on in VAh."""
        return self.read_32bit_value(REG_ENERGY_POWERON_HIGH)

    def get_energy_since_installation(self) -> int | None:
        """Get energy since installation in VAh."""
        return self.read_32bit_value(REG_ENERGY_INSTALL_HIGH)

    def get_energy_charge_cycle(self) -> int | None:
        """Get energy during current charge cycle in VAh."""
        return self.read_32bit_value(REG_ENERGY_CYCLE_HIGH)

    def get_hardware_max_current(self) -> int | None:
        """Get hardware configured maximum current."""
        return self.read_input_register(REG_HW_MAX_CURRENT)

    def get_hardware_min_current(self) -> int | None:
        """Get hardware minimum current."""
        return self.read_input_register(REG_HW_MIN_CURRENT)

    def get_serial_number(self) -> str | None:
        """Get wallbox serial number."""
        return self.read_string_registers(REG_SERIAL_START, 18)

    def get_item_number(self) -> str | None:
        """Get wallbox item number."""
        return self.read_string_registers(REG_ITEM_NUMBER_START, 18)

    def get_production_date(self) -> str | None:
        """Get production date."""
        return self.read_string_registers(REG_PRODUCTION_DATE_START, 18)

    def get_firmware_version(self) -> str | None:
        """Get firmware version."""
        return self.read_string_registers(REG_FIRMWARE_VERSION_START, 41)

    def get_firmware_variant(self) -> str | None:
        """Get firmware variant."""
        return self.read_string_registers(REG_FIRMWARE_VARIANT_START, 41)

    # Control methods (holding registers)
    def get_watchdog_timeout(self) -> int | None:
        """Get watchdog timeout in milliseconds."""
        return self.read_holding_register(REG_WATCHDOG_TIMEOUT)

    def set_watchdog_timeout(self, value: int) -> bool:
        """Set watchdog timeout in milliseconds."""
        return self.write_holding_register(REG_WATCHDOG_TIMEOUT, value)

    def get_remote_lock(self) -> int | None:
        """Get remote lock state (0=locked, 1=unlocked)."""
        return self.read_holding_register(REG_REMOTE_LOCK)

    def set_remote_lock(self, locked: bool) -> bool:
        """Set remote lock state."""
        return self.write_holding_register(REG_REMOTE_LOCK, 0 if locked else 1)

    def get_max_current(self) -> float | None:
        """Get maximum current command in Amperes."""
        value = self.read_holding_register(REG_MAX_CURRENT)
        return value / 10.0 if value is not None else None

    def set_max_current(self, amperes: float) -> bool:
        """Set maximum current command in Amperes (0.1A steps)."""
        value = int(amperes * 10)
        return self.write_holding_register(REG_MAX_CURRENT, value)

    def get_failsafe_current(self) -> float | None:
        """Get failsafe current in Amperes."""
        value = self.read_holding_register(REG_FAILSAFE_CURRENT)
        return value / 10.0 if value is not None else None

    def set_failsafe_current(self, amperes: float) -> bool:
        """Set failsafe current in Amperes (0.1A steps)."""
        value = int(amperes * 10)
        return self.write_holding_register(REG_FAILSAFE_CURRENT, value)

    # Phase switch methods (solar/solar pro only)
    def get_max_power_target(self) -> int | None:
        """Get maximum power target in Watts."""
        return self.read_holding_register(REG_MAX_POWER_TARGET)

    def set_max_power_target(self, watts: int) -> bool:
        """Set maximum power target in Watts."""
        return self.write_holding_register(REG_MAX_POWER_TARGET, watts)

    def get_phase_switch_control(self) -> int | None:
        """Get phase switch control (1 or 3)."""
        return self.read_holding_register(REG_PHASE_SWITCH_CONTROL)

    def set_phase_switch_control(self, phases: int) -> bool:
        """Set phase switch control (1 or 3)."""
        if phases not in (1, 3):
            _LOGGER.error("Invalid phase value: %s. Must be 1 or 3", phases)
            return False
        return self.write_holding_register(REG_PHASE_SWITCH_CONTROL, phases)

    def get_charging_strategy(self) -> int | None:
        """Get charging management strategy."""
        return self.read_holding_register(REG_CHARGING_STRATEGY)

    def set_charging_strategy(self, strategy: int) -> bool:
        """Set charging management strategy (0=manual, 1=solar)."""
        return self.write_holding_register(REG_CHARGING_STRATEGY, strategy)

    def get_phase_switch_duration(self) -> int | None:
        """Get phase switch duration in seconds."""
        return self.read_holding_register(REG_PHASE_SWITCH_DURATION)

    def set_phase_switch_duration(self, seconds: int) -> bool:
        """Set phase switch duration in seconds (15-900)."""
        return self.write_holding_register(REG_PHASE_SWITCH_DURATION, seconds)

    def get_phase_switch_waiting(self) -> int | None:
        """Get phase switch waiting time in seconds."""
        return self.read_holding_register(REG_PHASE_SWITCH_WAITING)

    def set_phase_switch_waiting(self, seconds: int) -> bool:
        """Set phase switch waiting time in seconds (0-3600)."""
        return self.write_holding_register(REG_PHASE_SWITCH_WAITING, seconds)

    def get_disconnect_simulation(self) -> int | None:
        """Get disconnect simulation state."""
        return self.read_holding_register(REG_DISCONNECT_SIMULATION)

    def set_disconnect_simulation(self, enabled: bool) -> bool:
        """Set disconnect simulation state."""
        return self.write_holding_register(REG_DISCONNECT_SIMULATION, 1 if enabled else 0)

    def get_max_power_set(self) -> int | None:
        """Get maximum power set in Watts."""
        return self.read_input_register(REG_MAX_POWER_SET)

    def get_phase_switch_state(self) -> int | None:
        """Get phase switch state (0=switching, 1=1phase, 3=3phases)."""
        return self.read_input_register(REG_PHASE_SWITCH_STATE)

    def get_charging_strategy_status(self) -> int | None:
        """Get charging strategy status."""
        return self.read_input_register(REG_CHARGING_STRATEGY_STATUS)

    def get_disconnect_simulation_status(self) -> int | None:
        """Get disconnect simulation status."""
        return self.read_input_register(REG_DISCONNECT_SIMULATION_STATUS)
