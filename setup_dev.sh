#!/bin/bash
set -e

echo "Setting up development environment for Amperfied Wallbox Connect..."
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3.11 or higher"
    exit 1
fi

echo "Creating virtual environment..."
python3 -m venv venv

echo ""
echo "Activating virtual environment..."
source venv/bin/activate

echo ""
echo "Installing development dependencies..."
pip install --upgrade pip
pip install -r requirements_dev.txt

echo ""
echo "========================================"
echo "Setup complete!"
echo "========================================"
echo ""
echo "To activate the virtual environment in the future, run:"
echo "  source venv/bin/activate"
echo ""
echo "VS Code should automatically detect the virtual environment."
echo "If not, press Ctrl+Shift+P and select 'Python: Select Interpreter'"
echo ""
