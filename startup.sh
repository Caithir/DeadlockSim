#!/bin/bash
# Azure App Service startup script for DeadlockSim (NiceGUI)
set -e

# Dependencies are installed by Oryx during deployment (SCM_DO_BUILD_DURING_DEPLOYMENT).
# Run the GUI module directly — reads PORT env var set by Azure (default 8000).
exec python -m deadlock_sim.ui.gui
