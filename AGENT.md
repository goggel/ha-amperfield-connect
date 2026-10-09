# CLAUDE.md - Amperfied Wallbox Connect Integration

## Project Overview

Home Assistant custom integration for **Heidelberg Amperfied Wallbox Connect** EV chargers. Communicates via Modbus TCP protocol.

**Domain:** `amperfield_connect`
**IoT Class:** `local_polling`
**Requirements:** `pymodbus>=3.11.2,<4.0.0`

## Supported Wallbox Models

| Item Number                           | Model                  |
| ------------------------------------- | ---------------------- |
| 00.779.2964, 00.779.2965, 00.779.3157 | connect.business 11kW  |
| 00.779.2795, 00.779.2963              | connect.home 11kW      |
| 00.779.3056, 00.779.3057              | connect.solar 11kW     |
| 00.779.3218, 00.779.3219              | Energy Control 11kW    |
| 00.779.3162                           | connect.solar PRO 11kW |

**Note:** Solar/Solar PRO models support phase switching (1-phase/3-phase) and additional power management features.

## Architecture

```
custom_components/amperfield_connect/
├── __init__.py          # Integration setup, coordinator, device registration
├── config_flow.py       # Config flow + reconfigure flow
├── const.py             # Constants, register addresses, mappings
├── modbus_client.py     # Modbus TCP communication layer
├── sensor.py            # Sensor entities (power, current, voltage, energy, etc.)
├── binary_sensor.py     # Binary sensors (vehicle connected, phase switching available)
├── number.py            # Number entities (max current, failsafe current, max power target)
├── switch.py            # Switch entities (remote lock)
├── button.py            # Disconnect simulation command
├── select.py            # Select entities (charging strategy)
├── manifest.json        # Integration manifest
├── strings.json         # Base strings (references translations)
└── translations/
    ├── en.json          # English translations
    └── de.json          # German translations
```

## Key Components

### Connection Management

**CRITICAL:** The wallbox only accepts ONE Modbus TCP connection at a time.

The `AmperfieldModbusClient` uses one shared async TCP client per config entry:

- All operations acquire an async lock before talking to the wallbox
- Runtime setup calls `connect()` once and starts a 10s heartbeat
- `close()` stops the heartbeat and releases the TCP connection on unload/reconfigure
- This prevents concurrent requests while staying below the wallbox's default 15s watchdog timeout

For efficiency, batch methods are used:

- `fetch_all_data()` - Reads all sensor data through the shared client
- `fetch_device_info()` - Reads device identification through the shared client

Individual read/write methods still exist for write operations (e.g., setting max current).

### Data Flow

1. `AmperfieldModbusClient` handles low-level Modbus TCP communication
2. `AmperfieldDataUpdateCoordinator` polls data at configurable intervals (default: 10s)
3. All platforms (`sensor`, `binary_sensor`, `number`, `switch`, `select`, `button`) share:
   - Same `coordinator` instance
   - Same `device_info` (single device per integration entry)
   - Same `client` for write operations

### Device Identification

- **Unique ID:** Serial number from registers 1000-1017
- **Device Identifier:** `(DOMAIN, serial_number)`
- All entities belong to ONE device per config entry

## Modbus Registers

### Input Registers (Read-Only)

| Register  | Description                        | Unit                 |
| --------- | ---------------------------------- | -------------------- |
| 4         | Modbus version                     | -                    |
| 5         | Charging state                     | enum                 |
| 6-8       | Current L1/L2/L3                   | 0.1 A                |
| 9         | Temperature                        | 0.1 °C (signed)      |
| 10-12     | Voltage L1/L2/L3                   | V                    |
| 13        | External lock state                | 0=locked, 1=unlocked |
| 14        | Total power                        | W                    |
| 15-16     | Energy since power-on (32-bit)     | VAh                  |
| 17-18     | Energy since installation (32-bit) | VAh                  |
| 19-20     | Energy charge cycle (32-bit)       | VAh                  |
| 21-23     | Power L1/L2/L3                     | W                    |
| 100       | Hardware max current               | A                    |
| 1000-1017 | Serial number                      | ASCII                |
| 1050-1067 | Item/model number                  | ASCII                |
| 1250-1290 | Firmware version                   | ASCII                |

### Holding Registers (Read/Write)

| Register | Description         | Unit                 |
| -------- | ------------------- | -------------------- |
| 257      | Watchdog timeout    | ms                   |
| 259      | Remote lock         | 0=locked, 1=unlocked |
| 261      | Max current command | 0.1 A                |
| 262      | Failsafe current    | 0.1 A                |

### Solar/Solar PRO Only Registers

| Register | Description                                            |
| -------- | ------------------------------------------------------ |
| 500      | Max power target (W)                                   |
| 501      | Phase switch control (1 or 3)                          |
| 502      | Charging strategy (0=manual, 1=solar)                  |
| 5000     | Max power set (read-back)                              |
| 5001     | Phase switch state (0=switching, 1=1-phase, 3=3-phase) |

## Charging States (EN 61851-1)

