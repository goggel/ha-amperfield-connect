"""Modbus client for Amperfield Wallbox Connect."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymodbus.client import AsyncModbusTcpClient

from .const import REGISTER_MAP

_LOGGER = logging.getLogger(__name__)

# Modbus operation delay
MODBUS_DELAY = 0.05  # 50ms

# Keep-alive interval must stay below the wallbox watchdog default of 15 seconds.
HEARTBEAT_INTERVAL = 10.0


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
                    _LOGGER.debug("Failed to connect to %s:%s", self.host, self.port)
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

                if self._client.connected:
                    version = await self._read_using_register_map("modbus_version")
                    if version is not None:
                        _LOGGER.debug("Heartbeat: connection alive (modbus version: %d)", version)
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

    # --- Core register operations (all routing through REGISTER_MAP) ---

    async def _read_using_register_map(self, data_key: str) -> Any | None:
        """Read a register value using REGISTER_MAP decoder.

        Universal read method that handles all register types (uint16, int16,
        uint32, string) through the decoder defined in RegisterSpec.
        Applies scaling when defined in the spec.
        """
        if data_key not in REGISTER_MAP:
            _LOGGER.error("Data key '%s' not found in REGISTER_MAP", data_key)
            return None

        spec = REGISTER_MAP[data_key]

        try:
            async def _read():
                await self._ensure_connected()

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

                raw = spec.decoder(result.registers)
                return raw / spec.scale if spec.scale else raw

            return await self._with_delay(_read)
        except Exception as err:
            _LOGGER.error("Exception reading %s: %s", data_key, err)
            return None

    async def _write_using_register_map(self, data_key: str, value: int | float) -> bool:
        """Write a register value using REGISTER_MAP spec for address and scale."""
        if data_key not in REGISTER_MAP:
            _LOGGER.error("Data key '%s' not found in REGISTER_MAP", data_key)
            return False

        spec = REGISTER_MAP[data_key]
        write_value = round(value * spec.scale) if spec.scale else int(value)

        async def _write():
            await self._ensure_connected()
            result = await self._client.write_register(
                address=spec.start_address, value=write_value
            )
            if result.isError():
                _LOGGER.error(
                    "Error writing register %d = %s for key '%s': %s",
                    spec.start_address, write_value, data_key, result,
                )
                return False
            _LOGGER.debug("Successfully wrote %s = %s (raw: %d)", data_key, value, write_value)
            return True

        try:
            return await self._with_delay(_write)
        except Exception as err:
            _LOGGER.error("Exception writing %s = %s: %s", data_key, value, err)
            return False

    # --- Read accessors ---

    async def get_modbus_version(self) -> int | None:
        return await self._read_using_register_map("modbus_version")

    async def get_charging_state(self) -> int | None:
        return await self._read_using_register_map("charging_state")

    async def get_current_l1(self) -> float | None:
        return await self._read_using_register_map("current_l1")

    async def get_current_l2(self) -> float | None:
        return await self._read_using_register_map("current_l2")

    async def get_current_l3(self) -> float | None:
        return await self._read_using_register_map("current_l3")

    async def get_temperature(self) -> float | None:
        return await self._read_using_register_map("temperature")

    async def get_voltage_l1(self) -> int | None:
        return await self._read_using_register_map("voltage_l1")

    async def get_voltage_l2(self) -> int | None:
        return await self._read_using_register_map("voltage_l2")

    async def get_voltage_l3(self) -> int | None:
        return await self._read_using_register_map("voltage_l3")

    async def get_extern_lock_state(self) -> int | None:
        """0=locked, 1=unlocked."""
        return await self._read_using_register_map("extern_lock")

    async def get_power(self) -> int | None:
        return await self._read_using_register_map("power")

    async def get_power_l1(self) -> int | None:
        return await self._read_using_register_map("power_l1")

    async def get_power_l2(self) -> int | None:
        return await self._read_using_register_map("power_l2")

    async def get_power_l3(self) -> int | None:
        return await self._read_using_register_map("power_l3")

    async def get_energy_since_poweron(self) -> int | None:
        return await self._read_using_register_map("energy_poweron")

    async def get_energy_since_installation(self) -> int | None:
        return await self._read_using_register_map("energy_installation")

    async def get_energy_charge_cycle(self) -> int | None:
        return await self._read_using_register_map("energy_cycle")

    async def get_hardware_max_current(self) -> int | None:
        return await self._read_using_register_map("hw_max_current")

    async def get_hardware_min_current(self) -> int | None:
        return await self._read_using_register_map("hw_min_current")

    async def get_serial_number(self) -> str | None:
        return await self._read_using_register_map("serial_number")

    async def get_item_number(self) -> str | None:
        return await self._read_using_register_map("item_number")

    async def get_production_date(self) -> str | None:
        return await self._read_using_register_map("production_date")

    async def get_firmware_version(self) -> str | None:
        return await self._read_using_register_map("firmware_version")

    async def get_firmware_variant(self) -> str | None:
        return await self._read_using_register_map("firmware_variant")

    async def get_remote_lock(self) -> int | None:
        """0=locked, 1=unlocked."""
        return await self._read_using_register_map("remote_lock")

    async def get_max_current(self) -> float | None:
        return await self._read_using_register_map("max_current")

    async def get_failsafe_current(self) -> float | None:
        return await self._read_using_register_map("failsafe_current")

    async def get_max_power_target(self) -> int | None:
        return await self._read_using_register_map("max_power_target")

    async def get_charging_strategy(self) -> int | None:
        return await self._read_using_register_map("charging_strategy")

    async def get_max_power_set(self) -> int | None:
        return await self._read_using_register_map("max_power_set")

    async def get_phase_switch_state(self) -> int | None:
        """0=switching, 1=1-phase, 3=3-phase."""
        return await self._read_using_register_map("phase_switch_state")

    async def get_charging_strategy_status(self) -> int | None:
        return await self._read_using_register_map("charging_strategy_status")

    async def get_phase_switch_duration(self) -> int | None:
        return await self._read_using_register_map("phase_switch_duration")

    async def get_phase_switch_waiting(self) -> int | None:
        return await self._read_using_register_map("phase_switch_waiting")

    async def get_disconnect_simulation(self) -> int | None:
        return await self._read_using_register_map("disconnect_simulation")

    # --- Write accessors ---

    async def set_remote_lock(self, locked: bool) -> bool:
        _LOGGER.info("Setting remote lock to %s", "locked" if locked else "unlocked")
        return await self._write_using_register_map("remote_lock", 0 if locked else 1)

    async def set_max_current(self, amperes: float) -> bool:
        _LOGGER.info("Setting max current to %.1f A", amperes)
        return await self._write_using_register_map("max_current", amperes)

    async def set_failsafe_current(self, amperes: float) -> bool:
        _LOGGER.info("Setting failsafe current to %.1f A", amperes)
        return await self._write_using_register_map("failsafe_current", amperes)

    async def set_max_power_target(self, watts: int) -> bool:
        _LOGGER.info("Setting max power target to %d W", watts)
        return await self._write_using_register_map("max_power_target", watts)

    async def set_charging_strategy(self, strategy: int) -> bool:
        """0=manual, 1=solar."""
        strategy_name = "manual" if strategy == 0 else "solar" if strategy == 1 else f"unknown({strategy})"
        _LOGGER.info("Setting charging strategy to %s (%d)", strategy_name, strategy)
        return await self._write_using_register_map("charging_strategy", strategy)

    async def set_phase_switch_duration(self, seconds: int) -> bool:
        _LOGGER.info("Setting phase switch duration to %d s", seconds)
        return await self._write_using_register_map("phase_switch_duration", seconds)

    async def set_phase_switch_waiting(self, seconds: int) -> bool:
        _LOGGER.info("Setting phase switch waiting time to %d s", seconds)
        return await self._write_using_register_map("phase_switch_waiting", seconds)

    async def set_disconnect_simulation(self, enabled: bool) -> bool:
        """Enable or disable disconnect simulation."""
        _LOGGER.info("Setting disconnect simulation to %s", "enabled" if enabled else "disabled")
        return await self._write_using_register_map("disconnect_simulation", 1 if enabled else 0)

    # --- Batch data fetching ---

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

    async def fetch_selected_data(self, required_keys: set[str]) -> dict[str, Any]:
        """Fetch only the data keys that are needed by enabled entities.

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

    async def _do_fetch_selected_data(self, required_keys: set[str]) -> dict[str, Any]:
        """Internal method to fetch selected data.

        Reads all registers for each data key in a single operation, with
        delay between each data key to prevent overwhelming the wallbox.
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
                        # Decode the registers, applying scale if defined
                        raw = spec.decoder(result.registers)
                        decoded = raw / spec.scale if spec.scale else raw
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
        data = await self._do_fetch_selected_data(
            {"serial_number", "firmware_version", "item_number", "hw_max_current"}
        )
        _LOGGER.debug(
            "Device info: serial=%s, firmware=%s, item=%s",
            data.get("serial_number"),
            data.get("firmware_version"),
            data.get("item_number"),
        )
        return data
