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

$Target = "x86_64-unknown-linux-musl"
$PackageDir = Join-Path ([System.IO.Path]::GetTempPath()) ("deadlocksim-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $PackageDir | Out-Null

# Build a static Linux binary. Cross-compiling from Windows needs a musl
# cross toolchain (for example `cargo install cross`, then use `cross build`).
Write-Host "Building release binary..."
Push-Location $ProjectRoot
try {
    cargo build --release --locked --target $Target
    if ($LASTEXITCODE -ne 0) { throw "cargo build failed" }
    Copy-Item "target/$Target/release/deadlock-sim", "startup.sh" $PackageDir
    Copy-Item "data" (Join-Path $PackageDir "data") -Recurse
}
finally {
    Pop-Location
}
$Zip = Join-Path $PackageDir "package.zip"
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $Zip

# Configure the startup command
Write-Host "Setting startup command..."
az webapp config set `
    --resource-group $ResourceGroup `
    --name $AppName `
    --startup-file "bash startup.sh"

# The package is prebuilt: skip the Oryx build
Write-Host "Configuring app settings..."
az webapp config appsettings set `
    --resource-group $ResourceGroup `
    --name $AppName `
    --settings `
        SCM_DO_BUILD_DURING_DEPLOYMENT=false `
        WEBSITE_HEALTHCHECK_MAXPINGFAILURES=5

Write-Host ""
Write-Host "Deploying package..."
az webapp deploy `
    --resource-group $ResourceGroup `
    --name $AppName `
    --src-path $Zip `
    --type zip
Remove-Item $PackageDir -Recurse -Force

Write-Host ""
Write-Host "=== Deployment complete ===" -ForegroundColor Green
Write-Host "URL: https://$AppName.azurewebsites.net"
Write-Host ""
Write-Host "View logs:"
Write-Host "  az webapp log tail --resource-group $ResourceGroup --name $AppName"
