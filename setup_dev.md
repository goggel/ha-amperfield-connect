# Development Environment Setup

This guide helps you set up a local development environment with Home Assistant dependencies for better IDE support.

## Option 1: Virtual Environment (Recommended)

### Step 1: Create Virtual Environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

### Step 2: Install Dependencies

```bash
pip install -r requirements_dev.txt
```

### Step 3: Configure VS Code (if using)

Create or update `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/venv/Scripts/python.exe",
  "python.analysis.typeCheckingMode": "basic",
  "python.analysis.autoImportCompletions": true,
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": false,
  "python.linting.flake8Enabled": false,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "[python]": {
    "editor.defaultFormatter": "ms-python.black-formatter",
    "editor.codeActionsOnSave": {
      "source.organizeImports": "explicit"
    }
  }
}
```

## Option 2: Use devcontainer (Advanced)

Home Assistant provides an official devcontainer for development. Create `.devcontainer/devcontainer.json`:

```json
{
  "name": "Home Assistant Custom Component",
  "image": "ghcr.io/home-assistant/devcontainer:latest",
  "features": {
    "ghcr.io/devcontainers/features/python:1": {}
  },
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "ms-python.vscode-pylance",
        "ms-python.black-formatter"
      ],
      "settings": {
        "python.pythonPath": "/usr/bin/python3",
        "python.analysis.typeCheckingMode": "basic"
      }
    }
  },
  "postCreateCommand": "pip install -r requirements_dev.txt"
}
```

## Option 3: Lightweight - Just Type Stubs

If you want minimal installation for just type hints:

```bash
pip install homeassistant-stubs pymodbus types-requests
```

## Verifying Setup

Test that imports work correctly:

```python
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity
from pymodbus.client import ModbusTcpClient

print("All imports successful!")
```

## Running Tests

Once set up, you can run tests:

```bash
# Run pytest
pytest tests/

# Run type checking
mypy custom_components/amperfield_connect/

# Format code
black custom_components/amperfield_connect/

# Lint code
ruff check custom_components/amperfield_connect/
```

## IDE-Specific Configuration

### PyCharm

1. Go to Settings → Project → Python Interpreter
2. Add new interpreter → Virtual Environment
3. Select existing environment: `venv`
4. Mark `custom_components` as Sources Root

### VS Code

1. Press `Ctrl+Shift+P`
2. Type "Python: Select Interpreter"
3. Choose the venv interpreter
4. Install recommended extensions:
   - Python (ms-python.python)
   - Pylance (ms-python.vscode-pylance)
   - Black Formatter (ms-python.black-formatter)

## Troubleshooting

### Windows: Scripts execution policy error

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Import errors in IDE but code works

- Reload window (VS Code: `Ctrl+Shift+P` → "Reload Window")
- Restart IDE
- Verify correct Python interpreter is selected

### Type checking errors with Home Assistant

Some Home Assistant types may show warnings - this is normal. The integration will still work in Home Assistant.
