#!/bin/bash
# Azure App Service startup script for DeadlockSim.
# The deployment package contains the prebuilt `deadlock-sim` binary and `data/`.
# Azure sets PORT; the server must accept remote connections, hence 0.0.0.0.
set -e
cd "$(dirname "$0")"
chmod +x ./deadlock-sim
exec ./deadlock-sim serve --host 0.0.0.0 --port "${PORT:-8000}"
