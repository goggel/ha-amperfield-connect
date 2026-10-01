"""Modbus client for Amperfield Wallbox Connect."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import math
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from pymodbus.client import AsyncModbusTcpClient

from .const import REGISTER_MAP

_LOGGER = logging.getLogger(__name__)

# Modbus operation delay
MODBUS_DELAY = 0.05  # 50ms

# Keep-alive interval must stay below the wallbox watchdog default of 15 seconds.
HEARTBEAT_INTERVAL = 10.0

# Known readable ranges. Requests inside the same range can safely be combined;
# gaps between ranges may contain reserved registers and must not be spanned.
READ_BLOCKS: tuple[tuple[str, int, int], ...] = (
    ("input", 4, 23),
    ("input", 100, 101),
    ("input", 1000, 1017),
    ("input", 1050, 1067),
    ("input", 1100, 1117),
    ("input", 1250, 1290),
    ("input", 1300, 1340),
    ("input", 5000, 5003),
    ("holding", 259, 259),
    ("holding", 261, 262),
    ("holding", 500, 505),
)

MODBUS_ILLEGAL_ADDRESS = 2

# Only these holding registers are intentionally exposed for writes. Keeping an
# explicit allowlist prevents a future caller from turning the generic register
# helper into an arbitrary Modbus write primitive.
WRITABLE_DATA_KEYS = frozenset(
    {
        "remote_lock",
        "max_current",
        "failsafe_current",
        "max_power_target",
        "phase_switch_control",
        "charging_strategy",
        "phase_switch_duration",
        "phase_switch_waiting",
        "disconnect_simulation",
    }
)

_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def normalize_host(host: str) -> str:
    """Validate and normalize a host without accepting URLs or log controls."""
    if not isinstance(host, str):
        raise ValueError("Host must be a string")

    host = host.strip()
    if not host or len(host) > 253:
        raise ValueError("Host must contain between 1 and 253 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in host):
        raise ValueError("Host must not contain control characters")
    if any(char in host for char in "/?#@[]") or "://" in host:
        raise ValueError("Host must be a hostname or IP address, not a URL")

    try:
        ipaddress.ip_address(host)
    except ValueError:
        # Colons are valid only in an IPv6 literal. IDNA conversion bounds the
        # value to a resolvable hostname while still allowing internationalized
        # local hostnames.
        if ":" in host:
            raise ValueError("Invalid IP address") from None
        try:
            ascii_host = host.rstrip(".").encode("idna").decode("ascii")
        except UnicodeError as err:
            raise ValueError("Invalid hostname") from err
        if (
            not ascii_host
            or len(ascii_host) > 253
            or not _HOSTNAME_RE.fullmatch(ascii_host)
            or any(
                not label
                or len(label) > 63
                or label.startswith("-")
                or label.endswith("-")
                for label in ascii_host.split(".")
            )
        ):
            raise ValueError("Invalid hostname")

    return host


def validate_port(port: int) -> int:
    """Validate a TCP port without accepting booleans as integers."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Port must be an integer between 1 and 65535")
    return port


def _is_allowed_write_value(data_key: str, value: int | float) -> bool:
    """Return whether a value is safe for the documented register contract."""
    if data_key in {"remote_lock", "disconnect_simulation"}:
        return value in {0, 1}
    if data_key in {"max_current", "failsafe_current"}:
        return value == 0 or 6 <= value <= 16
    if data_key == "max_power_target":
        return value == 0 or 1400 <= value <= 11040
    if data_key == "phase_switch_control":
        return value in {1, 3}
    if data_key == "charging_strategy":
        return value in {0, 1}
    if data_key == "phase_switch_duration":
        return 15 <= value <= 900
    if data_key == "phase_switch_waiting":
        return 0 <= value <= 3600
    return False


class AmperfieldModbusError(Exception):
    """Base exception for wallbox communication errors."""