| Value | State                       |
| ----- | --------------------------- |
| 2     | No vehicle connected        |
| 3     | Vehicle ready to connect    |
| 4     | Vehicle ready to charge     |
| 5     | Waiting for wallbox release |
| 6     | Charging paused             |
| 7     | Charging                    |
| 8     | Derating                    |
| 9     | Error                       |
| 10    | Not ready                   |
| 11    | Fault                       |

## Entity Types

### Sensors

- Charging state (enum)
- Current L1/L2/L3 (A)
- Voltage L1/L2/L3 (V)
- Power total/L1/L2/L3 (W)
- Temperature (°C)
- Energy since power-on/installation/charge cycle (kWh)
- Hardware max current (A)
- Phase switch state (solar models only)
- Max power set (solar models only)

### Binary Sensors

- Vehicle connected
- Phase switching available

### Numbers

- Maximum current (6-16A, step 0.1)
- Failsafe current (0-16A, step 0.1)
- Maximum power target (1380-11040W, solar models only)

### Switches

- Remote lock (charging locked/unlocked)

### Selects

- Charging strategy (Manual/Solar-Eco, solar models only)

## Configuration

### User Config Flow

- Host (IP address)
- Port (default: 502)
- Scan interval (default: 10 seconds)
- Name prefix (for multiple wallboxes)

### Reconfigure Flow

Allows changing all settings after initial setup without removing the integration.

## Development Notes

### Adding New Entities

1. Add register constant to `const.py`
2. Add read/write method to `modbus_client.py`
3. Add data key to `fetch_all_data()` in `modbus_client.py`
4. Create entity class in appropriate platform file
5. Add translations to `en.json` and `de.json`

### Translation Keys

Entity names use `translation_key` attribute. Format:

- Sensors: `sensor.<translation_key>.name`
- States: `sensor.<translation_key>.state.<state_value>`

### Testing Connection

```python
from pymodbus.client import ModbusTcpClient
client = ModbusTcpClient(host="192.168.x.x", port=502)
client.connect()
result = client.read_input_registers(address=4, count=1)  # Modbus version
print(result.registers[0])
```

## Debugging

The integration includes comprehensive logging to help diagnose issues with wallbox communication.

### Enabling Debug Logging

Add the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.amperfield_connect: debug
```

For even more detailed Modbus-level logging, you can also enable pymodbus debug:

```yaml
logger:
  default: info
  logs:
    custom_components.amperfield_connect: debug
    pymodbus: debug
```

After changing the configuration, restart Home Assistant.

### Log Levels

The integration uses the following log levels:

| Level       | What's Logged                                                                                                                                               |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **DEBUG**   | Connection lifecycle (open/close), individual register reads/writes with addresses and values, batch data fetches, coordinator updates, entity setup        |
| **INFO**    | Successful connection, device discovery (serial, model, firmware), integration setup/teardown, write operations (max current, lock, power target, strategy) |
| **WARNING** | Connection failures, coordinator update failures                                                                                                            |
| **ERROR**   | Modbus communication errors, failed write operations, invalid parameters                                                                                    |

### Example Debug Output

When debug logging is enabled, you'll see output like:

```
DEBUG custom_components.amperfield_connect.modbus_client - Testing connection to 192.168.1.100:502
INFO custom_components.amperfield_connect.modbus_client - Successfully connected to wallbox at 192.168.1.100:502
DEBUG custom_components.amperfield_connect.modbus_client - Started heartbeat task
DEBUG custom_components.amperfield_connect.modbus_client - Starting batch fetch of all sensor data
DEBUG custom_components.amperfield_connect.modbus_client - Batch fetch complete: charging_state=7, power=7400W, current=10.8/10.7/10.8 A
INFO custom_components.amperfield_connect.modbus_client - Setting max current to 12.0 A
DEBUG custom_components.amperfield_connect.modbus_client - Writing holding register 261 = 120
DEBUG custom_components.amperfield_connect.modbus_client - Successfully wrote holding register 261 = 120
```

### Diagnosing Connection Issues

1. **Enable debug logging** as shown above
2. **Check the logs** for connection open/close patterns
3. **Look for error messages** indicating what failed
4. **Verify register values** match expected behavior

Common patterns in logs:

- `Failed to connect` - Network issue or wallbox not reachable
- `Error reading input register` - Communication succeeded but register read failed
- `Exception fetching all data` - General communication problem during batch fetch

### Live Log Viewing

In Home Assistant, you can view logs in real-time:

1. Go to **Settings → System → Logs**
2. Filter by `amperfield_connect` to see only this integration's logs
3. Use the **Download full log** button for detailed analysis

## Common Issues

### Two Devices Showing

If duplicate devices appea
r, delete the orphaned device manually in Home Assistant:
Settings → Devices & Services → Devices → Find orphan → Delete

### Connection Failed

- Verify IP address is correct
- Ensure Modbus TCP is enabled on wallbox
- Check firewall allows port 502
- Only one Modbus TCP connection at a time is supported

## Links

- [pymodbus Documentation](https://pymodbus.readthedocs.io/)
- [Home Assistant Integration Development](https://developers.home-assistant.io/)
