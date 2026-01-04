"""Constants for the Amperfield Wallbox Connect integration."""

DOMAIN = "amperfield_connect"
DEFAULT_PORT = 502
DEFAULT_SCAN_INTERVAL = 10
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
CHARGING_STATES = {
    2: "no_vehicle_connected",
    3: "vehicle_ready_to_connect",
    4: "vehicle_connected",
    5: "vehicle_ready_to_charge",
    6: "charging_paused",
    7: "charging",
    8: "derating",
    9: "error",
    10: "not_ready",
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
    "00.779.2964": "connect.business 11kW", # (5m)
    "00.779.2965": "connect.business 11kW", # (7.5m)
    "00.779.3157": "connect.business 11kW", # (7.5m mit RCD)
    # connect.home 11 kW
    "00.779.2795": "connect.home 11kW", # (5m)
    "00.779.2963": "connect.home 11kW", # (7.5m)
    # connect.solar 11 kW
    "00.779.3056": "connect.solar 11kW", # (5m)
    "00.779.3057": "connect.solar 11kW", # (7.5m)
    # Energy Control 11kW
    "00.779.3218": "Energy Control 11kW", # (5m)
    "00.779.3219": "Energy Control 11kW", # (7.5m)
    # connect.solar PRO 11 kW
    "00.779.3162": "connect.solar PRO 11kW", # (7.5m)
}
