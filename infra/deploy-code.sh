#!/bin/bash
# Deploy DeadlockSim code to an existing Azure Web App
# Usage: ./deploy-code.sh [resource-group] [app-name]
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Subscription selected (az account set --subscription <id>)

set -euo pipefail

RESOURCE_GROUP="${1:-deadlocksim-rg}"
APP_NAME="${2:-deadlocksim}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== DeadlockSim Code Deployment ==="
echo "App:            $APP_NAME"
echo "Resource Group: $RESOURCE_GROUP"
echo "Source:         $PROJECT_ROOT"
echo ""

# Configure the startup command
echo "Setting startup command..."
az webapp config set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --startup-file "startup.sh"

# Configure app settings
echo "Configuring app settings..."
az webapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --settings \
    SCM_DO_BUILD_DURING_DEPLOYMENT=true \
    WEBSITES_PORT=8080 \
    WEBSITE_HEALTHCHECK_MAXPINGFAILURES=5

# Enable WebSockets (required by NiceGUI)
az webapp config set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --web-sockets-enabled true

# Deploy code via zip deploy
echo ""
echo "Deploying code..."
cd "$PROJECT_ROOT"
az webapp up \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --runtime "PYTHON:3.14"

echo ""
echo "=== Deployment complete ==="
echo "URL: https://$APP_NAME.azurewebsites.net"
echo ""
echo "View logs:"
echo "  az webapp log tail --resource-group $RESOURCE_GROUP --name $APP_NAME"
