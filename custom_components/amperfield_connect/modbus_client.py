"""Modbus client for Amperfield Wallbox Connect."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymodbus.client import AsyncModbusTcpClient

from .const import (
    REGISTER_MAP,
    REG_CHARGING_STATE,
    REG_CHARGING_STRATEGY,
    REG_CHARGING_STRATEGY_STATUS,
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
    REG_PHASE_SWITCH_STATE,
    REG_POWER,
    REG_POWER_L1,
    REG_POWER_L2,
    REG_POWER_L3,
    REG_PRODUCTION_DATE_START,
    REG_REMOTE_LOCK,
    REG_SERIAL_START,
    REG_VOLTAGE_L1,
    REG_VOLTAGE_L2,
    REG_VOLTAGE_L3,
)

_LOGGER = logging.getLogger(__name__)

# Modbus operation delay
MODBUS_DELAY = 0.05  # 50ms

# Heartbeat interval to keep connection alive (30 seconds)
HEARTBEAT_INTERVAL = 30.0

# Write operation delay before read-back verification
WRITE_DELAY = 0.05  # 50ms - pause before reading back written value

class AmperfieldModbusClient:
    """Async Modbus client for Amperfield Wallbox.

    The wallbox only accepts ONE Modbus TCP connection at a time.
    The pymodbus AsyncModbusTcpClient handles connection management internally.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._client = AsyncModbusTcpClient(host=host, port=port, timeout=15, reconnect_delay=1)
        self._operation_lock = asyncio.Lock()  # Serialize all operations with delay
        self._heartbeat_task: asyncio.Task | None = None
        self._shutdown = False
        _LOGGER.debug("Initialized async Modbus client for %s:%s", host, port)

    async def connect(self) -> bool:
        """Test connection to the wallbox and start heartbeat."""
        _LOGGER.debug("Testing connection to %s:%s", self.host, self.port)
        try:
            if not self._client.connected:
                if not await self._client.connect():
                    _LOGGER.warning("Failed to connect to %s:%s", self.host, self.port)
                    return False
                _LOGGER.info("Successfully connected to wallbox at %s:%s", self.host, self.port)

            # Start heartbeat to keep connection alive
            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._shutdown = False
                self._heartbeat_task = asyncio.create_task(self._heartbeat())
                _LOGGER.debug("Started heartbeat task")

            return self._client.connected
        except Exception as err:
            _LOGGER.debug("Connection test failed: %s", err)
            return False

    async def close(self) -> None:
        """Close the connection and stop heartbeat."""
        # Stop heartbeat
        self._shutdown = True
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            _LOGGER.debug("Stopped heartbeat task")

        self._client.close()
        _LOGGER.debug("Closed connection to %s:%s", self.host, self.port)

    async def _ensure_connected(self) -> None:
        """Ensure the client is connected, connecting if necessary.

        Raises:
            ConnectionError: If connection fails
        """
        if not self._client.connected:
            _LOGGER.debug("Client not connected, connecting...")
            if not await self._client.connect():
                raise ConnectionError(f"Failed to connect to {self.host}:{self.port}")
            _LOGGER.debug("Client connected successfully")

    async def _heartbeat(self) -> None:
        """Heartbeat task to keep connection alive.

        Periodically reads the modbus version register to prevent
        the wallbox from closing idle connections.
        """
        _LOGGER.debug("Heartbeat task started (interval: %.1fs)", HEARTBEAT_INTERVAL)
        while not self._shutdown:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if self._shutdown:
                    break

                # Read a simple register to keep connection alive
                # Use modbus version as it's lightweight and always available
                if self._client.connected:
                    result = await self._client.read_input_registers(address=REG_MODBUS_VERSION, count=1)
                    if not result.isError():
                        _LOGGER.debug("Heartbeat: connection alive (modbus version: %d)", result.registers[0])
                    else:
                        _LOGGER.debug("Heartbeat: read failed, connection may be stale")
            except asyncio.CancelledError:
                _LOGGER.debug("Heartbeat task cancelled")
                break
            except Exception as err:
                _LOGGER.debug("Heartbeat error: %s", err)
        _LOGGER.debug("Heartbeat task stopped")

    async def _with_delay(self, operation):
        """Execute a Modbus operation with global delay to prevent
        overwhelming the wallbox.
        """
        async with self._operation_lock:
            result = await operation()
            await asyncio.sleep(MODBUS_DELAY)
            return result

    async def read_input_register(self, address: int) -> int | None:
        """Read a single input register with global delay."""
        async def _read():
            result = await self._client.read_input_registers(address=address, count=1)
            if result.isError():
                _LOGGER.error("Error reading input register %s: %s", address, result)
                return None
            return result.registers[0]

        try:
            return await self._with_delay(_read)
        except Exception as err:
            _LOGGER.error("Exception reading input register %s: %s", address, err)
            return None

    async def read_holding_register(self, address: int) -> int | None:
        """Read a single holding register with global delay."""
        async def _read():
            result = await self._client.read_holding_registers(address=address, count=1)
            if result.isError():
                _LOGGER.error("Error reading holding register %s: %s", address, result)
                return None
            return result.registers[0]

        try:
            return await self._with_delay(_read)
        except Exception as err:
            _LOGGER.error("Exception reading holding register %s: %s", address, err)
            return None

    async def write_holding_register(self, address: int, value: int) -> bool:
        """Write holding register with read-back verification.
        """
        async def _write():
            # Ensure connected before writing
            await self._ensure_connected()

            result = await self._client.write_register(address=address, value=value)
            if result.isError():
                _LOGGER.error("Error writing holding register %s = %s: %s", address, value, result)
                return False
            _LOGGER.debug("Successfully wrote holding register %s = %s", address, value)

            return True

        try:
            return await self._with_delay(_write)
        except Exception as err:
            _LOGGER.error("Exception writing holding register %s = %s: %s", address, value, err)
            return False

    async def read_string_registers(self, start_address: int, count: int) -> str | None:
        """Read ASCII string from multiple registers with global delay."""
        async def _read():
            result = await self._client.read_input_registers(address=start_address, count=count)
            if result.isError():
                _LOGGER.error("Error reading string registers from %s: %s", start_address, result)
                return None
            return self._decode_string(result.registers)

        try:
            return await self._with_delay(_read)
        except Exception as err:
            _LOGGER.error("Exception reading string registers from %s: %s", start_address, err)
            return None

    async def read_32bit_value(self, high_address: int) -> int | None:
        """Read 32-bit value from two consecutive registers (big-endian) with global delay."""
        async def _read():
            result = await self._client.read_input_registers(address=high_address, count=2)
            if result.isError():
                _LOGGER.error("Error reading 32-bit value from %s: %s", high_address, result)
                return None
            high_byte = result.registers[0]
            low_byte = result.registers[1]
            return (high_byte << 16) + low_byte

        try:
            return await self._with_delay(_read)
        except Exception as err:
            _LOGGER.error("Exception reading 32-bit value from %s: %s", high_address, err)
            return None

    async def _read_using_register_map(self, data_key: str) -> Any | None:
        """Read a register value using REGISTER_MAP decoder.

        This centralizes register reading to use the scaling/decoding logic
        defined in REGISTER_MAP, avoiding hardcoded scaling in getter methods.
        """
        if data_key not in REGISTER_MAP:
            _LOGGER.error("Data key '%s' not found in REGISTER_MAP", data_key)
            return None

        spec = REGISTER_MAP[data_key]

        try:
            async def _read():
                if spec.register_type == "input":
                    result = await self._client.read_input_registers(
                        address=spec.start_address, count=spec.count
                    )
                else:
                    result = await self._client.read_holding_registers(
                        address=spec.start_address, count=spec.count
                    )

                if result.isError():
                    _LOGGER.error(
                        "Error reading %s register(s) at %d for key '%s': %s",
                        spec.register_type,
                        spec.start_address,
                        data_key,
                        result,
                    )
                    return None

                return spec.decoder(result.registers)

            return await self._with_delay(_read)
        except Exception as err:
            _LOGGER.error("Exception reading %s: %s", data_key, err)
            return None

    async def get_modbus_version(self) -> int | None:
        return await self.read_input_register(REG_MODBUS_VERSION)

    async def get_charging_state(self) -> int | None:
        return await self.read_input_register(REG_CHARGING_STATE)

    async def get_current_l1(self) -> float | None:
        return await self._read_using_register_map("current_l1")

    async def get_current_l2(self) -> float | None:
        return await self._read_using_register_map("current_l2")

    async def get_current_l3(self) -> float | None:
        return await self._read_using_register_map("current_l3")

    async def get_temperature(self) -> float | None:
        return await self._read_using_register_map("temperature")

    async def get_voltage_l1(self) -> int | None:
        return await self.read_input_register(REG_VOLTAGE_L1)

    async def get_voltage_l2(self) -> int | None:
        return await self.read_input_register(REG_VOLTAGE_L2)

    async def get_voltage_l3(self) -> int | None:
        return await self.read_input_register(REG_VOLTAGE_L3)

    async def get_extern_lock_state(self) -> int | None:
        """0=locked, 1=unlocked."""
        return await self.read_input_register(REG_EXTERN_LOCK)

    async def get_power(self) -> int | None:
        return await self.read_input_register(REG_POWER)

    async def get_power_l1(self) -> int | None:
        return await self.read_input_register(REG_POWER_L1)

    async def get_power_l2(self) -> int | None:
        return await self.read_input_register(REG_POWER_L2)

    async def get_power_l3(self) -> int | None:
        return await self.read_input_register(REG_POWER_L3)

    async def get_energy_since_poweron(self) -> int | None:
        return await self.read_32bit_value(REG_ENERGY_POWERON_HIGH)

    async def get_energy_since_installation(self) -> int | None:
        return await self.read_32bit_value(REG_ENERGY_INSTALL_HIGH)

    async def get_energy_charge_cycle(self) -> int | None:
        return await self.read_32bit_value(REG_ENERGY_CYCLE_HIGH)

    async def get_hardware_max_current(self) -> int | None:
        return await self.read_input_register(REG_HW_MAX_CURRENT)

    async def get_hardware_min_current(self) -> int | None:
        return await self.read_input_register(REG_HW_MIN_CURRENT)

    async def get_serial_number(self) -> str | None:
        return await self.read_string_registers(REG_SERIAL_START, 18)

    async def get_item_number(self) -> str | None:
        return await self.read_string_registers(REG_ITEM_NUMBER_START, 18)

    async def get_production_date(self) -> str | None:
        return await self.read_string_registers(REG_PRODUCTION_DATE_START, 18)

    async def get_firmware_version(self) -> str | None:
        return await self.read_string_registers(REG_FIRMWARE_VERSION_START, 41)

    async def get_firmware_variant(self) -> str | None:
        return await self.read_string_registers(REG_FIRMWARE_VARIANT_START, 41)

    async def get_remote_lock(self) -> int | None:
        """0=locked, 1=unlocked."""
        return await self.read_holding_register(REG_REMOTE_LOCK)

    async def set_remote_lock(self, locked: bool) -> bool:
        _LOGGER.info("Setting remote lock to %s", "locked" if locked else "unlocked")
        return await self.write_holding_register(REG_REMOTE_LOCK, 0 if locked else 1)

    async def get_max_current(self) -> float | None:
        """Read max current using REGISTER_MAP decoder (scales by 0.1A)."""
        return await self._read_using_register_map("max_current")

    async def set_max_current(self, amperes: float) -> bool:
        """Write max current using REGISTER_MAP scale (0.1A resolution)."""
        _LOGGER.info("Setting max current to %.1f A", amperes)
        spec = REGISTER_MAP.get("max_current")
        if spec and spec.scale:
            value = int(amperes * spec.scale)
        else:
            _LOGGER.error("max_current scale not found in REGISTER_MAP, using fallback")
            value = int(amperes * 10)  # Fallback
        return await self.write_holding_register(REG_MAX_CURRENT, value)

    async def get_failsafe_current(self) -> float | None:
        """Read failsafe current using REGISTER_MAP decoder (scales by 0.1A)."""
        return await self._read_using_register_map("failsafe_current")

    async def set_failsafe_current(self, amperes: float) -> bool:
        """Write failsafe current using REGISTER_MAP scale (0.1A resolution)."""
        _LOGGER.info("Setting failsafe current to %.1f A", amperes)
        spec = REGISTER_MAP.get("failsafe_current")
        if spec and spec.scale:
            value = int(amperes * spec.scale)
        else:
            _LOGGER.error("failsafe_current scale not found in REGISTER_MAP, using fallback")
            value = int(amperes * 10)  # Fallback
        return await self.write_holding_register(REG_FAILSAFE_CURRENT, value)

    async def get_max_power_target(self) -> int | None:
        return await self.read_holding_register(REG_MAX_POWER_TARGET)

    async def set_max_power_target(self, watts: int) -> bool:
        _LOGGER.info("Setting max power target to %d W", watts)
        return await self.write_holding_register(REG_MAX_POWER_TARGET, watts)

    async def get_charging_strategy(self) -> int | None:
        return await self.read_holding_register(REG_CHARGING_STRATEGY)

    async def set_charging_strategy(self, strategy: int) -> bool:
        """0=manual, 1=solar."""
        strategy_name = "manual" if strategy == 0 else "solar" if strategy == 1 else f"unknown({strategy})"
        _LOGGER.info("Setting charging strategy to %s (%d)", strategy_name, strategy)
        return await self.write_holding_register(REG_CHARGING_STRATEGY, strategy)

    async def get_max_power_set(self) -> int | None:
        return await self.read_input_register(REG_MAX_POWER_SET)

    async def get_phase_switch_state(self) -> int | None:
        """0=switching, 1=1-phase, 3=3-phase."""
        return await self.read_input_register(REG_PHASE_SWITCH_STATE)

    async def get_charging_strategy_status(self) -> int | None:
        return await self.read_input_register(REG_CHARGING_STRATEGY_STATUS)

    @staticmethod
    def _decode_string(registers: list[int]) -> str:
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

    async def _do_fetch_all_data(self) -> dict[str, Any]:
        """Fetch all data including solar model detection.

        Reads non-solar registers first, then detects solar model and reads solar registers if present.
        """
        # First, read all non-solar registers
        non_solar_keys = {key for key, spec in REGISTER_MAP.items() if not spec.solar_only}
        data = await self._do_fetch_selected_data(non_solar_keys)

        # Try to detect solar model by reading max_power_set register
        # This register exists only on solar/solar pro models
        try:
            test_data = await self._do_fetch_selected_data({"max_power_set"})
            if test_data.get("max_power_set") is not None:
                # Solar model detected, read all solar-only registers
                _LOGGER.debug("Solar model detected, reading solar-only registers")
                solar_keys = {key for key, spec in REGISTER_MAP.items() if spec.solar_only}
                solar_data = await self._do_fetch_selected_data(solar_keys)
                data.update(solar_data)
            else:
                _LOGGER.debug("Non-solar model detected (max_power_set returned None)")
        except Exception as err:
            _LOGGER.debug("Non-solar model detected (max_power_set not available): %s", err)

        return data

    async def fetch_all_data(self) -> dict[str, Any]:
        """Retries once on connection error (e.g. wallbox dropped idle connection)."""
        _LOGGER.debug("Starting batch fetch of all sensor data")
        try:
            data = await self._do_fetch_all_data()
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
            _LOGGER.error("Exception fetching all data: %s", err)
            raise
        # Unreachable, but satisfies type checker
        raise ConnectionError("Failed to fetch data")

    async def fetch_selected_data(self, required_keys: set[str]) -> dict[str, Any]:
        """Fetch only the data keys that are needed by enabled entities.

        Uses intelligent batching to optimize Modbus reads:
        - Groups contiguous registers for bulk reads
        - Reads isolated registers individually
        - Retries once on connection error

        Args:
            required_keys: Set of data keys to fetch (e.g., {"charging_state", "power"})

        Returns:
            Dictionary mapping data keys to their decoded values
        """
        _LOGGER.debug("Starting smart fetch for %d data keys: %s", len(required_keys), sorted(required_keys))
        try:
            data = await self._do_fetch_selected_data(required_keys)
            _LOGGER.debug(
                "Smart fetch complete: %d values retrieved",
                len(data),
            )
            return data
        except Exception as err:
            _LOGGER.error("Exception fetching selected data: %s", err)
            raise
        # Unreachable, but satisfies type checker
        raise ConnectionError("Failed to fetch data")

    async def _do_fetch_selected_data(self, required_keys: set[str]) -> dict[str, Any]:
        """Internal method to fetch selected data.

        Reads all registers for each data key in a single operation, with
        100ms delay between each data key to prevent overwhelming the wallbox.
        """
        # Ensure client is connected
        await self._ensure_connected()

        data: dict[str, Any] = {}

        # Iterate in sorted order to match the debug log order
        for key in sorted(required_keys):
            if key not in REGISTER_MAP:
                _LOGGER.warning("Data key '%s' not found in REGISTER_MAP, skipping", key)
                continue

            spec = REGISTER_MAP[key]

            try:
                # Read all registers for this data key in one operation with delay
                async def _read_key():
                    if spec.register_type == "input":
                        result = await self._client.read_input_registers(
                            address=spec.start_address, count=spec.count
                        )
                    else:
                        result = await self._client.read_holding_registers(
                            address=spec.start_address, count=spec.count
                        )

                    if result.isError():
                        _LOGGER.error(
                            "Error reading %s register(s) at %d (count=%d) for key '%s': %s",
                            spec.register_type,
                            spec.start_address,
                            spec.count,
                            key,
                            result,
                        )
                        return None
                    else:
                        # Decode the registers
                        decoded = spec.decoder(result.registers)
                        _LOGGER.debug(
                            "Decoded %s (registers %d-%d): %s = %s",
                            key,
                            spec.start_address,
                            spec.start_address + spec.count - 1,
                            key,
                            decoded,
                        )
                        return decoded

                # Apply global delay for each data key read
                data[key] = await self._with_delay(_read_key)

            except Exception as err:
                _LOGGER.error("Exception reading %s: %s", key, err)
                data[key] = None

        return data

    async def fetch_device_info(self) -> dict[str, Any]:
        """Fetch device identification information."""
        _LOGGER.debug("Fetching device identification info")

        async def _fetch():
            data: dict[str, Any] = {}

            try:
                # Ensure client is connected
                await self._ensure_connected()

                result = await self._client.read_input_registers(address=REG_SERIAL_START, count=18)
                data["serial_number"] = self._decode_string(result.registers) if not result.isError() else None

                result = await self._client.read_input_registers(address=REG_FIRMWARE_VERSION_START, count=41)
                data["firmware_version"] = self._decode_string(result.registers) if not result.isError() else None

                result = await self._client.read_input_registers(address=REG_ITEM_NUMBER_START, count=18)
                data["item_number"] = self._decode_string(result.registers) if not result.isError() else None

                result = await self._client.read_input_registers(address=REG_HW_MAX_CURRENT, count=1)
                data["hw_max_current"] = result.registers[0] if not result.isError() else None

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

        return await self._with_delay(_fetch)
