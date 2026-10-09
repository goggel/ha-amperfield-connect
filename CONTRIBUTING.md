# Contributing to Amperfied Wallbox Connect Integration

Thank you for your interest in contributing! This guide will help you set up your development environment.

## Quick Start

### Windows

1. Run the setup script:
   ```cmd
   setup_dev.bat
   ```

2. Open the project in VS Code (it will prompt to install recommended extensions)

3. The virtual environment should be automatically detected

### Linux/macOS

1. Make the script executable and run it:
   ```bash
   chmod +x setup_dev.sh
   ./setup_dev.sh
   ```

2. Open the project in VS Code

3. The virtual environment should be automatically detected

## Manual Setup

See [setup_dev.md](setup_dev.md) for detailed manual setup instructions.

## Development Workflow

### Activating the Environment

**Windows:**
```cmd
venv\Scripts\activate
```

**Linux/macOS:**
```bash
source venv/bin/activate
```

### Code Formatting

Format your code before committing:
```bash
black custom_components/amperfield_connect/
```

### Linting

Check for code issues:
```bash
ruff check custom_components/amperfield_connect/
```

### Type Checking

Run type checking:
```bash
mypy custom_components/amperfield_connect/
```

### Testing Changes

To test your changes in a real Home Assistant instance:

1. Copy the `custom_components/amperfield_connect` folder to your Home Assistant `config/custom_components/` directory

2. Restart Home Assistant

3. Add the integration through the UI

## Project Structure

```
custom_components/amperfield_connect/
├── __init__.py          # Integration setup and coordinator
├── config_flow.py       # UI configuration
├── const.py             # Constants and register definitions
├── modbus_client.py     # Modbus TCP communication layer
├── sensor.py            # Sensor entities (monitoring)
├── number.py            # Number entities (current control)
├── switch.py            # Switch entities (lock control)
├── button.py            # Momentary command entities
├── select.py            # Select entities (phase/strategy selection)
├── manifest.json        # Integration metadata
└── strings.json         # UI text translations
```

## Adding New Features

### Adding a New Sensor

1. Add the register address to [const.py](custom_components/amperfield_connect/const.py)
2. Add a getter method to [modbus_client.py](custom_components/amperfield_connect/modbus_client.py)
3. Add the sensor to the data fetch in [sensor.py](custom_components/amperfield_connect/sensor.py)
4. Create a new sensor class in [sensor.py](custom_components/amperfield_connect/sensor.py)
5. Add the sensor to the entities list in `async_setup_entry`

### Adding a New Control

1. Choose the appropriate platform (number, switch, select, button)
2. Add register addresses to [const.py](custom_components/amperfield_connect/const.py)
3. Add getter/setter methods to [modbus_client.py](custom_components/amperfield_connect/modbus_client.py)
4. Create entity class in the appropriate platform file
5. Add to the entities list in `async_setup_entry`

## Code Style

- Follow PEP 8 style guide
- Use type hints for all function parameters and return values
- Add docstrings to all classes and public methods
- Keep line length to 88 characters (Black default)
- Use descriptive variable names

## Commit Guidelines

- Write clear, descriptive commit messages
- Reference issue numbers when applicable
- Keep commits focused on a single change

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Format and lint your code
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Getting Help

- Check existing [GitHub Issues](https://github.com/goggel/ha-amperfield-connect/issues)
- Review the [official Amperfied Modbus documentation](https://wallbox.amperfied.com/support/wissensdatenbank/connect-series/)
- Open a new issue for bugs or feature requests

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
