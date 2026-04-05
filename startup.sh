#!/bin/bash
# Azure App Service startup script for DeadlockSim (NiceGUI)
set -e

# Install the package (entry points + editable mode)
pip install -e .

# Start the NiceGUI web interface on port 8080
exec deadlock-sim-gui
