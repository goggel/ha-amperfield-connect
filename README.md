# Amperfield Wallbox Connect - Home Assistant Integration

This is a custom Home Assistant integration for the Amperfield Wallbox Connect Series (home, business, solar, solar pro) using Modbus TCP communication.

## Features

This integration provides comprehensive monitoring and control of your Amperfield Wallbox:

### Sensors

- **Charging State** - Current charging state with vehicle connection status
- **Current (L1, L2, L3)** - Real-time current per phase
- **Voltage (L1, L2, L3)** - Voltage per phase
- **Power** - Total power consumption
- **Power (L1, L2, L3)** - Power per phase
- **Temperature** - Internal wallbox temperature
- **Energy Since Power On** - Energy consumed since last restart
- **Energy Since Installation** - Total energy consumed (MID meter if available)
- **Energy Charge Cycle** - Energy consumed in current charging session
- **Phase Switch State** - Current phase configuration (solar/solar pro only)
- **Maximum Power Set** - Current power target setting (solar/solar pro only)

### Controls

- **Maximum Current** - Set the maximum charging current (0A to disable, 6-16A for charging)
- **Failsafe Current** - Set fallback current in case of communication loss
- **Remote Lock** - Lock/unlock the wallbox remotely
- **Maximum Power Target** - Set target power in Watts, wallbox automatically switches phases (solar/solar pro only)
- **Charging Strategy** - Select Manual or Solar/Eco mode (solar/solar pro only)
- **Disconnect Simulation** - Enable/disable disconnect simulation for phase switching (solar/solar pro only)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/benja/ha-amperfield-connect`
6. Select "Integration" as the category
7. Click "Add"
8. Click "Install" on the Amperfield Wallbox Connect integration
9. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/amperfield_connect` directory to your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Amperfield Wallbox Connect"
4. Enter your wallbox connection details:
   - **IP Address or Hostname**: The IP address of your wallbox (or hostname like `hdm-smart-connect-XXXXXX.fritz.box`)
   - **Port**: Modbus TCP port (default: 502)
   - **Scan Interval**: How often to poll the wallbox in seconds (default: 10)

### Finding Your Wallbox

The wallbox can be found by:

- **IP Address**: Check your router for the device IP (recommended to set a static IP)
- **Hostname**: `HDM-SMART-CONNECT-XXXXXX` where XXXXXX is the last 6 characters of the MAC address
- On some routers (e.g., FRITZ!Box), you can use: `hdm-smart-connect-xxxxxx.fritz.box`

## Modbus TCP Configuration

- **Port**: 502 (default Modbus TCP port)
- **Only one connection** can be active at a time on port 502
- The integration uses the official Modbus TCP register layout (versions 1.0.8 - 2.0.4)

## Important Notes

### Current Control

- Setting **Maximum Current** to `0A` will stop charging
- Valid charging range: `6.0A - 16.0A` (depending on your hardware configuration)
- Values between `0.1A and 5.9A` are **not allowed** and will be treated as `0A`
- After changing current, it's recommended to keep the value stable for at least 20 seconds

### Watchdog Timer

The integration keeps Modbus communication active with polling and a heartbeat that are below the wallbox watchdog default. If communication is lost, the wallbox will use the **Failsafe Current** setting when watchdog timeout mode is active.

### Phase Switching (Solar/Solar Pro Only)

- Only available on `connect.solar` and `connect.solar pro` models
- **Automatic phase switching** based on available power
- Set the **Maximum Power Target** in Watts, and the wallbox automatically switches between 1-phase and 3-phase charging
- Monitor the current phase state via the **Phase Switch State** sensor
- Works in conjunction with **Charging Strategy** (Manual or Solar/Eco mode)

### Energy Meters

If your wallbox has an internal MID power meter, the energy and power values are suitable for billing purposes. Otherwise, they are for informational use only.

## Supported Models

- Amperfield Wallbox Connect Home (≥ V1.0.8)
- Amperfield Wallbox Connect Business (≥ V2.0.0)
- Amperfield Wallbox Connect Solar (≥ V2.0.1)
- Amperfield Wallbox Connect Solar Pro (≥ V2.0.1)

## Troubleshooting

### Cannot Connect

- Verify the IP address and port are correct
- Ensure only one Modbus connection is active (close any other Modbus tools)
- Check that port 502 is not blocked by a firewall
- Try pinging the wallbox to ensure network connectivity

### Sensors Show "Unavailable"

- Check the scan interval isn't too short
- Verify the wallbox is powered on and connected to the network
- Check Home Assistant logs for specific error messages

### Updates are Slow

- Increase the scan interval in the integration configuration
- Remember that only one Modbus connection can be active at a time

## Support

For issues and feature requests, please visit:

- GitHub Issues: https://github.com/benja/ha-amperfield-connect/issues
- Official Amperfield Documentation: https://www.amperfied.de/de/service-support/downloads/

## License

This integration is not officially affiliated with Amperfield GmbH. Use at your own risk.

## Credits

Based on the official Amperfield Wallbox Connect Series Modbus TCP documentation (Version 1.0.8 - 2.0.4).
