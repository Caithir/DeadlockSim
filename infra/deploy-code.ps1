# Deploy DeadlockSim code to an existing Azure Web App (PowerShell)
# Usage: .\deploy-code.ps1 [-ResourceGroup <name>] [-AppName <name>]
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Subscription selected (az account set --subscription <id>)

param(
    [string]$ResourceGroup = "deadlocksim-rg",
    [string]$AppName = "deadlocksim"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent

Write-Host "=== DeadlockSim Code Deployment ===" -ForegroundColor Cyan
Write-Host "App:            $AppName"
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Source:         $ProjectRoot"
Write-Host ""

# Configure the startup command
Write-Host "Setting startup command..."
az webapp config set `
    --resource-group $ResourceGroup `
    --name $AppName `
    --startup-file "startup.sh"

# Configure app settings
Write-Host "Configuring app settings..."
az webapp config appsettings set `
    --resource-group $ResourceGroup `
    --name $AppName `
    --settings `
        SCM_DO_BUILD_DURING_DEPLOYMENT=true `
        WEBSITES_PORT=8080 `
        WEBSITE_HEALTHCHECK_MAXPINGFAILURES=5

# Enable WebSockets (required by NiceGUI)
az webapp config set `
    --resource-group $ResourceGroup `
    --name $AppName `
    --web-sockets-enabled true

# Deploy code via zip deploy
Write-Host ""
Write-Host "Deploying code..."
Push-Location $ProjectRoot
try {
    az webapp up `
        --resource-group $ResourceGroup `
        --name $AppName `
        --runtime "PYTHON:3.14"
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "=== Deployment complete ===" -ForegroundColor Green
Write-Host "URL: https://$AppName.azurewebsites.net"
Write-Host ""
Write-Host "View logs:"
Write-Host "  az webapp log tail --resource-group $ResourceGroup --name $AppName"
