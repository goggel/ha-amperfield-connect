"""Modbus client for Amperfield Wallbox Connect."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Generator

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
    """Modbus client for Amperfield Wallbox.

    The wallbox only accepts ONE Modbus TCP connection at a time.
    This client uses a lock to ensure thread-safety and keeps a persistent
    connection open, reconnecting automatically if the connection is lost.
    """

    def __init__(self, host: str, port: int) -> None:
        """Initialize the Modbus client."""
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._client = ModbusTcpClient(host=host, port=port, timeout=5)
        _LOGGER.debug("Initialized Modbus client for %s:%s", host, port)

    def _ensure_connected(self) -> None:
        """Ensure the client is connected, reconnecting if needed.

        Must be called while holding self._lock.
        """
        if not self._client.connected:
            _LOGGER.debug("Opening Modbus connection to %s:%s", self.host, self.port)
            if not self._client.connect():
                _LOGGER.warning("Failed to connect to %s:%s", self.host, self.port)
                raise ConnectionError(f"Failed to connect to {self.host}:{self.port}")
            _LOGGER.debug("Connected to %s:%s", self.host, self.port)

    def _reconnect(self) -> None:
        """Force a reconnect by closing and reopening the connection.

        Must be called while holding self._lock.
        """
        self._client.close()
        _LOGGER.debug("Reconnecting to %s:%s", self.host, self.port)
        if not self._client.connect():
            _LOGGER.warning("Failed to reconnect to %s:%s", self.host, self.port)
            raise ConnectionError(f"Failed to reconnect to {self.host}:{self.port}")
        _LOGGER.debug("Reconnected to %s:%s", self.host, self.port)

    @contextmanager
    def _connection(self) -> Generator[ModbusTcpClient, None, None]:
        """Context manager for thread-safe Modbus connection.

        Acquires lock and yields a persistent client, reconnecting if needed.
        On error, closes the connection so the next call will reconnect.
        """
        with self._lock:
            self._ensure_connected()
            try:
                yield self._client
            except Exception:
                self._client.close()
                _LOGGER.debug("Closed connection to %s:%s after error", self.host, self.port)
                raise

    def connect(self) -> bool:
        """Test connection to the Modbus device."""
        _LOGGER.debug("Testing connection to %s:%s", self.host, self.port)
        try:
            with self._connection() as client:
                connected = client.connected
                if connected:
                    _LOGGER.info("Successfully connected to wallbox at %s:%s", self.host, self.port)
                return connected
        except Exception as err:
            _LOGGER.debug("Connection test failed: %s", err)
            return False

    def close(self) -> None:
        """Close the persistent connection."""
        with self._lock:
            self._client.close()
            _LOGGER.debug("Closed persistent connection to %s:%s", self.host, self.port)

    def read_input_register(self, address: int) -> int | None:
        """Read a single input register."""
        _LOGGER.debug("Reading input register %s", address)
        try:
            with self._connection() as client:
                result = client.read_input_registers(address=address, count=1)
                if result.isError():
                    _LOGGER.error("Error reading input register %s: %s", address, result)
                    return None
                value = result.registers[0]
                _LOGGER.debug("Read input register %s = %s", address, value)
                return value
        except Exception as err:
            _LOGGER.error("Exception reading input register %s: %s", address, err)
            return None

    def read_holding_register(self, address: int) -> int | None:
        """Read a single holding register."""
        _LOGGER.debug("Reading holding register %s", address)
        try:
            with self._connection() as client:
                result = client.read_holding_registers(address=address, count=1)
                if result.isError():
                    _LOGGER.error("Error reading holding register %s: %s", address, result)
                    return None
                value = result.registers[0]
                _LOGGER.debug("Read holding register %s = %s", address, value)
                return value
        except Exception as err:
            _LOGGER.error("Exception reading holding register %s: %s", address, err)
            return None

    def write_holding_register(self, address: int, value: int) -> bool:
        """Write a single holding register. Retries once on connection error."""
        _LOGGER.debug("Writing holding register %s = %s", address, value)
        with self._lock:
            for attempt in range(2):
                try:
                    self._ensure_connected()
                    result = self._client.write_register(address=address, value=value)
                    if result.isError():
                        _LOGGER.error("Error writing holding register %s = %s: %s", address, value, result)
                        return False
                    _LOGGER.debug("Successfully wrote holding register %s = %s", address, value)
                    return True
                except Exception as err:
                    if attempt == 0:
                        _LOGGER.debug("Write failed, reconnecting and retrying: %s", err)
                        self._client.close()
                    else:
                        _LOGGER.error("Exception writing holding register %s = %s: %s", address, value, err)
                        return False
        return False

    def read_string_registers(self, start_address: int, count: int) -> str | None:
        """Read multiple registers and convert to ASCII string."""
        _LOGGER.debug("Reading string registers %s-%s (count=%s)", start_address, start_address + count - 1, count)
        try:
            with self._connection() as client:
                result = client.read_input_registers(address=start_address, count=count)
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
                _LOGGER.debug("Read string from register %s = '%s'", start_address, text)
                return text
        except Exception as err:
            _LOGGER.error("Exception reading string registers from %s: %s", start_address, err)
            return None

    def read_32bit_value(self, high_address: int) -> int | None:
        """Read a 32-bit value from two consecutive registers."""
        _LOGGER.debug("Reading 32-bit value from registers %s-%s", high_address, high_address + 1)
        try:
            with self._connection() as client:
                result = client.read_input_registers(address=high_address, count=2)
                if result.isError():
                    _LOGGER.error("Error reading 32-bit value from %s: %s", high_address, result)
                    return None

                high_byte = result.registers[0]
                low_byte = result.registers[1]
                value = (high_byte << 16) + low_byte
                _LOGGER.debug("Read 32-bit value from register %s = %s", high_address, value)
                return value
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
        _LOGGER.info("Setting remote lock to %s", "locked" if locked else "unlocked")
        return self.write_holding_register(REG_REMOTE_LOCK, 0 if locked else 1)

    def get_max_current(self) -> float | None:
        """Get maximum current command in Amperes."""
        value = self.read_holding_register(REG_MAX_CURRENT)
        return value / 10.0 if value is not None else None

    def set_max_current(self, amperes: float) -> bool:
        """Set maximum current command in Amperes (0.1A steps)."""
        _LOGGER.info("Setting max current to %.1f A", amperes)
        value = int(amperes * 10)
        return self.write_holding_register(REG_MAX_CURRENT, value)

    def get_failsafe_current(self) -> float | None:
        """Get failsafe current in Amperes."""
        value = self.read_holding_register(REG_FAILSAFE_CURRENT)
        return value / 10.0 if value is not None else None

    def set_failsafe_current(self, amperes: float) -> bool:
        """Set failsafe current in Amperes (0.1A steps)."""
        _LOGGER.info("Setting failsafe current to %.1f A", amperes)
        value = int(amperes * 10)
        return self.write_holding_register(REG_FAILSAFE_CURRENT, value)

    # Phase switch methods (solar/solar pro only)
    def get_max_power_target(self) -> int | None:
        """Get maximum power target in Watts."""
        return self.read_holding_register(REG_MAX_POWER_TARGET)

    def set_max_power_target(self, watts: int) -> bool:
        """Set maximum power target in Watts."""
        _LOGGER.info("Setting max power target to %d W", watts)
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
        strategy_name = "manual" if strategy == 0 else "solar" if strategy == 1 else f"unknown({strategy})"
        _LOGGER.info("Setting charging strategy to %s (%d)", strategy_name, strategy)
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

    @staticmethod
    def _decode_string(registers: list[int]) -> str:
        """Decode a string from a list of Modbus registers (2 ASCII chars per register)."""
        text = ""
        for register in registers:
            high_byte = (register >> 8) & 0xFF
            low_byte = register & 0xFF
            if high_byte == 0:
                break
            text += chr(high_byte)
            if low_byte == 0:
                break
            text += chr(low_byte)
        return text

    def _do_fetch_all_data(self, client: ModbusTcpClient) -> dict[str, Any]:
        """Perform the actual batch fetch using the given connected client.

        Must be called while holding self._lock.
        """
        data: dict[str, Any] = {}

        # --- Bulk read: input registers 5-23 (19 registers) ---
        result = client.read_input_registers(address=5, count=19)
        if result.isError():
            _LOGGER.error("Error reading input registers 5-23: %s", result)
            raise ConnectionError(f"Failed to read input registers 5-23: {result}")

        r = result.registers  # index 0 = register 5
        data["charging_state"] = r[0]
        data["current_l1"] = r[1] / 10.0
        data["current_l2"] = r[2] / 10.0
        data["current_l3"] = r[3] / 10.0
        temp = r[4]
        if temp > 32767:
            temp = temp - 65536
        data["temperature"] = temp / 10.0
        data["voltage_l1"] = r[5]
        data["voltage_l2"] = r[6]
        data["voltage_l3"] = r[7]
        data["extern_lock"] = r[8]
        data["power"] = r[9]
        data["energy_poweron"] = (r[10] << 16) + r[11]
        data["energy_installation"] = (r[12] << 16) + r[13]
        data["energy_cycle"] = (r[14] << 16) + r[15]
        data["power_l1"] = r[16]
        data["power_l2"] = r[17]
        data["power_l3"] = r[18]

        # --- Bulk read: input registers 100-101 (hw max/min current) ---
        result = client.read_input_registers(address=100, count=2)
        if not result.isError():
            data["hw_max_current"] = result.registers[0]
        else:
            data["hw_max_current"] = None

        # --- Bulk read: item number (input registers 1050-1067, 18 regs) ---
        result = client.read_input_registers(address=1050, count=18)
        data["item_number"] = self._decode_string(result.registers) if not result.isError() else None

        # --- Bulk read: firmware version (input registers 1250-1290, 41 regs) ---
        result = client.read_input_registers(address=1250, count=41)
        data["firmware_version"] = self._decode_string(result.registers) if not result.isError() else None

        # --- Bulk read: holding registers 259-262 (remote_lock, _, max_current, failsafe) ---
        result = client.read_holding_registers(address=259, count=4)
        if not result.isError():
            data["remote_lock"] = result.registers[0]
            # register 260 is unused
            data["max_current"] = result.registers[2] / 10.0
            data["failsafe_current"] = result.registers[3] / 10.0
        else:
            data["remote_lock"] = None
            data["max_current"] = None
            data["failsafe_current"] = None

        # --- Solar/Solar PRO: input registers 5000-5003 ---
        result = client.read_input_registers(address=5000, count=4)
        if not result.isError():
            data["max_power_set"] = result.registers[0]
            data["phase_switch_state"] = result.registers[1]
            data["charging_strategy_status"] = result.registers[2]
            data["disconnect_simulation_status"] = result.registers[3]

            # --- Solar holding registers 500-505 ---
            result = client.read_holding_registers(address=500, count=6)
            if not result.isError():
                data["max_power_target"] = result.registers[0]
                data["phase_switch_control"] = result.registers[1]
                data["charging_strategy"] = result.registers[2]

        return data

    def fetch_all_data(self) -> dict[str, Any]:
        """Fetch all data in a single connection using bulk register reads.

        Retries once on connection error (e.g. wallbox dropped idle connection).
        """
        _LOGGER.debug("Starting batch fetch of all sensor data")
        with self._lock:
            for attempt in range(2):
                try:
                    self._ensure_connected()
                    data = self._do_fetch_all_data(self._client)
                    _LOGGER.debug(
                        "Batch fetch complete: charging_state=%s, power=%sW, current=%.1f/%.1f/%.1f A",
                        data.get("charging_state"),
                        data.get("power"),
                        data.get("current_l1") or 0,
                        data.get("current_l2") or 0,
                        data.get("current_l3") or 0,
                    )
                    return data
                except Exception as err:
                    if attempt == 0:
                        _LOGGER.debug("Fetch failed, reconnecting and retrying: %s", err)
                        self._client.close()
                    else:
                        _LOGGER.error("Exception fetching all data: %s", err)
                        raise
        # Unreachable, but satisfies type checker
        raise ConnectionError("Failed to fetch data")

    def fetch_device_info(self) -> dict[str, Any]:
        """Fetch device identification info in a single connection."""
        _LOGGER.debug("Fetching device identification info")
        data: dict[str, Any] = {}

        try:
            with self._connection() as client:
                def read_string(start_address: int, count: int) -> str | None:
                    result = client.read_input_registers(address=start_address, count=count)
                    if result.isError():
                        return None
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

                def read_input(address: int) -> int | None:
                    result = client.read_input_registers(address=address, count=1)
                    if result.isError():
                        return None
                    return result.registers[0]

                data["serial_number"] = read_string(REG_SERIAL_START, 18)
                data["firmware_version"] = read_string(REG_FIRMWARE_VERSION_START, 41)
                data["item_number"] = read_string(REG_ITEM_NUMBER_START, 18)
                data["hw_max_current"] = read_input(REG_HW_MAX_CURRENT)

        except Exception as err:
            _LOGGER.error("Exception fetching device info: %s", err)
            raise

        _LOGGER.debug(
            "Device info: serial=%s, firmware=%s, item=%s",
            data.get("serial_number"),
            data.get("firmware_version"),
            data.get("item_number"),
        )
        return data
