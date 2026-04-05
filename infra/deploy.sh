#!/bin/bash
# Deploy DeadlockSim infrastructure to Azure
# Usage: ./deploy.sh <resource-group-name> [location]
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Subscription selected (az account set --subscription <id>)

set -euo pipefail

RESOURCE_GROUP="${1:?Usage: $0 <resource-group-name> [location]}"
LOCATION="${2:-westus3}"
TEMPLATE_FILE="$(dirname "$0")/azuredeploy.json"
PARAMS_FILE="$(dirname "$0")/azuredeploy.parameters.json"

echo "=== DeadlockSim Azure Deployment ==="
echo "Resource Group: $RESOURCE_GROUP"
echo "Location:       $LOCATION"
echo ""

# Create resource group if it doesn't exist
if ! az group show --name "$RESOURCE_GROUP" &>/dev/null; then
  echo "Creating resource group '$RESOURCE_GROUP' in '$LOCATION'..."
  az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
fi

# Validate template
echo "Validating ARM template..."
az deployment group validate \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$TEMPLATE_FILE" \
  --parameters @"$PARAMS_FILE"

echo "Validation passed."
echo ""

# Deploy
echo "Deploying infrastructure..."
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$TEMPLATE_FILE" \
  --parameters @"$PARAMS_FILE" \
  --name "deadlocksim-$(date +%Y%m%d-%H%M%S)"

echo ""
echo "=== Deployment complete ==="
echo ""

# Show outputs
az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$(az deployment group list --resource-group "$RESOURCE_GROUP" --query '[0].name' -o tsv)" \
  --query 'properties.outputs' \
  -o table
