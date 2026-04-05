# Deploy DeadlockSim infrastructure to Azure (PowerShell)
# Usage: .\deploy.ps1 -ResourceGroup <name> [-Location <region>]
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Subscription selected (az account set --subscription <id>)

param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroup,

    [string]$Location = "westus3"
)

$TemplateFile = Join-Path $PSScriptRoot "azuredeploy.json"
$ParamsFile = Join-Path $PSScriptRoot "azuredeploy.parameters.json"

Write-Host "=== DeadlockSim Azure Deployment ===" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Location:       $Location"
Write-Host ""

# Create resource group if it doesn't exist
$ErrorActionPreference = "SilentlyContinue"
$rgExists = az group show --name $ResourceGroup 2>&1
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating resource group '$ResourceGroup' in '$Location'..."
    az group create --name $ResourceGroup --location $Location | Out-Null
}

# Validate template
Write-Host "Validating ARM template..."
az deployment group validate `
    --resource-group $ResourceGroup `
    --template-file $TemplateFile `
    --parameters "@$ParamsFile"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Template validation failed."
    exit 1
}

Write-Host "Validation passed." -ForegroundColor Green
Write-Host ""

# Deploy
$deploymentName = "deadlocksim-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Write-Host "Deploying infrastructure (deployment: $deploymentName)..."
az deployment group create `
    --resource-group $ResourceGroup `
    --template-file $TemplateFile `
    --parameters "@$ParamsFile" `
    --name $deploymentName

if ($LASTEXITCODE -ne 0) {
    Write-Error "Deployment failed."
    exit 1
}

Write-Host ""
Write-Host "=== Deployment complete ===" -ForegroundColor Green
Write-Host ""

# Show outputs
az deployment group show `
    --resource-group $ResourceGroup `
    --name $deploymentName `
    --query "properties.outputs" `
    -o table