class AmperfieldConnectionError(AmperfieldModbusError):
    """Raised when the wallbox cannot be reached."""


class AmperfieldProtocolError(AmperfieldModbusError):
    """Raised when the wallbox returns an unexpected Modbus error."""


class AmperfieldUnsupportedRegisterError(AmperfieldProtocolError):
    """Raised when the wallbox reports an illegal register address."""


class AmperfieldModbusClient:
    """Async Modbus client for Amperfield Wallbox.

    The wallbox only accepts ONE Modbus TCP connection at a time.
    The pymodbus AsyncModbusTcpClient handles connection management internally.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = normalize_host(host)
        self.port = validate_port(port)
        self._client = AsyncModbusTcpClient(
            host=self.host, port=self.port, timeout=15, reconnect_delay=1
        )
        self._operation_lock = asyncio.Lock()  # Serialize all operations with delay
        self._heartbeat_task: asyncio.Task | None = None
        self._shutdown = False
        self._suspended = False
        _LOGGER.debug("Initialized async Modbus client for %s:%s", self.host, self.port)

    async def connect(self, *, start_heartbeat: bool = True) -> bool:
        """Connect to the wallbox and optionally start the runtime heartbeat."""
        _LOGGER.debug("Testing connection to %s:%s", self.host, self.port)
        try:
            async with self._operation_lock:
                self._suspended = False
                await self._ensure_connected_locked()

            if start_heartbeat:
                self._start_heartbeat()

            return self._client.connected
        except AmperfieldModbusError as err:
            _LOGGER.debug("Connection test failed: %s", err)
            return False

    async def close(self) -> None:
        """Close the connection and stop heartbeat."""
        self._shutdown = True
        self._suspended = True
        await self._stop_heartbeat()
        async with self._operation_lock:
            self._client.close()
        _LOGGER.debug("Closed connection to %s:%s", self.host, self.port)

    async def suspend(self) -> None:
        """Temporarily stop I/O while an endpoint is reconfigured."""
        self._suspended = True
        await self._stop_heartbeat()
        async with self._operation_lock:
            self._client.close()
        _LOGGER.debug("Suspended connection to %s:%s", self.host, self.port)

    async def resume(self) -> bool:
        """Resume a temporarily suspended runtime connection."""
        self._suspended = False
        self._shutdown = False
        connected = await self.connect(start_heartbeat=True)
        if not connected:
            # Keep retrying in the background after a failed reconfigure rollback.
            self._start_heartbeat()
        return connected

    def _start_heartbeat(self) -> None:
        """Start the heartbeat task if it is not already running."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._shutdown = False
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat(), name=f"amperfield-heartbeat-{self.host}"
            )
            _LOGGER.debug("Started heartbeat task")

    async def _stop_heartbeat(self) -> None:
        """Cancel and await the heartbeat task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            _LOGGER.debug("Stopped heartbeat task")
        self._heartbeat_task = None

    async def _ensure_connected_locked(self) -> None:
        """Ensure the client is connected while the operation lock is held."""
        if self._suspended:
            raise AmperfieldConnectionError("Modbus client is temporarily suspended")
        if not self._client.connected:
            _LOGGER.debug("Client not connected, connecting...")
            try:
                connected = await self._client.connect()
            except Exception as err:
                raise AmperfieldConnectionError(
                    f"Failed to connect to {self.host}:{self.port}: {err}"
                ) from err
            if not connected:
                raise AmperfieldConnectionError(
                    f"Failed to connect to {self.host}:{self.port}"
                )
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

                version = await self._read_using_register_map("modbus_version")
                _LOGGER.debug(
                    "Heartbeat: connection alive (modbus version: %d)", version
                )
            except asyncio.CancelledError:
                _LOGGER.debug("Heartbeat task cancelled")
                break
            except Exception as err:
                _LOGGER.debug("Heartbeat error: %s", err)
        _LOGGER.debug("Heartbeat task stopped")

    async def _with_delay(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        """Execute a Modbus operation with global delay to prevent
        overwhelming the wallbox.
        """
        async with self._operation_lock:
            await self._ensure_connected_locked()
            try:
                result = await operation()
            except AmperfieldModbusError:
                raise
            except Exception as err:
                raise AmperfieldConnectionError(
                    f"Modbus request to {self.host}:{self.port} failed: {err}"
                ) from err
            await asyncio.sleep(MODBUS_DELAY)
            return result

    @staticmethod
    def _raise_for_result(
        result: Any, *, operation: str, allow_unsupported: bool = False
    ) -> None:
        """Raise a typed exception for a Modbus error response."""
        if not result.isError():
            return
        exception_code = getattr(result, "exception_code", None)
        if allow_unsupported and exception_code == MODBUS_ILLEGAL_ADDRESS:
            raise AmperfieldUnsupportedRegisterError(f"{operation}: {result}")
        raise AmperfieldProtocolError(f"{operation}: {result}")

    async def _read_range(
        self,
        register_type: str,
        address: int,
        count: int,
        *,
        allow_unsupported: bool = False,
    ) -> list[int]:
        """Read and validate one Modbus register range."""

        async def _read() -> list[int]:
            if register_type == "input":
                result = await self._client.read_input_registers(
                    address=address, count=count
                )
            else:
                result = await self._client.read_holding_registers(
                    address=address, count=count
                )
            self._raise_for_result(
                result,
                operation=f"reading {register_type} registers {address}-{address + count - 1}",
                allow_unsupported=allow_unsupported,
            )
            return result.registers

        return await self._with_delay(_read)

    # --- Core register operations (all routing through REGISTER_MAP) ---

    async def _read_using_register_map(self, data_key: str) -> Any | None:
        """Read a register value using REGISTER_MAP decoder.

        Universal read method that handles all register types (uint16, int16,
        uint32, string) through the decoder defined in RegisterSpec.
        Applies scaling when defined in the spec.
        """
        if data_key not in REGISTER_MAP:
            raise ValueError(f"Data key '{data_key}' not found in REGISTER_MAP")

        spec = REGISTER_MAP[data_key]

        registers = await self._read_range(
            spec.register_type, spec.start_address, spec.count
        )
        raw = spec.decoder(registers)
        return raw / spec.scale if spec.scale else raw

    async def _write_using_register_map(
        self, data_key: str, value: int | float
    ) -> bool:
        """Write a register value using REGISTER_MAP spec for address and scale."""
        if data_key not in REGISTER_MAP:
            _LOGGER.error("Data key '%s' not found in REGISTER_MAP", data_key)
            return False

        spec = REGISTER_MAP[data_key]
        if data_key not in WRITABLE_DATA_KEYS or spec.register_type != "holding":
            _LOGGER.error("Refusing write to non-writable data key '%s'", data_key)
            return False
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            _LOGGER.error("Refusing invalid numeric value for '%s'", data_key)
            return False
        if not _is_allowed_write_value(data_key, value):
            _LOGGER.error("Refusing unsafe value for '%s'", data_key)
            return False

        write_value = round(value * spec.scale) if spec.scale else int(value)
        if not 0 <= write_value <= 0xFFFF:
            _LOGGER.error("Refusing out-of-range value for '%s'", data_key)
            return False

        async def _write():
            result = await self._client.write_register(
                address=spec.start_address, value=write_value
            )
            self._raise_for_result(
                result,
                operation=f"writing register {spec.start_address} for {data_key}",
            )
            _LOGGER.debug(
                "Successfully wrote %s = %s (raw: %d)", data_key, value, write_value
            )
            return True

        try:
            return await self._with_delay(_write)
        except AmperfieldModbusError as err:
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
        strategy_name = (
            "manual"
            if strategy == 0
            else "solar" if strategy == 1 else f"unknown({strategy})"
        )
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
        _LOGGER.info(
            "Setting disconnect simulation to %s", "enabled" if enabled else "disabled"
        )
        return await self._write_using_register_map(
            "disconnect_simulation", 1 if enabled else 0
        )

    # --- Batch data fetching ---

    async def _do_fetch_all_data(
        self, *, supports_phase_switching: bool = False
    ) -> dict[str, Any]:
        """Fetch all registers appropriate for the detected wallbox model."""
        keys = {key for key, spec in REGISTER_MAP.items() if not spec.solar_only}
        if supports_phase_switching:
            keys.update(key for key, spec in REGISTER_MAP.items() if spec.solar_only)
        return await self._do_fetch_selected_data(keys)

    async def fetch_all_data(
        self, *, supports_phase_switching: bool = False
    ) -> dict[str, Any]:
        """Fetch all data appropriate for the detected wallbox model."""
        _LOGGER.debug("Starting batch fetch of all sensor data")
        try:
            data = await self._do_fetch_all_data(
                supports_phase_switching=supports_phase_switching
            )
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
        _LOGGER.debug(
            "Starting smart fetch for %d data keys: %s",
            len(required_keys),
            sorted(required_keys),
        )
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

        Keys in known contiguous ranges are read in a single transaction. If a
        combined range is unsupported, it is retried per key so optional
        registers can become unknown without hiding transport failures.
        """
        data: dict[str, Any] = {}

        unknown_keys = required_keys - REGISTER_MAP.keys()
        for key in sorted(unknown_keys):
            _LOGGER.warning("Data key '%s' not found in REGISTER_MAP, skipping", key)

        grouped: dict[tuple[str, int, int], list[str]] = defaultdict(list)
        for key in sorted(required_keys & REGISTER_MAP.keys()):
            spec = REGISTER_MAP[key]
            matching_block = next(
                (
                    block
                    for block in READ_BLOCKS
                    if block[0] == spec.register_type
                    and block[1] <= spec.start_address
                    and spec.start_address + spec.count - 1 <= block[2]
                ),
                (
                    spec.register_type,
                    spec.start_address,
                    spec.start_address + spec.count - 1,
                ),
            )
            grouped[matching_block].append(key)

        for (register_type, _block_start, _block_end), keys in grouped.items():
            start = min(REGISTER_MAP[key].start_address for key in keys)
            end = max(
                REGISTER_MAP[key].start_address + REGISTER_MAP[key].count - 1
                for key in keys
            )
            try:
                registers = await self._read_range(
                    register_type,
                    start,
                    end - start + 1,
                    allow_unsupported=True,
                )
            except AmperfieldUnsupportedRegisterError:
                _LOGGER.debug(
                    "Combined range %s %d-%d is not fully supported; retrying per key",
                    register_type,
                    start,
                    end,
                )
                for key in keys:
                    spec = REGISTER_MAP[key]
                    try:
                        key_registers = await self._read_range(
                            spec.register_type,
                            spec.start_address,
                            spec.count,
                            allow_unsupported=True,
                        )
                    except AmperfieldUnsupportedRegisterError:
                        data[key] = None
                    else:
                        data[key] = self._decode_value(spec, key_registers)
                continue

            for key in keys:
                spec = REGISTER_MAP[key]
                offset = spec.start_address - start
                data[key] = self._decode_value(
                    spec, registers[offset : offset + spec.count]
                )

        return data

    @staticmethod
    def _decode_value(spec: Any, registers: list[int]) -> Any:
        """Decode and scale a value according to its register specification."""
        raw = spec.decoder(registers)
        return raw / spec.scale if spec.scale else raw

    async def probe_phase_switching(self) -> bool:
        """Return whether the phase-switch state register is supported."""
        spec = REGISTER_MAP["phase_switch_state"]
        try:
            await self._read_range(
                spec.register_type,
                spec.start_address,
                spec.count,
                allow_unsupported=True,
            )
        except AmperfieldUnsupportedRegisterError:
            return False
        return True

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
