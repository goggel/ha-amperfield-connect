"""Constants for the Amperfied Wallbox Connect integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

DOMAIN = "amperfield_connect"
DEFAULT_PORT = 502
DEFAULT_SCAN_INTERVAL = 10
CONF_CONTROL_MODE = "control_mode"
CONTROL_MODE_CURRENT = "current"
CONTROL_MODE_POWER = "power"
DEFAULT_CONTROL_MODE = CONTROL_MODE_POWER
CONF_NAME_PREFIX = "name_prefix"
DEFAULT_NAME_PREFIX = "Wallbox"

# Modbus Register Addresses
REG_MODBUS_VERSION = 4
REG_CHARGING_STATE = 5
REG_CURRENT_L1 = 6
REG_CURRENT_L2 = 7
REG_CURRENT_L3 = 8
REG_TEMPERATURE = 9
REG_VOLTAGE_L1 = 10
REG_VOLTAGE_L2 = 11
REG_VOLTAGE_L3 = 12
REG_EXTERN_LOCK = 13
REG_POWER = 14
REG_ENERGY_POWERON_HIGH = 15
REG_ENERGY_POWERON_LOW = 16
REG_ENERGY_INSTALL_HIGH = 17
REG_ENERGY_INSTALL_LOW = 18
REG_ENERGY_CYCLE_HIGH = 19
REG_ENERGY_CYCLE_LOW = 20
REG_POWER_L1 = 21
REG_POWER_L2 = 22
REG_POWER_L3 = 23
REG_HW_MAX_CURRENT = 100
REG_HW_MIN_CURRENT = 101
REG_WATCHDOG_TIMEOUT = 257
REG_REMOTE_LOCK = 259
REG_MAX_CURRENT = 261
REG_FAILSAFE_CURRENT = 262
REG_SERIAL_START = 1000
REG_SERIAL_END = 1017
REG_ITEM_NUMBER_START = 1050
REG_ITEM_NUMBER_END = 1067
REG_PRODUCTION_DATE_START = 1100
REG_PRODUCTION_DATE_END = 1117
REG_FIRMWARE_VERSION_START = 1250
REG_FIRMWARE_VERSION_END = 1290
REG_FIRMWARE_VARIANT_START = 1300
REG_FIRMWARE_VARIANT_END = 1340

# Phase Switch Registers (only for solar/solar pro models)
REG_MAX_POWER_TARGET = 500
REG_PHASE_SWITCH_CONTROL = 501
REG_CHARGING_STRATEGY = 502
REG_PHASE_SWITCH_DURATION = 503
REG_PHASE_SWITCH_WAITING = 504
REG_DISCONNECT_SIMULATION = 505
REG_MAX_POWER_SET = 5000
REG_PHASE_SWITCH_STATE = 5001
REG_CHARGING_STRATEGY_STATUS = 5002
REG_DISCONNECT_SIMULATION_STATUS = 5003

# Charging States (EN 61851-1 standard)
# Format: car state + wallbox state
CHARGING_STATES = {
    2: "no_vehicle_no_charging",  # A1: No vehicle plugged, wallbox doesn't allow
    3: "no_vehicle_wallbox_ready",  # A2: No vehicle plugged, wallbox allows
    4: "vehicle_plugged_no_charging",  # B1: Vehicle plugged, no charge request, wallbox doesn't allow
    5: "vehicle_plugged_wallbox_ready",  # B2: Vehicle plugged, no charge request, wallbox allows
    6: "charge_request_no_charging",  # C1: Vehicle plugged, charge request, wallbox doesn't allow
    7: "charging",  # C2: Vehicle plugged, charge request, wallbox allows
    8: "derating",
    9: "error",
    10: "wallbox_locked",
    11: "fault",
}

# Charging Strategy
CHARGING_STRATEGY_MANUAL = 0
CHARGING_STRATEGY_SOLAR = 1

CHARGING_STRATEGIES = {
    0: "manual_mode",
    1: "solar_eco_mode",
}

# Phase Switch States
PHASE_SWITCH_STATES = {
    0: "switching_in_progress",
    1: "1_phase",
    3: "3_phases",
}

# Model/Item Number Mapping
MODEL_MAPPING = {
    # connect.business 11 kW
    "00.779.2964": "connect.business 11kW",  # (5m)
    "00.779.2965": "connect.business 11kW",  # (7.5m)
    "00.779.3157": "connect.business 11kW",  # (7.5m mit RCD)
    # connect.home 11 kW
    "00.779.2795": "connect.home 11kW",  # (5m)
    "00.779.2963": "connect.home 11kW",  # (7.5m)
    # connect.solar 11 kW
    "00.779.3056": "connect.solar 11kW",  # (5m)
    "00.779.3057": "connect.solar 11kW",  # (7.5m)
    # Energy Control 11kW
    "00.779.3218": "Energy Control 11kW",  # (5m)
    "00.779.3219": "Energy Control 11kW",  # (7.5m)
    # connect.solar PRO 11 kW
    "00.779.3162": "connect.solar PRO 11kW",  # (7.5m)
}

PHASE_SWITCHING_ITEM_NUMBERS = {
    "00.779.3056",
    "00.779.3057",
    "00.779.3162",
}


@dataclass
class RegisterSpec:
    """Specification for reading a Modbus register."""

    register_type: Literal["input", "holding"]
    start_address: int
    count: int  # Number of registers
    decoder: Callable[[list[int]], Any]  # Function to decode raw register values
    solar_only: bool = False  # Only read for solar/solar pro models
    scale: float | None = (
        None  # Scaling factor for read/write (e.g., 10.0 for 0.1A resolution)
    )


# Helper functions for decoding register values
def _decode_uint16(registers: list[int]) -> int:
    """Decode single 16-bit unsigned integer."""
    return registers[0]


def _decode_int16(registers: list[int]) -> int:
    """Decode 16-bit signed integer (two's complement)."""
    value = registers[0]
    if value >= 32768:
        value = value - 65536
    return value


def _decode_uint32(registers: list[int]) -> int:
    """Decode 32-bit unsigned integer from two registers (big-endian)."""
    return (registers[0] << 16) | registers[1]


def _decode_string(registers: list[int]) -> str:
    """Decode a printable ASCII string from device-controlled registers."""
    decoded: list[str] = []
    for register in registers:
        for byte in ((register >> 8) & 0xFF, register & 0xFF):
            if byte == 0:
                return "".join(decoded)
            # The protocol specifies ASCII. Replacing controls and extended
            # bytes prevents a hostile/misconfigured endpoint from injecting
            # terminal controls or forged lines into Home Assistant logs.
            decoded.append(
                chr(byte) if 0x20 <= byte <= 0x7E else "\N{REPLACEMENT CHARACTER}"
            )
    return "".join(decoded)


# Register mapping: data_key -> register specification
# This map defines how to read each data key from Modbus registers
REGISTER_MAP: dict[str, RegisterSpec] = {
    # Basic sensor data (input registers 5-23)
    "charging_state": RegisterSpec(
        register_type="input",
        start_address=REG_CHARGING_STATE,
        count=1,
        decoder=_decode_uint16,
    ),
    "current_l1": RegisterSpec(
        register_type="input",
        start_address=REG_CURRENT_L1,
        count=1,
        decoder=_decode_uint16,
        scale=10.0,
    ),
    "current_l2": RegisterSpec(
        register_type="input",
        start_address=REG_CURRENT_L2,
        count=1,
        decoder=_decode_uint16,
        scale=10.0,
    ),
    "current_l3": RegisterSpec(
        register_type="input",
        start_address=REG_CURRENT_L3,
        count=1,
        decoder=_decode_uint16,
        scale=10.0,
    ),
    "temperature": RegisterSpec(
        register_type="input",
        start_address=REG_TEMPERATURE,
        count=1,
        decoder=_decode_int16,
        scale=10.0,
    ),
    "voltage_l1": RegisterSpec(
        register_type="input",
        start_address=REG_VOLTAGE_L1,
        count=1,
        decoder=_decode_uint16,
    ),
    "voltage_l2": RegisterSpec(
        register_type="input",
        start_address=REG_VOLTAGE_L2,
        count=1,
        decoder=_decode_uint16,
    ),
    "voltage_l3": RegisterSpec(
        register_type="input",
        start_address=REG_VOLTAGE_L3,
        count=1,
        decoder=_decode_uint16,
    ),
    "extern_lock": RegisterSpec(
        register_type="input",
        start_address=REG_EXTERN_LOCK,
        count=1,
        decoder=_decode_uint16,
    ),
    "power": RegisterSpec(
        register_type="input",
        start_address=REG_POWER,
        count=1,
        decoder=_decode_uint16,
    ),
    "energy_poweron": RegisterSpec(
        register_type="input",
        start_address=REG_ENERGY_POWERON_HIGH,
        count=2,
        decoder=_decode_uint32,
    ),
    "energy_installation": RegisterSpec(
        register_type="input",
        start_address=REG_ENERGY_INSTALL_HIGH,
        count=2,
        decoder=_decode_uint32,
    ),
    "energy_cycle": RegisterSpec(
        register_type="input",
        start_address=REG_ENERGY_CYCLE_HIGH,
        count=2,
        decoder=_decode_uint32,
    ),
    "power_l1": RegisterSpec(
        register_type="input",
        start_address=REG_POWER_L1,
        count=1,
        decoder=_decode_uint16,
    ),
    "power_l2": RegisterSpec(
        register_type="input",
        start_address=REG_POWER_L2,
        count=1,
        decoder=_decode_uint16,
    ),
    "power_l3": RegisterSpec(
        register_type="input",
        start_address=REG_POWER_L3,
        count=1,
        decoder=_decode_uint16,
    ),
    # Hardware limits
    "hw_max_current": RegisterSpec(
        register_type="input",
        start_address=REG_HW_MAX_CURRENT,
        count=1,
        decoder=_decode_uint16,
    ),
    "hw_min_current": RegisterSpec(
        register_type="input",
        start_address=REG_HW_MIN_CURRENT,
        count=1,
        decoder=_decode_uint16,
    ),
    "modbus_version": RegisterSpec(
        register_type="input",
        start_address=REG_MODBUS_VERSION,
        count=1,
        decoder=_decode_uint16,
    ),
    # Device identification (string registers)
    "serial_number": RegisterSpec(
        register_type="input",
        start_address=REG_SERIAL_START,
        count=18,
        decoder=_decode_string,
    ),
    "item_number": RegisterSpec(
        register_type="input",
        start_address=REG_ITEM_NUMBER_START,
        count=18,
        decoder=_decode_string,
    ),
    "production_date": RegisterSpec(
        register_type="input",
        start_address=REG_PRODUCTION_DATE_START,
        count=18,
        decoder=_decode_string,
    ),
    "firmware_version": RegisterSpec(
        register_type="input",
        start_address=REG_FIRMWARE_VERSION_START,
        count=41,
        decoder=_decode_string,
    ),
    "firmware_variant": RegisterSpec(
        register_type="input",
        start_address=REG_FIRMWARE_VARIANT_START,
        count=41,
        decoder=_decode_string,
    ),
    # Holding registers (control values)
    "remote_lock": RegisterSpec(
        register_type="holding",
        start_address=REG_REMOTE_LOCK,
        count=1,
        decoder=_decode_uint16,
    ),
    "max_current": RegisterSpec(
        register_type="holding",
        start_address=REG_MAX_CURRENT,
        count=1,
        decoder=_decode_uint16,
        scale=10.0,
    ),
    "failsafe_current": RegisterSpec(
        register_type="holding",
        start_address=REG_FAILSAFE_CURRENT,
        count=1,
        decoder=_decode_uint16,
        scale=10.0,
    ),
    # Solar/Solar PRO only - input registers
    "max_power_set": RegisterSpec(
        register_type="input",
        start_address=REG_MAX_POWER_SET,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
    "phase_switch_state": RegisterSpec(
        register_type="input",
        start_address=REG_PHASE_SWITCH_STATE,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
    "charging_strategy_status": RegisterSpec(
        register_type="input",
        start_address=REG_CHARGING_STRATEGY_STATUS,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
    "disconnect_simulation_status": RegisterSpec(
        register_type="input",
        start_address=REG_DISCONNECT_SIMULATION_STATUS,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
    # Solar/Solar PRO only - holding registers
    "max_power_target": RegisterSpec(
        register_type="holding",
        start_address=REG_MAX_POWER_TARGET,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
    "phase_switch_control": RegisterSpec(
        register_type="holding",
        start_address=REG_PHASE_SWITCH_CONTROL,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
    "charging_strategy": RegisterSpec(
        register_type="holding",
        start_address=REG_CHARGING_STRATEGY,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
    "phase_switch_duration": RegisterSpec(
        register_type="holding",
        start_address=REG_PHASE_SWITCH_DURATION,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
    "phase_switch_waiting": RegisterSpec(
        register_type="holding",
        start_address=REG_PHASE_SWITCH_WAITING,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
    "disconnect_simulation": RegisterSpec(
        register_type="holding",
        start_address=REG_DISCONNECT_SIMULATION,
        count=1,
        decoder=_decode_uint16,
        solar_only=True,
    ),
}
