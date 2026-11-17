#!/bin/bash
# Deploy DeadlockSim code to an existing Azure Web App
# Usage: ./deploy-code.sh [resource-group] [app-name]
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Rust with the x86_64-unknown-linux-musl target, musl-tools and zip
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

TARGET="x86_64-unknown-linux-musl"
PACKAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$PACKAGE_DIR"' EXIT

# Build a static binary (needs: rustup target add $TARGET, and musl-tools)
echo "Building release binary..."
cd "$PROJECT_ROOT"
cargo build --release --locked --target "$TARGET"

echo "Assembling deployment package..."
cp "target/$TARGET/release/deadlock-sim" startup.sh "$PACKAGE_DIR/"
cp -r data "$PACKAGE_DIR/data"
(cd "$PACKAGE_DIR" && zip -qr package.zip deadlock-sim startup.sh data)

# Configure the startup command
echo "Setting startup command..."
az webapp config set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --startup-file "bash startup.sh"

# The package is prebuilt: skip the Oryx build
echo "Configuring app settings..."
az webapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --settings \
    SCM_DO_BUILD_DURING_DEPLOYMENT=false \
    WEBSITE_HEALTHCHECK_MAXPINGFAILURES=5

echo ""
echo "Deploying package..."
az webapp deploy \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --src-path "$PACKAGE_DIR/package.zip" \
  --type zip

echo ""
echo "=== Deployment complete ==="
echo "URL: https://$APP_NAME.azurewebsites.net"
echo ""
echo "View logs:"
echo "  az webapp log tail --resource-group $RESOURCE_GROUP --name $APP_NAME"
